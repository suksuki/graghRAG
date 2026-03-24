"""
Graph + Vector 融合检索（最小可用）：向量召回 → 种子实体 → 图扩展 → 合并排序。

产品原则（DI 优先、防跑偏）：
- **主路径是向量**：先 `retrieve(query)`，再据 chunk / metadata 抽种子实体扩图。
- **图是增强**：不得改为「先全图遍历再补向量」；具体策略若调整须同步更新
  docs/DOCUMENT_INTELLIGENCE_POSITIONING.md。

不依赖 FastAPI；由 controller 注入 vector_engine 与 Neo4j driver。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from core.document_intelligence import DI_ENTITIES
from core.kg_edge_filter import min_kg_conf_query_param, normalize_kg_rel_properties_for_api

logger = logging.getLogger(__name__)

_LEX = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9]{2,}|\d{4,}")


def _parse_di_entities(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if x and str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        try:
            j = json.loads(s)
            if isinstance(j, list):
                return [str(x).strip() for x in j if x and str(x).strip()]
        except json.JSONDecodeError:
            return [s]
    return []


def _lexical_hints(text: str, max_terms: int = 8) -> List[str]:
    if not text or not str(text).strip():
        return []
    parts = _LEX.findall(str(text)[:1200])
    out: List[str] = []
    seen: Set[str] = set()
    for p in parts:
        if len(p) < 2 or p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= max_terms:
            break
    return out


def _node_retrieval_score(nws: Any) -> float:
    for attr in ("score", "similarity"):
        v = getattr(nws, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.5


def collect_seed_entities(nodes_with_scores: List[Any], query: str) -> List[str]:
    """从 chunk metadata 的 di_entities 等收集种子；不足时用查询与正文词块兜底。"""
    seen: Set[str] = set()
    ordered: List[str] = []

    def add(name: str) -> None:
        n = (name or "").strip()
        if len(n) < 2 or n in seen:
            return
        seen.add(n)
        ordered.append(n)

    for nws in nodes_with_scores or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        md = getattr(node, "metadata", None) or {}
        for key in (DI_ENTITIES, "di_entities", "entities"):
            if key in md:
                for x in _parse_di_entities(md.get(key)):
                    add(x)

    if not ordered:
        for x in _lexical_hints(query):
            add(x)

    for nws in nodes_with_scores or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        text = (getattr(node, "text", "") or "").strip()
        for x in _lexical_hints(text, max_terms=5):
            add(x)
        if len(ordered) >= 24:
            break

    return ordered[:25]


def _score_graph_rel_props(props: Dict[str, Any]) -> float:
    p = normalize_kg_rel_properties_for_api(props)
    base = float(p.get("kg_confidence") or 1.0)
    if p.get("kg_source") == "fallback":
        base *= 0.6
    return max(0.0, min(base, 1.0))


def _relevance_tokens(query: str) -> Set[str]:
    """查询侧词元：与种子抽取一致，便于头尾实体与问句对齐。"""
    s: Set[str] = set()
    for x in _lexical_hints(query, max_terms=24):
        s.add(x.lower())
    for w in re.findall(r"[A-Za-z]{3,}", query):
        s.add(w.lower())
    return {t for t in s if len(t) >= 2}


def _vector_evidence_anchors(nodes_with_scores: List[Any]) -> Tuple[Set[str], str]:
    """
    从本轮向量召回的 chunk 收集：metadata 实体名 + 正文拼接串。
    用于判断图边是否「贴着文档证据」。
    """
    meta_names: Set[str] = set()
    texts: List[str] = []
    for nws in nodes_with_scores or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        md = getattr(node, "metadata", None) or {}
        for key in (DI_ENTITIES, "di_entities", "entities"):
            if key in md:
                for x in _parse_di_entities(md.get(key)):
                    n = str(x).strip()
                    if len(n) >= 2:
                        meta_names.add(n)
                        meta_names.add(n.lower())
        t = (getattr(node, "text", "") or "").strip()
        if t:
            texts.append(t.lower())
    return meta_names, "\n".join(texts)


def _relation_anchored_to_vector_chunks(
    src: str, tgt: str, meta_names: Set[str], text_blob_lower: str
) -> bool:
    """主/宾是否与任一向量 chunk 的 metadata 实体或正文子串对齐。"""
    for raw in (src, tgt):
        name = (raw or "").strip()
        if len(name) < 2:
            continue
        nl = name.lower()
        if name in meta_names or nl in meta_names:
            return True
        if name in text_blob_lower or nl in text_blob_lower:
            return True
    return False


VECTOR_UNANCHORED_REL_PENALTY = 0.85


def _relation_relevance_bonus(
    src: str, rel_type: str, tgt: str, tokens: Set[str]
) -> float:
    """问句词元出现在主语/宾语/关系类型上时小幅加分，避免纯置信度排序与 query 脱节。"""
    if not tokens:
        return 0.0
    s_low = src.lower()
    t_low = tgt.lower()
    r_low = rel_type.lower()
    bonus = 0.0
    for tok in tokens:
        if tok in s_low or tok in t_low or tok in r_low:
            bonus += 0.1
    return min(bonus, 0.35)


def graph_expand(
    graph_driver: Any,
    entity_names: List[str],
    limit: int,
    min_kg_conf: float,
) -> List[Dict[str, Any]]:
    if not entity_names:
        return []
    cy = """
    MATCH (e:Entity)-[r]->(n)
    WHERE e.name IN $entities
      AND n.name IS NOT NULL
      AND ($min_kg_conf <= 0 OR coalesce(r.kg_confidence, 1.0) >= $min_kg_conf)
    RETURN e.name AS src, type(r) AS rel_type, n.name AS tgt, properties(r) AS rel_props
    LIMIT $limit
    """
    try:
        with graph_driver.session() as session:
            rows = list(
                session.run(
                    cy,
                    entities=entity_names,
                    min_kg_conf=float(min_kg_conf),
                    limit=int(limit),
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("hybrid graph_expand failed: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for rec in rows:
        src = rec.get("src")
        rel_type = rec.get("rel_type")
        tgt = rec.get("tgt")
        if not src or not tgt or not rel_type:
            continue
        rp = dict(rec.get("rel_props") or {})
        out.append(
            {
                "src": str(src),
                "rel_type": str(rel_type),
                "tgt": str(tgt),
                "rel_props": rp,
                "score": _score_graph_rel_props(rp),
            }
        )
    return out


def run_hybrid_search(
    *,
    vector_engine: Any,
    graph_driver: Any,
    query: str,
    top_k: int = 5,
    graph_expand_limit: int = 20,
    min_kg_conf: Optional[float] = None,
    include_fallback: bool = False,
    max_results: int = 20,
) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {
            "query": "",
            "results": [],
            "debug": {
                "vector_hits": 0,
                "graph_nodes": 0,
                "graph_edges": 0,
                "seed_entities": [],
            },
        }

    top_k = max(1, min(int(top_k or 5), 30))
    graph_expand_limit = max(1, min(int(graph_expand_limit or 20), 100))
    eff_min = 0.0 if include_fallback else float(
        min_kg_conf if min_kg_conf is not None else min_kg_conf_query_param()
    )

    try:
        retriever = vector_engine.get_retriever(similarity_top_k=top_k)
        nodes_with_scores = retriever.retrieve(q)
    except Exception as e:  # noqa: BLE001
        logger.warning("hybrid vector retrieve failed: %s", e)
        nodes_with_scores = []

    seeds = collect_seed_entities(nodes_with_scores, q)
    graph_rows = graph_expand(
        graph_driver, seeds, graph_expand_limit, eff_min
    )
    query_tokens = _relevance_tokens(q)
    anchor_meta, anchor_blob = _vector_evidence_anchors(nodes_with_scores)

    results: List[Dict[str, Any]] = []
    seen_chunk: Set[str] = set()
    for nws in nodes_with_scores or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        text = (getattr(node, "text", "") or "").strip()
        if not text:
            continue
        md = getattr(node, "metadata", None) or {}
        cid = str(
            getattr(node, "id_", None)
            or getattr(node, "node_id", None)
            or hash(text[:200])
        )
        if cid in seen_chunk:
            continue
        seen_chunk.add(cid)
        score = _node_retrieval_score(nws)
        results.append(
            {
                "type": "chunk",
                "id": cid,
                "score": round(score, 4),
                "content": text[:2000] + ("…" if len(text) > 2000 else ""),
                "source": "vector",
                "file_name": md.get("file_name") or md.get("source"),
            }
        )

    seen_rel: Set[Tuple[str, str, str]] = set()
    for row in graph_rows:
        key = (row["src"], row["rel_type"], row["tgt"])
        if key in seen_rel:
            continue
        seen_rel.add(key)
        base_sc = float(row["score"])
        rel_b = _relation_relevance_bonus(
            key[0], key[1], key[2], query_tokens
        )
        sc = min(1.0, base_sc + rel_b)
        anchored = _relation_anchored_to_vector_chunks(
            key[0], key[2], anchor_meta, anchor_blob
        )
        if not anchored:
            sc *= VECTOR_UNANCHORED_REL_PENALTY
        norm = normalize_kg_rel_properties_for_api(row["rel_props"])
        results.append(
            {
                "type": "relation",
                "id": f"{key[0]}::{key[1]}::{key[2]}",
                "triplet": [key[0], key[1], key[2]],
                "score": round(sc, 4),
                "source": "graph",
                "kg_source": norm.get("kg_source"),
                "kg_confidence": norm.get("kg_confidence"),
                "score_base": round(base_sc, 4),
                "score_relevance": round(rel_b, 4),
                "vector_anchored": anchored,
            }
        )

    results.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    results = results[: max(1, min(max_results, 50))]

    graph_node_names: Set[str] = set(seeds)
    for row in graph_rows:
        graph_node_names.add(row["src"])
        graph_node_names.add(row["tgt"])

    return {
        "query": q,
        "results": results,
        "debug": {
            "vector_hits": len(seen_chunk),
            "graph_nodes": len(graph_node_names),
            "graph_edges": len(graph_rows),
            "seed_entities": seeds[:15],
        },
    }
