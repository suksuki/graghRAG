"""
单请求文档洞察（DI-first）：向量召回 → supporting_chunks → 实体/图关系辅助 → LLM 仅基于片段的 grounded summary。

不得编造片段外事实；证据不足时在 summary 中明确说明。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from core.document_intelligence import DI_ENTITIES
from core.hybrid_search_service import _parse_di_entities
from core.kg_edge_filter import (
    min_kg_conf_query_param,
    normalize_kg_rel_properties_for_api,
    params_with_min_kg_conf,
)

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 14_000
_LANG_NAME = {
    "zh": "Chinese (Simplified)",
    "en": "English",
    "ko": "Korean",
}


def _node_score(nws: Any) -> float:
    for attr in ("score", "similarity"):
        v = getattr(nws, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _collect_key_entities(nodes_with_scores: List[Any]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for nws in nodes_with_scores or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        md = getattr(node, "metadata", None) or {}
        for key in (DI_ENTITIES, "di_entities", "entities"):
            if key not in md:
                continue
            for x in _parse_di_entities(md.get(key)):
                n = str(x).strip()
                if len(n) < 2 or n in seen:
                    continue
                seen.add(n)
                out.append(n)
    return out[:40]


def _graph_relations_for_entities(
    graph_driver: Any, names: List[str], limit: int = 28
) -> List[Dict[str, Any]]:
    if not names:
        return []
    cy = """
    MATCH (e:Entity)-[r]->(n)
    WHERE e.name IN $names AND n.name IS NOT NULL
      AND type(r) <> 'ALIAS_OF'
      AND ($min_kg_conf <= 0 OR coalesce(r.kg_confidence, 1.0) >= $min_kg_conf)
    RETURN e.name AS source, type(r) AS relation, n.name AS target, properties(r) AS rel_props
    LIMIT $limit
    """
    try:
        with graph_driver.session() as session:
            rows = list(
                session.run(
                    cy,
                    **params_with_min_kg_conf(
                        {"names": names[:20], "limit": int(limit)}
                    ),
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("document insight graph relations failed: %s", e)
        return []
    seen: Set[Tuple[str, str, str]] = set()
    out: List[Dict[str, Any]] = []
    for rec in rows:
        s, rel, t = rec.get("source"), rec.get("relation"), rec.get("target")
        if not (s and rel and t):
            continue
        key = (str(s), str(rel), str(t))
        if key in seen:
            continue
        seen.add(key)
        norm = normalize_kg_rel_properties_for_api(dict(rec.get("rel_props") or {}))
        out.append(
            {
                "source": key[0],
                "relation": key[1],
                "target": key[2],
                "kg_source": norm.get("kg_source"),
                "kg_confidence": norm.get("kg_confidence"),
            }
        )
    return out


def _build_grounded_summary_prompt(
    query: str, sources_text: str, lang: str
) -> str:
    lang_name = _LANG_NAME.get(lang, _LANG_NAME["zh"])
    return (
        "You are a document intelligence assistant.\n\n"
        "STRICT RULES:\n"
        "1. Use ONLY information explicitly stated in SOURCES below.\n"
        "2. Do NOT invent entities, numbers, or relationships not in SOURCES.\n"
        "3. If SOURCES are empty or do not answer the question, say clearly that "
        "the retrieved excerpts are insufficient (one or two sentences).\n"
        "4. Write 3–6 sentences when evidence exists.\n"
        f"5. Write entirely in {lang_name}.\n"
        "6. SOURCES are numbered [1], [2], ... After each sentence or factual claim, "
        "append bracket citations using ONLY those numbers, e.g. ...[1] or ...[1][3]. "
        "Every substantive claim should have at least one citation.\n"
        "7. Do NOT cite a number that does not appear in SOURCES.\n\n"
        f"User question / focus:\n{query.strip()}\n\n"
        "SOURCES (retrieved chunks only; numbers match supporting_chunks.ref_index):\n"
        "-----\n"
        f"{sources_text}\n"
        "-----\n\n"
        "Summary:"
    )


def run_document_insight(
    *,
    vector_engine: Any,
    graph_driver: Any,
    llm: Any,
    query: str,
    top_k: int = 5,
    doc_id: Optional[str] = None,
    include_graph_relations: bool = True,
    lang: str = "zh",
) -> Dict[str, Any]:
    q = (query or "").strip()
    top_k = max(1, min(int(top_k or 5), 20))
    doc_filter = (doc_id or "").strip() or None

    nodes_with_scores: List[Any] = []
    retrieve_k = min(30, top_k * 3 if doc_filter else top_k)
    retrieve_k = max(retrieve_k, top_k)
    try:
        retriever = vector_engine.get_retriever(similarity_top_k=retrieve_k)
        nodes_with_scores = retriever.retrieve(q)
    except Exception as e:  # noqa: BLE001
        logger.warning("document insight retrieve failed: %s", e)
    if doc_filter:
        filtered: List[Any] = []
        for nws in nodes_with_scores or []:
            node = getattr(nws, "node", None)
            if node is None:
                continue
            md = getattr(node, "metadata", None) or {}
            fn = str(md.get("file_name") or md.get("source") or "").strip()
            if fn == doc_filter:
                filtered.append(nws)
        nodes_with_scores = filtered[:top_k]
    else:
        nodes_with_scores = (nodes_with_scores or [])[:top_k]

    supporting: List[Dict[str, Any]] = []
    source_blocks: List[str] = []
    char_budget = 0
    ref_idx = 0
    for nws in nodes_with_scores:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        text = (getattr(node, "text", "") or "").strip()
        if not text:
            continue
        md = getattr(node, "metadata", None) or {}
        fn = md.get("file_name") or md.get("source") or ""
        cid = str(
            getattr(node, "id_", None)
            or getattr(node, "node_id", None)
            or hash(text[:200])
        )
        sc = _node_score(nws)
        snip = text.replace("\n", " ")
        if len(snip) > 1200:
            snip = snip[:1200].rstrip() + "…"
        next_idx = ref_idx + 1
        block = f"[{next_idx}] file: {fn or 'unknown'}\n{snip}"
        if char_budget + len(block) > MAX_SOURCE_CHARS:
            break
        ref_idx = next_idx
        char_budget += len(block)
        source_blocks.append(block)
        supporting.append(
            {
                "id": cid,
                "ref_index": ref_idx,
                "file_name": fn if fn else None,
                "snippet": snip,
                "score": round(sc, 4),
            }
        )

    sources_joined = "\n\n".join(source_blocks)
    key_entities = _collect_key_entities(nodes_with_scores)

    key_relations: List[Dict[str, Any]] = []
    if include_graph_relations and key_entities:
        key_relations = _graph_relations_for_entities(
            graph_driver, key_entities[:15], limit=28
        )

    insufficient = len(supporting) == 0
    summary = ""
    if insufficient:
        if lang == "en":
            summary = (
                "No relevant document excerpts were retrieved; cannot provide a grounded answer."
            )
        elif lang == "ko":
            summary = "관련 문서 조각을 찾지 못해 근거 있는 답변을 드리기 어렵습니다."
        else:
            summary = "未能检索到相关文档片段，无法基于语料给出有据回答。"
    else:
        prompt = _build_grounded_summary_prompt(q, sources_joined, lang)
        try:
            summary = str(llm.complete(prompt)).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("document insight LLM failed: %s", e)
            summary = (
                "（摘要生成暂时失败，请稍后重试。）"
                if lang != "en"
                else "(Summary generation failed; please retry.)"
            )

    if not summary:
        insufficient = True
        summary = (
            "根据当前检索到的片段无法生成摘要。"
            if lang != "en"
            else "Could not generate a summary from the retrieved excerpts."
        )

    return {
        "summary": summary,
        "key_entities": key_entities[:30],
        "key_relations": key_relations,
        "supporting_chunks": supporting,
        "insufficient_evidence": insufficient,
        "debug": {
            "chunk_count": len(supporting),
            "doc_filter": doc_filter,
            "graph_relation_count": len(key_relations),
            "min_kg_conf_used": min_kg_conf_query_param(),
        },
    }
