"""
Insight 认知摩擦埋点：写入 PostgreSQL insight_events，失败则追加 JSONL（不阻塞主业务）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from configs.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

_JSONL_PATH = PROJECT_ROOT / "data" / "logs" / "insight_events.jsonl"


def _ensure_jsonl_dir() -> None:
    _JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)


def ensure_insight_events_table() -> None:
    """CREATE TABLE IF NOT EXISTS（与向量库共用 Postgres 连接参数）。"""
    try:
        import psycopg2
    except ImportError:
        return
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS insight_events (
                id BIGSERIAL PRIMARY KEY,
                event TEXT NOT NULL,
                ts BIGINT NOT NULL,
                session_id TEXT NOT NULL,
                doc_id TEXT NOT NULL DEFAULT '',
                insight_id TEXT,
                payload JSONB
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_insight_events_ts ON insight_events(ts);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_insight_events_event ON insight_events(event);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_insight_events_session ON insight_events(session_id);"
        )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("insight_events table ensure failed (will use jsonl fallback): %s", e)


def append_insight_event(
    *,
    event: str,
    ts: int,
    session_id: str,
    doc_id: str = "",
    insight_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    row = {
        "event": event,
        "ts": ts,
        "session_id": session_id,
        "doc_id": doc_id or "",
        "insight_id": insight_id,
        "payload": payload or {},
    }
    try:
        import psycopg2
        from psycopg2.extras import Json

        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO insight_events (event, ts, session_id, doc_id, insight_id, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event,
                int(ts),
                session_id,
                doc_id or "",
                insight_id,
                Json(payload or {}),
            ),
        )
        conn.commit()
        conn.close()
        return
    except Exception as e:  # noqa: BLE001
        logger.debug("insight_events PG insert failed, jsonl fallback: %s", e)

    try:
        _ensure_jsonl_dir()
        with open(_JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e2:  # noqa: BLE001
        logger.warning("insight_events jsonl write failed: %s", e2)


def fetch_insight_events_for_session(
    session_id: str,
    doc_id: Optional[str] = None,
    limit: int = 8000,
) -> List[Dict[str, Any]]:
    """
    按时间升序返回事件，供摩擦评估使用。
    PG 不可用时扫描 insight_events.jsonl 尾部（开发兜底）。
    """
    out: List[Dict[str, Any]] = []
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        if doc_id:
            cur.execute(
                """
                SELECT event, ts, doc_id, payload
                FROM insight_events
                WHERE session_id = %s AND doc_id = %s
                ORDER BY ts ASC
                LIMIT %s
                """,
                (session_id, doc_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT event, ts, doc_id, payload
                FROM insight_events
                WHERE session_id = %s
                ORDER BY ts ASC
                LIMIT %s
                """,
                (session_id, limit),
            )
        for row in cur.fetchall():
            ev, ts, did, payload = row
            pl = payload if isinstance(payload, dict) else {}
            out.append(
                {
                    "event": ev,
                    "ts": int(ts) if ts is not None else 0,
                    "doc_id": did or "",
                    "payload": pl,
                }
            )
        conn.close()
        return out
    except Exception as e:  # noqa: BLE001
        logger.debug("insight_events PG fetch failed, jsonl scan: %s", e)

    return _fetch_insight_events_from_jsonl(session_id, doc_id, limit)


def _fetch_insight_events_from_jsonl(
    session_id: str,
    doc_id: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    if not _JSONL_PATH.is_file():
        return []
    matched: List[Dict[str, Any]] = []
    try:
        lines = _JSONL_PATH.read_text(encoding="utf-8").splitlines()
        # 尾部优先（近期会话）
        for line in lines[-max(limit * 3, 5000) :]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("session_id") != session_id:
                continue
            if doc_id and (row.get("doc_id") or "") != doc_id:
                continue
            pl = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            matched.append(
                {
                    "event": row.get("event") or "",
                    "ts": int(row["ts"]) if row.get("ts") is not None else 0,
                    "doc_id": row.get("doc_id") or "",
                    "payload": pl,
                }
            )
        matched.sort(key=lambda x: x.get("ts") or 0)
        return matched[-limit:]
    except Exception as e:  # noqa: BLE001
        logger.warning("insight_events jsonl read failed: %s", e)
        return []
