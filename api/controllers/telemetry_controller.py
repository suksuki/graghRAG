"""HTTP 无关：写入 insight 埋点。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.insight_event_log import append_insight_event, ensure_insight_events_table

_table_ready = False


def ingest_insight_event(
    *,
    event: str,
    ts: int,
    session_id: str,
    doc_id: str = "",
    insight_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    global _table_ready
    if not _table_ready:
        ensure_insight_events_table()
        _table_ready = True
    append_insight_event(
        event=event,
        ts=ts,
        session_id=session_id,
        doc_id=doc_id,
        insight_id=insight_id,
        payload=payload,
    )
