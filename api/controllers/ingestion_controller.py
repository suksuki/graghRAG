from typing import List, Dict, Any

import datetime
import json
import logging
import os
import time

try:
    import pwd
except ImportError:  # pragma: no cover - non-Unix platforms
    pwd = None

import redis

from configs.config import settings
from api.errors import AppError, ErrorCode, error_payload
from api.utils import (
    sanitize_filename,
    is_allowed_extension,
    resolve_path_under,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_UPLOAD,
    ALLOWED_EXTENSIONS,
)
from api.deps import graph_engine, vector_engine, ingestor
from core.kg_edge_filter import params_with_min_kg_conf
from workers.celery_worker import ingest_document_task, _set_status, celery_app

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


def _eligible_raw_file_count() -> int:
    """与知识库列表一致：可摄取扩展名的磁盘文件数。"""
    base = settings.DATA_RAW_DIR
    if not os.path.isdir(base):
        return 0
    n = 0
    for fn in os.listdir(base):
        path = os.path.join(base, fn)
        if os.path.isfile(path) and is_allowed_extension(fn):
            n += 1
    return n


def _vector_chunk_row_count() -> int:
    """当前向量表行数；-1 表示查询失败（健康判断时不据此判失败）。"""
    try:
        from sqlalchemy import text

        q = text(f"SELECT COUNT(*) AS c FROM {vector_engine.full_table_name}")
        with vector_engine.vector_store._engine.connect() as conn:
            row = conn.execute(q).fetchone()
            return int(row[0] if row and row[0] is not None else 0)
    except Exception as e:  # noqa: BLE001
        logger.debug("vector chunk count failed: %s", e)
        return -1


def _compute_ingestion_health(
    status: str,
    updated_at: int | float | None,
    eligible_files: int,
    vector_rows: int,
    *,
    vector_known: bool = True,
) -> str:
    """
    ok | processing | stalled | failed
    stalled：processing 且 Redis 心跳超过约 60s 未更新（尚未触发硬超时转 failed）。
    """
    now = int(time.time())
    if status in ("unknown", "failed"):
        return "failed"
    if status == "processing":
        age: int | None = None
        if isinstance(updated_at, (int, float)):
            age = now - int(updated_at)
        stale_hard = max(180, int(getattr(settings, "EXTRACTION_TIMEOUT", 120)) * 3)
        if age is not None and age > 60 and age <= stale_hard:
            return "stalled"
        return "processing"
    # idle
    if vector_known and eligible_files > 0 and vector_rows == 0:
        return "failed"
    return "ok"


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


def _run_ingestion_sync_fallback(saved_files: List[str]) -> None:
    """
    Celery / Redis 不可用时，在 API 进程内同步跑摄取（单机开发最常见）。
    与 workers/celery_worker.ingest_document_task 成功路径对齐：ingest_data + 可选 bump graph version。
    """
    INGESTION_STATE["is_processing"] = True
    progress_callback(
        "Inline ingestion (no Celery worker)…",
        0,
        graph_done=0,
        graph_total=0,
        files_in_batch=len(saved_files),
        file_names=list(saved_files),
    )
    try:
        ingestor.ingest_data(directory_path=settings.DATA_RAW_DIR, progress_callback=progress_callback)
        try:
            from core.query_cache import QueryCache

            _qc = QueryCache(url=settings.REDIS_URL)
            _qc.bump_graph_version()
        except Exception as e:  # noqa: BLE001
            logger.debug("graph version bump skipped after inline ingest: %s", e)
        for fname in saved_files:
            try:
                _set_status(fname, "done")
            except Exception as e:  # noqa: BLE001
                logger.debug("Redis file status (done) skipped for %s: %s", fname, e)
        progress_callback("Ingestion completed.", 100, graph_done=0, graph_total=0, files_in_batch=0, file_names=[])
    except Exception as e:  # noqa: BLE001
        logger.exception("Inline ingestion failed: %s", e)
        for fname in saved_files:
            try:
                _set_status(fname, "failed")
            except Exception as e2:  # noqa: BLE001
                logger.debug("Redis file status (failed) skipped for %s: %s", fname, e2)
        progress_callback(f"Error: {e}", 0, files_in_batch=0, file_names=[])
        raise
    finally:
        INGESTION_STATE["is_processing"] = False


def handle_upload(files) -> Dict[str, Any]:
    """处理文件上传逻辑，不抛 HTTPException。

    可能抛 ValueError 表示 4xx 场景，由路由转换成 HTTPException。
    """
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise AppError(
            code=ErrorCode.UNKNOWN_ERROR,
            message=f"文件数量超过限制（最多 {MAX_FILES_PER_UPLOAD} 个）",
            detail=f"当前上传数量：{len(files)}",
            suggestion="请分批上传文件",
            status_code=400,
        )

    if not os.path.exists(settings.DATA_RAW_DIR):
        os.makedirs(settings.DATA_RAW_DIR)

    saved_files: List[str] = []
    for file in files:
        safe_name = sanitize_filename(file.filename)
        if not safe_name:
            raise AppError(
                code=ErrorCode.PARSE_ERROR,
                message="文件名不合法",
                detail=f"原始文件名：{file.filename!r}",
                suggestion="请使用常规文件名（字母/数字/中划线）后重试",
                status_code=400,
            )
        if not is_allowed_extension(safe_name):
            allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise AppError(
                code=ErrorCode.UNSUPPORTED_FILE_TYPE,
                message="不支持该文件类型",
                detail=f"文件：{file.filename}，支持类型：{allowed}",
                suggestion="请转换为支持的类型后重试",
                status_code=400,
            )

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
                    raise AppError(
                        code=ErrorCode.FILE_TOO_LARGE,
                        message=f"文件超过大小限制（最大 {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB）",
                        detail=f"文件：{safe_name}，当前大小约：{size // (1024 * 1024)}MB",
                        suggestion="请压缩文件或分批上传",
                        status_code=400,
                    )
                buffer.write(chunk)
        saved_files.append(safe_name)

    # 优先 Celery；若 broker/worker 不可用则在本进程同步摄取，避免「只落盘、不入库」。
    jobs: List[Dict[str, str]] = []
    for fname in saved_files:
        try:
            _set_status(fname, "queued")
            file_path = os.path.join(settings.DATA_RAW_DIR, fname)
            task = ingest_document_task.delay(file_path)
            jobs.append({"file": fname, "job_id": task.id, "status": "queued"})
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to enqueue Celery task for %s: %s", fname, e)
            jobs.clear()
            break

    use_inline = len(jobs) != len(saved_files)
    if use_inline and saved_files:
        logger.info(
            "Celery enqueue unavailable or incomplete; running synchronous ingestion for %d file(s)",
            len(saved_files),
        )
        try:
            _run_ingestion_sync_fallback(saved_files)
        except Exception as e:  # noqa: BLE001
            raise AppError(
                code=ErrorCode.UNKNOWN_ERROR,
                message="文件已保存，但摄取失败",
                detail=str(e),
                suggestion="请检查 Ollama / PGVector / Neo4j 是否可用，并查看服务端日志",
                status_code=500,
            ) from e
        if len(saved_files) == 1:
            return {
                "status": "completed",
                "filename": saved_files[0],
                "files": saved_files,
                "jobs": [],
                "ingestion_mode": "inline",
            }
        return {
            "status": "completed",
            "filename": saved_files,
            "files": saved_files,
            "jobs": [],
            "ingestion_mode": "inline",
        }

    if len(saved_files) == 1:
        return {"status": "queued", "filename": saved_files[0], "files": saved_files, "jobs": jobs}
    return {"status": "queued", "filename": saved_files, "files": saved_files, "jobs": jobs}


def get_ingest_job_status_controller(job_id: str) -> Dict[str, Any]:
    """查询单个 ingestion job 状态。"""
    if not job_id or not job_id.strip():
        return {
            "status": "failed",
            "error": error_payload(
                ErrorCode.UNKNOWN_ERROR,
                "任务标识缺失",
                "job_id is required",
                "请刷新页面后重试上传",
            )["error"],
        }
    res = celery_app.AsyncResult(job_id.strip())
    state = (res.state or "PENDING").upper()
    if state in ("PENDING", "RECEIVED", "STARTED", "RETRY"):
        return {"status": "processing", "progress": 10 if state == "PENDING" else 50, "job_id": job_id}
    if state == "SUCCESS":
        return {"status": "done", "progress": 100, "job_id": job_id}
    # FAILURE / REVOKED / other unexpected states
    err = str(res.result) if res.result is not None else "unknown error"
    msg = err.lower()
    if "timeout" in msg or "timed out" in msg:
        payload = error_payload(
            ErrorCode.TIMEOUT,
            "处理超时",
            err,
            "请重试上传，或减少单次上传文件大小",
        )["error"]
    elif (
        "unsupported file type" in msg
        or "no extractable text" in msg
        or "legacy .doc parsing requires" in msg
        or "parse" in msg
    ):
        payload = error_payload(
            ErrorCode.PARSE_ERROR,
            "文档解析失败",
            err,
            "请检查文件内容是否完整，或将文档转换为 DOCX / TXT 后重试",
        )["error"]
    elif "graph" in msg:
        payload = error_payload(
            ErrorCode.GRAPH_BUILD_FAILED,
            "图索引构建失败",
            err,
            "请检查文档内容格式后重试",
        )["error"]
    elif "vector" in msg:
        payload = error_payload(
            ErrorCode.VECTOR_INDEX_FAILED,
            "向量索引构建失败",
            err,
            "请重试上传，若持续失败请联系管理员",
        )["error"]
    else:
        payload = error_payload(
            ErrorCode.UNKNOWN_ERROR,
            "文档处理失败",
            err,
            "请重试上传并查看详细错误",
        )["error"]
    return {"status": "failed", "progress": 0, "job_id": job_id, "error": payload}


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
        query = """
        MATCH (n)-[r]->(m)
        WHERE ($min_kg_conf <= 0 OR coalesce(r.kg_confidence, 1.0) >= $min_kg_conf)
        RETURN n, r, m LIMIT 100
        """
        with graph_engine.graph_store._driver.session() as session:
            result = session.run(query, **params_with_min_kg_conf({}))
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
        eligible_files = _eligible_raw_file_count()
        vector_rows = _vector_chunk_row_count()

        if not os.path.exists(settings.DATA_RAW_DIR):
            vk = vector_rows >= 0
            vr = vector_rows if vk else 0
            h = _compute_ingestion_health("idle", None, eligible_files, vr, vector_known=vk)
            return {
                "status": "idle",
                "progress": 0,
                "health": h,
                "eligible_file_count": eligible_files,
                "vector_chunk_count": vector_rows if vk else None,
                "file_count": 0,
                "node_count": 0,
                "message": "",
                "graph_done": 0,
                "graph_total": 0,
                "files_in_batch": 0,
                "file_names": [],
            }

        # 基础统计：目录项数量与图节点数
        file_count = len(os.listdir(settings.DATA_RAW_DIR))
        with graph_engine.graph_store._driver.session() as session:
            count = session.run("MATCH (n) RETURN count(n) as c").single()["c"]

        # 默认回退到本地 INGESTION_STATE（主要用于无 Redis / 无 Celery 的场景）
        base: Dict[str, Any] = {
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
                for key in ("status", "message", "progress", "graph_done", "graph_total", "files_in_batch", "file_names", "updated_at"):
                    if key in data:
                        base[key] = data[key]
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to read ingestion status from Redis: %s", e)

        # 防卡死保护：长时间 processing 但无更新，转为 failed，避免前端一直显示处理中
        updated_at = base.get("updated_at")
        if base.get("status") == "processing" and isinstance(updated_at, (int, float)):
            stale_seconds = max(180, int(getattr(settings, "EXTRACTION_TIMEOUT", 120)) * 3)
            if int(time.time()) - int(updated_at) > stale_seconds:
                base["status"] = "failed"
                base["message"] = "Ingestion seems stalled. Please retry or check worker logs."

        base["node_count"] = count
        base["file_count"] = file_count
        base["eligible_file_count"] = eligible_files
        vk = vector_rows >= 0
        base["vector_chunk_count"] = vector_rows if vk else None
        vr = vector_rows if vk else 0
        base["health"] = _compute_ingestion_health(
            str(base.get("status") or "idle"),
            updated_at if isinstance(updated_at, (int, float)) else None,
            eligible_files,
            vr,
            vector_known=vk,
        )
        return base
    except Exception:  # noqa: BLE001
        return {"status": "unknown", "health": "failed"}


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

