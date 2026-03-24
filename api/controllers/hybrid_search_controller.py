"""融合检索：向量 + 图谱扩展。"""

from typing import Any, Dict

from api.deps import graph_engine, vector_engine
from api.schemas import HybridSearchRequest
from core.hybrid_search_service import run_hybrid_search


def hybrid_search_controller(body: HybridSearchRequest) -> Dict[str, Any]:
    driver = graph_engine.graph_store._driver  # type: ignore[attr-defined]
    return run_hybrid_search(
        vector_engine=vector_engine,
        graph_driver=driver,
        query=body.query,
        top_k=body.top_k,
        graph_expand_limit=body.graph_expand_k,
        min_kg_conf=body.min_kg_conf,
        include_fallback=body.include_fallback,
        max_results=20,
    )
