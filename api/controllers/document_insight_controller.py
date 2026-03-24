"""单请求、片段锚定的文档洞察（与 corpus 洞察区分）。"""

from typing import Dict

from api.deps import graph_engine, vector_engine
from api.schemas import DocumentInsightRequest, DocRelationItem
from core.document_insight_service import run_document_insight
from core.lang_detect import resolve_query_language


def document_insight_controller(
    body: DocumentInsightRequest, ui_lang: str | None = None
) -> Dict:
    rq = resolve_query_language(body.query, ui_lang, default="zh")
    lang_final = str(rq.get("lang_final") or "zh")

    driver = graph_engine.graph_store._driver  # type: ignore[attr-defined]
    raw = run_document_insight(
        vector_engine=vector_engine,
        graph_driver=driver,
        llm=graph_engine.llm,
        query=body.query,
        top_k=body.top_k,
        doc_id=body.doc_id,
        include_graph_relations=body.include_graph_relations,
        lang=lang_final,
    )

    rels = [
        DocRelationItem(
            source=r["source"],
            relation=r["relation"],
            target=r["target"],
            kg_source=r.get("kg_source"),
            kg_confidence=r.get("kg_confidence"),
        )
        for r in raw.get("key_relations") or []
        if r.get("source") and r.get("relation") and r.get("target")
    ]
    dbg = dict(raw.get("debug") or {})
    dbg["lang_final"] = lang_final
    return {
        "summary": raw["summary"],
        "key_entities": raw["key_entities"],
        "key_relations": rels,
        "supporting_chunks": raw["supporting_chunks"],
        "insufficient_evidence": raw["insufficient_evidence"],
        "debug": dbg,
    }
