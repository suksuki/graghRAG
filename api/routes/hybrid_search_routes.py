"""POST /api/v1/hybrid-search — Graph + Vector 融合检索。"""

from fastapi import APIRouter

from api.schemas import HybridSearchRequest, HybridSearchResponse
from configs.config import settings

router = APIRouter(prefix=settings.API_V1_STR, tags=["hybrid-search"])


def _get_hybrid_search_controller():
    from api.controllers.hybrid_search_controller import hybrid_search_controller

    return hybrid_search_controller


@router.post("/hybrid-search", response_model=HybridSearchResponse)
def hybrid_search_route(body: HybridSearchRequest) -> HybridSearchResponse:
    data = _get_hybrid_search_controller()(body)
    return HybridSearchResponse(**data)
