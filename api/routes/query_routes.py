import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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


def _stream_ndjson(query: str, mode: str):
    """Yield NDJSON lines (one JSON object per line) for streaming query."""
    import nest_asyncio
    nest_asyncio.apply()
    from pipelines.query_pipeline import QueryPipeline
    pipeline = QueryPipeline()
    try:
        for event in pipeline.run_stream(query, mode=mode):
            line = json.dumps(event, ensure_ascii=False) + "\n"
            yield line.encode("utf-8")
    except Exception as e:  # noqa: BLE001
        yield json.dumps({"type": "error", "detail": str(e)}, ensure_ascii=False).encode("utf-8") + b"\n"


@router.post("/query/stream")
def query_stream_route(request: QueryRequest) -> StreamingResponse:
    """流式查询：返回 NDJSON 流，每行一个 JSON。事件 type: chunk | done | error。"""
    return StreamingResponse(
        _stream_ndjson(request.query.strip(), request.mode),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

