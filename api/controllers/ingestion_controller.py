from typing import List, Dict, Any

import datetime
import json
import logging
import os

try:
    import pwd
except ImportError:  # pragma: no cover - non-Unix platforms
    pwd = None

import redis

from configs.config import settings
from api.utils import (
    sanitize_filename,
    is_allowed_extension,
    resolve_path_under,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_UPLOAD,
    ALLOWED_EXTENSIONS,
)
from api.deps import graph_engine, vector_engine, ingestor
from workers.celery_worker import ingest_document_task, _set_status

logger = logging.getLogger(__name__)


INGESTION_STATE = {
    "is_processing": False,
    "status": "idle",
    "progress": 0,
    "graph_done": 0,
    "graph_total": 0,
    "files_in_batch": 0,
    "file_names": [],
    "pending": False,
}


def progress_callback(
    status_msg: str,
    percent: int,
    graph_done: int | None = None,
    graph_total: int | None = None,
    files_in_batch: int | None = None,
    file_names: list | None = None,
) -> None:
    INGESTION_STATE["status"] = status_msg
    INGESTION_STATE["progress"] = percent
    if graph_done is not None:
        INGESTION_STATE["graph_done"] = graph_done
    if graph_total is not None:
        INGESTION_STATE["graph_total"] = graph_total
    if files_in_batch is not None:
        INGESTION_STATE["files_in_batch"] = files_in_batch
    if file_names is not None:
        INGESTION_STATE["file_names"] = file_names

def handle_upload(files) -> Dict[str, Any]:
    """处理文件上传逻辑，不抛 HTTPException。

    可能抛 ValueError 表示 4xx 场景，由路由转换成 HTTPException。
    """
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise ValueError(f"Too many files. Maximum {MAX_FILES_PER_UPLOAD} files per upload.")

    if not os.path.exists(settings.DATA_RAW_DIR):
        os.makedirs(settings.DATA_RAW_DIR)

    saved_files: List[str] = []
    for file in files:
        safe_name = sanitize_filename(file.filename)
        if not safe_name:
            raise ValueError(f"Invalid filename: {file.filename!r}")
        if not is_allowed_extension(safe_name):
            allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise ValueError(f"File type not allowed: {file.filename}. Allowed: {allowed}")

        file_path = os.path.join(settings.DATA_RAW_DIR, safe_name)
        size = 0
        with open(file_path, "wb") as buffer:
            while True:
                chunk = file.file.read(8192)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE_BYTES:
                    buffer.close()
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    raise ValueError(
                        f"File {safe_name} exceeds maximum size "
                        f"({MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB)."
                    )
                buffer.write(chunk)
        saved_files.append(safe_name)

    # 使用 Celery 异步队列，每个文件一个任务，并写入 Redis 状态为 queued。
    # 如果 Celery / Redis 不可用（例如测试环境未启动 Redis），则静默降级为仅保存文件，
    # 由外部显式调用 ingestor.ingest_data() 完成同步摄取。
    for fname in saved_files:
        try:
            _set_status(fname, "queued")
            file_path = os.path.join(settings.DATA_RAW_DIR, fname)
            ingest_document_task.delay(file_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to enqueue Celery task for %s: %s", fname, e)

    if len(saved_files) == 1:
        return {"status": "queued", "filename": saved_files[0], "files": saved_files}
    return {"status": "queued", "filename": saved_files, "files": saved_files}


def list_documents_controller() -> List[Dict[str, Any]]:
    if not os.path.exists(settings.DATA_RAW_DIR):
        return []

    def get_owner(path: str) -> str:
        if pwd:
            try:
                return pwd.getpwuid(os.stat(path).st_uid).pw_name
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Uploader detection failed: {e}")
                return "Unknown"
        return "System"

    files = os.listdir(settings.DATA_RAW_DIR)
    results: List[Dict[str, Any]] = []
    for f in files:
        full_path = os.path.join(settings.DATA_RAW_DIR, f)
        try:
            stats = os.stat(full_path)
            results.append(
                {
                    "name": f,
                    "size": stats.st_size,
                    "uploaded_at": datetime.datetime.fromtimestamp(stats.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "uploader": get_owner(full_path),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to get stats for {f}: {e}")
    return results


def get_graph_data_controller() -> Dict[str, Any]:
    """从 Neo4j 抓取一小部分子图用于前端可视化。"""
    try:
        query = "MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 100"
        with graph_engine.graph_store._driver.session() as session:
            result = session.run(query)
            nodes: Dict[str, Dict[str, Any]] = {}
            edges: List[Dict[str, Any]] = []
            for record in result:
                n = record["n"]
                m = record["m"]
                r = record["r"]

                for node in (n, m):
                    node_id = str(node.id)
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "id": node_id,
                            "label": list(node.labels)[0] if node.labels else "Entity",
                            "name": node.get("name", node.get("id", "Unknown")),
                        }

                edges.append({"source": str(n.id), "target": str(m.id), "label": r.type})

            return {"nodes": list(nodes.values()), "links": edges}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to fetch graph data: {e}")
        return {"nodes": [], "links": []}


def get_ingestion_status_controller() -> Dict[str, Any]:
    try:
        if not os.path.exists(settings.DATA_RAW_DIR):
            return {"status": "idle", "progress": 0}

        # 基础统计：文件数与图节点数
        file_count = len(os.listdir(settings.DATA_RAW_DIR))
        with graph_engine.graph_store._driver.session() as session:
            count = session.run("MATCH (n) RETURN count(n) as c").single()["c"]

        # 默认回退到本地 INGESTION_STATE（主要用于无 Redis / 无 Celery 的场景）
        base = {
            "status": "processing" if INGESTION_STATE.get("is_processing") else "idle",
            "message": INGESTION_STATE.get("status", "idle"),
            "progress": INGESTION_STATE.get("progress", 0),
            "graph_done": INGESTION_STATE.get("graph_done", 0),
            "graph_total": INGESTION_STATE.get("graph_total", 0),
            "files_in_batch": INGESTION_STATE.get("files_in_batch", 0),
            "file_names": INGESTION_STATE.get("file_names", []),
        }

        # 若有 Redis，则优先使用 Celery worker 写入的全局状态
        try:
            r = redis.Redis.from_url(settings.REDIS_URL)
            raw = r.get("ingestion:status")
            if raw:
                data = json.loads(raw.decode("utf-8"))
                # 只覆盖已知字段，避免意外键污染
                for key in ("status", "message", "progress", "graph_done", "graph_total", "files_in_batch", "file_names"):
                    if key in data:
                        base[key] = data[key]
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to read ingestion status from Redis: %s", e)

        base["node_count"] = count
        base["file_count"] = file_count
        return base
    except Exception:  # noqa: BLE001
        return {"status": "unknown"}


def delete_document_controller(filename: str) -> Dict[str, Any]:
    """删除文档及其在两套存储中的数据。"""
    path = resolve_path_under(settings.DATA_RAW_DIR, filename)
    if path is None or not os.path.exists(path):
        raise FileNotFoundError("File not found")
    safe_name = os.path.basename(path)

    try:
        os.remove(path)
        nodes_deleted = graph_engine.delete_document(safe_name)
        vectors_deleted = vector_engine.delete_document(safe_name)
        logger.info(
            "Deleted file: %s. Removed %s graph nodes and %s vectors.",
            safe_name,
            nodes_deleted,
            vectors_deleted,
        )
        return {
            "status": "success",
            "message": f"Successfully deleted {safe_name}",
            "details": {
                "graph_nodes_removed": nodes_deleted,
                "vectors_removed": vectors_deleted,
            },
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to delete {path}: {e}")
        raise

