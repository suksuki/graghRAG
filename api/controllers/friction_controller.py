"""认知摩擦 → v3 候选：聚合埋点并评估（不写业务 UI）。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from core.friction_v3 import append_friction_candidate_jsonl, evaluate_friction_v0
from core.insight_event_log import fetch_insight_events_for_session


def eval_friction_for_session(
    *,
    session_id: str,
    doc_id: Optional[str] = None,
    log_candidate: bool = False,
) -> Dict[str, Any]:
    events = fetch_insight_events_for_session(session_id, doc_id or None)
    result = evaluate_friction_v0(events)
    result["session_id"] = session_id
    result["doc_id"] = doc_id or ""
    if log_candidate and result.get("friction_type"):
        append_friction_candidate_jsonl(
            {
                "eval_ts": int(time.time() * 1000),
                **result,
            }
        )
    return result
