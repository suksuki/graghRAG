"""POST /log — Insight 认知摩擦埋点（轻量，不阻塞）。"""

from __future__ import annotations

from fastapi import APIRouter, Body

from api.controllers.friction_controller import eval_friction_for_session
from api.controllers.telemetry_controller import ingest_insight_event
from api.schemas import FrictionEvalRequest, FrictionEvalResponse, InsightEventIn

router = APIRouter(tags=["telemetry"])


@router.post("/log", status_code=204)
def post_insight_log(
    body: InsightEventIn = Body(...),
):
    """接收前端 sendBeacon / fetch 的 JSON；过大请求体由 Starlette 限制。"""
    ingest_insight_event(
        event=body.event,
        ts=body.ts,
        session_id=body.session_id,
        doc_id=body.doc_id or "",
        insight_id=body.insight_id,
        payload=body.payload,
    )
    return None


@router.post("/telemetry/friction-eval", response_model=FrictionEvalResponse)
def post_friction_eval(body: FrictionEvalRequest = Body(...)):
    """
    聚合当前 session 埋点，输出摩擦类型与建议 v3 形态（v0 规则）。
    可选 log_candidate 写入 data/logs/friction_v3_candidates.jsonl。
    """
    data = eval_friction_for_session(
        session_id=body.session_id,
        doc_id=body.doc_id,
        log_candidate=body.log_candidate,
    )
    return FrictionEvalResponse(**data)
