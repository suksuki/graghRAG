import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas import QueryRequest, QueryResponse
from api.controllers.query_controller import query_knowledge
from api.errors import ErrorCode, error_payload

router = APIRouter(tags=["Retrieval"])


@router.post("/query", response_model=QueryResponse)
def query_route(request: QueryRequest, http_request: Request) -> QueryResponse:
    """HTTP 层：只负责解析请求与错误转成 HTTPException。"""
    try:
        lang = (http_request.headers.get("x-lang") or "zh").strip().lower()
        data = query_knowledge(request, lang=lang)
        return QueryResponse(**data)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


def _stream_ndjson(query: str, mode: str, lang: str = "zh"):
    """Yield NDJSON lines (one JSON object per line) for streaming query."""
    import nest_asyncio
    nest_asyncio.apply()
    from pipelines.query_pipeline import QueryPipeline
    pipeline = QueryPipeline(lang=lang)
    try:
        for event in pipeline.run_stream(query, mode=mode):
            line = json.dumps(event, ensure_ascii=False) + "\n"
            yield line.encode("utf-8")
    except Exception as e:  # noqa: BLE001
        yield json.dumps(
            {
                "type": "error",
                "detail": str(e),
                **error_payload(
                    ErrorCode.UNKNOWN_ERROR,
                    "查询失败",
                    str(e),
                    "请稍后重试",
                ),
            },
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"


@router.post("/query/stream")
def query_stream_route(request: QueryRequest, http_request: Request) -> StreamingResponse:
    """流式查询：返回 NDJSON 流，每行一个 JSON。事件 type: chunk | done | error。"""
    lang = (http_request.headers.get("x-lang") or "zh").strip().lower()

    def _stream_ndjson_enriched(query: str, mode: str, lang: str):
        import nest_asyncio
        nest_asyncio.apply()
        from pipelines.query_pipeline import QueryPipeline

        pipeline = QueryPipeline(lang=lang)

        final_answer_parts = []
        last_done_event = None

        try:
            for event in pipeline.run_stream(query, mode=mode):
                if isinstance(event, dict):
                    if event.get("type") == "chunk" and isinstance(event.get("text"), str):
                        final_answer_parts.append(event.get("text") or "")
                    elif event.get("type") == "done":
                        last_done_event = event
                line = json.dumps(event, ensure_ascii=False) + "\n"
                yield line.encode("utf-8")

            if last_done_event is None:
                final_answer = "".join(final_answer_parts).strip()
                last_done_event = {"type": "done", "answer": final_answer, "sources": []}

            final_answer = last_done_event.get("answer")
            if not (isinstance(final_answer, str) and final_answer.strip()):
                final_answer = "".join(final_answer_parts).strip()

            sources = last_done_event.get("sources")
            if not isinstance(sources, list):
                sources = []

            graph = last_done_event.get("graph")
            if not isinstance(graph, dict):
                graph = {}
            relations = graph.get("relations")
            if not isinstance(relations, list):
                relations = []
            graph_payload = {
                "used": bool(graph.get("used")) if "used" in graph else (len(relations) > 0),
                "relations": relations,
                "count": int(graph.get("count")) if isinstance(graph.get("count"), int) else len(relations),
            }

            debug_payload = last_done_event.get("debug") if isinstance(last_done_event.get("debug"), dict) else {}

            enriched_done = {
                "type": "done",
                "answer": final_answer,
                "sources": sources,
                "graph": graph_payload,
                "debug": debug_payload,
            }
            for k in ("pipeline_latency_ms", "first_token_ms", "total_ms"):
                if k in last_done_event:
                    enriched_done[k] = last_done_event[k]

            yield (json.dumps(enriched_done, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as e:  # noqa: BLE001
            yield json.dumps(
                {
                    "type": "error",
                    "detail": str(e),
                    **error_payload(
                        ErrorCode.UNKNOWN_ERROR,
                        "流式查询失败",
                        str(e),
                        "请稍后重试",
                    ),
                },
                ensure_ascii=False,
            ).encode("utf-8") + b"\n"

    return StreamingResponse(
        _stream_ndjson_enriched(request.query.strip(), request.mode, lang),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

