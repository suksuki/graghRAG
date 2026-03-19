import json
import os
import logging
import time

from celery import Celery
import redis

from core.ingestion import SMEIngestor
from core.query_cache import QueryCache
from configs.config import settings

logger = logging.getLogger(__name__)

# 在 worker 启动时打印关键配置，便于排查环境问题
logger.info("Redis URL: %s", settings.REDIS_URL)
logger.info("Ollama URL: %s", settings.OLLAMA_BASE_URL)

celery_app = Celery(
    "ingestion_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

redis_client = redis.Redis.from_url(settings.REDIS_URL)
try:
    _query_cache = QueryCache(url=settings.REDIS_URL)
except Exception:  # noqa: BLE001
    _query_cache = None

GLOBAL_STATUS_KEY = "ingestion:status"


def _set_status(filename: str, status: str) -> None:
    key = f"ingestion:{filename}"
    redis_client.set(key, status)


def _set_global_status(payload: dict) -> None:
    try:
        payload = {**payload, "updated_at": int(time.time())}
        redis_client.set(GLOBAL_STATUS_KEY, json.dumps(payload, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to write ingestion status to Redis: %s", e)


def _progress_callback(
    status_msg: str,
    percent: int,
    graph_done: int | None = None,
    graph_total: int | None = None,
    files_in_batch: int | None = None,
    file_names: list | None = None,
) -> None:
    payload = {
        "status": "processing",
        "message": status_msg,
        "progress": percent,
        "graph_done": graph_done or 0,
        "graph_total": graph_total or 0,
        "files_in_batch": files_in_batch or 0,
        "file_names": file_names or [],
    }
    _set_global_status(payload)


@celery_app.task(name="workers.ingest_document_task")
def ingest_document_task(file_path: str) -> None:
    """Celery 任务：调用现有 SMEIngestor 管道进行摄取。"""
    filename = os.path.basename(file_path)
    _set_status(filename, "processing")
    _set_global_status(
        {
            "status": "processing",
            "message": f"Queued file {filename} for ingestion...",
            "progress": 0,
            "graph_done": 0,
            "graph_total": 0,
            "files_in_batch": 1,
            "file_names": [filename],
        }
    )

    try:
        ingestor = SMEIngestor()
        # 复用现有增量摄取逻辑，不改动其实现。
        # 传入目录路径，利用已有的按文件名增量判断机制。
        directory = os.path.dirname(file_path) or settings.DATA_RAW_DIR
        ingestor.ingest_data(directory_path=directory, progress_callback=_progress_callback)
        if _query_cache is not None:
            try:
                new_version = _query_cache.bump_graph_version()
                logger.info("Graph version bumped to %s after ingestion", new_version)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to bump graph version: %s", e)
        _set_status(filename, "done")
        _set_global_status(
            {
                "status": "idle",
                "message": "Ingestion completed.",
                "progress": 100,
                "graph_done": 0,
                "graph_total": 0,
                "files_in_batch": 0,
                "file_names": [],
            }
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Celery ingestion for %s failed: %s", filename, e)
        _set_status(filename, "failed")
        _set_global_status(
            {
                "status": "failed",
                "message": f"Error: {e}",
                "progress": 0,
                "graph_done": 0,
                "graph_total": 0,
                "files_in_batch": 0,
                "file_names": [],
            }
        )
        raise


