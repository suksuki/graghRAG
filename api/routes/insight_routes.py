"""跨文档知识库洞察（Corpus Insight）。"""

from fastapi import APIRouter, Request

from api.controllers.corpus_insight_controller import corpus_insight_controller
from api.schemas import CorpusInsightRequest, CorpusInsightResponse

router = APIRouter(tags=["insights"])


@router.post("/insights/corpus", response_model=CorpusInsightResponse)
def corpus_insight_route(body: CorpusInsightRequest, request: Request) -> CorpusInsightResponse:
    lang = (request.headers.get("x-lang") or "zh").strip().lower()
    data = corpus_insight_controller(top_k_docs=body.top_k_docs, lang=lang)
    return CorpusInsightResponse(**data)
