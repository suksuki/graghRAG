from fastapi import APIRouter, HTTPException

from api.schemas import QueryRequest, QueryResponse
from api.controllers.query_controller import query_knowledge

router = APIRouter(tags=["Retrieval"])


@router.post("/query", response_model=QueryResponse)
def query_route(request: QueryRequest) -> QueryResponse:
    """HTTP 层：只负责解析请求与错误转成 HTTPException。"""
    try:
        data = query_knowledge(request)
        return QueryResponse(**data)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))

