"""POST /api/v1/insights/document — 片段锚定的单请求洞察（DI-first）。"""

from fastapi import APIRouter, Request

from api.controllers.document_insight_controller import document_insight_controller
from api.schemas import DocumentInsightRequest, DocumentInsightResponse
from configs.config import settings

router = APIRouter(prefix=settings.API_V1_STR, tags=["insights"])


@router.post("/insights/document", response_model=DocumentInsightResponse)
def document_insight_route(
    body: DocumentInsightRequest, request: Request
) -> DocumentInsightResponse:
    lang = (request.headers.get("x-lang") or "zh").strip().lower()
    data = document_insight_controller(body, ui_lang=lang)
    return DocumentInsightResponse(**data)
