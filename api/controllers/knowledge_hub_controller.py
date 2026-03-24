"""
知识产品化 P0：文档中心、向量搜索、实体档案。
数据来自 DATA_RAW_DIR 文件列表 + Neo4j + PGVector metadata，不新增业务表。
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List

import psycopg2

from api.controllers.graph_controller import (
    _resolve_canonical_entity,
    _run_cypher,
)
from api.deps import graph_engine, vector_engine
from api.utils import is_allowed_extension
from configs.config import settings
from core.kg_edge_filter import params_with_min_kg_conf
from core.document_intelligence import (
    DI_DOC_TYPE,
    DI_ENTITIES,
    DI_KEYWORDS,
    DI_KEY_POINTS,
    DI_SUMMARY,
    DI_TOPICS,
)
from core.lang_detect import normalize_lang
from core.lang_guard import enforce_language
from core.query_cache import GRAPH_VERSION, QueryCache

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 480
_SEARCH_SNIPPET = 400
_INSIGHT_TTL = 1800

try:
    _insight_cache: QueryCache | None = QueryCache()
except Exception:  # noqa: BLE001
    _insight_cache = None


def _insight_cache_key(parts: List[str]) -> str:
    return "hub:insight:" + "|".join(parts)


def _insight_cache_get(parts: List[str]) -> str | None:
    if _insight_cache is None:
        return None
    key = _insight_cache_key(parts)
    try:
        val = _insight_cache.get(key)
        if isinstance(val, dict):
            s = val.get("insight")
            return s if isinstance(s, str) else None
    except Exception:  # noqa: BLE001
        pass
    return None


def _insight_cache_set(parts: List[str], insight: str) -> None:
    if _insight_cache is None or not insight:
        return
    key = _insight_cache_key(parts)
    try:
        _insight_cache.set(key, {"insight": insight}, ttl=_INSIGHT_TTL)
    except Exception:  # noqa: BLE001
        pass


def _rel_upper(rel: str | None) -> str:
    return (rel or "").upper()


def _build_graph_summary_from_triples(triples: List[Dict[str, str]], lang: str) -> str | None:
    """
    与 QueryPipeline._build_graph_summary 同构的模板摘要（不 import QueryPipeline）。
    文档/实体场景放宽：不要求 min_relations，仅需 PROVIDES 主语 + 产品或行业之一。
    """
    if not triples:
        return None
    companies = [
        t.get("source")
        for t in triples
        if _rel_upper(t.get("relation")) == "PROVIDES" and t.get("source")
    ]
    company = companies[0] if companies else None
    products = [
        t.get("target")
        for t in triples
        if _rel_upper(t.get("relation")) == "PROVIDES" and t.get("target")
    ]
    domains = [
        t.get("target")
        for t in triples
        if _rel_upper(t.get("relation")) == "APPLIES_TO" and t.get("target")
    ]
    products_uniq = list(dict.fromkeys([p for p in products if p]))
    domains_uniq = list(dict.fromkeys([d for d in domains if d]))
    if not company or (not products_uniq and not domains_uniq):
        return None
    lang_n = normalize_lang(lang, default="zh")
    if lang_n == "en":
        top_products = ", ".join(products_uniq[:3]) if products_uniq else "related products"
        top_domains = ", ".join(domains_uniq[:3]) if domains_uniq else "multiple industries"
        return f"{company} provides {top_products} and is mainly applied in {top_domains}."
    if lang_n == "ko":
        top_products = ", ".join(products_uniq[:3]) if products_uniq else "관련 제품"
        top_domains = ", ".join(domains_uniq[:3]) if domains_uniq else "여러 산업"
        return f"{company}는 {top_products}를 제공하며, 주로 {top_domains} 분야에 적용됩니다."
    top_products = "、".join(products_uniq[:3]) if products_uniq else "相关产品"
    top_domains = "、".join(domains_uniq[:3]) if domains_uniq else "多个行业"
    return f"{company} 提供 {top_products}，主要应用于 {top_domains}"


def _format_relations_for_prompt(relations: List[Dict[str, str]], limit: int = 12) -> str:
    lines: List[str] = []
    for r in relations[:limit]:
        s, rel, t = r.get("source"), r.get("relation"), r.get("target")
        if s and rel and t:
            lines.append(f"{s} -{rel}-> {t}")
    return "; ".join(lines) if lines else "(none)"


def _llm_one_sentence_insight_doc(
    entities: List[str],
    relations: List[Dict[str, str]],
    snippets: List[str],
    lang: str,
) -> str:
    """基于实体/关系/片段生成一句话业务理解（QueryPipeline 之外独立调用）。"""
    lang_n = normalize_lang(lang, default="zh")
    excerpt = " ".join(snippets)[:900]
    ent = "、".join(entities[:20]) if entities else "(none)"
    rels = _format_relations_for_prompt(relations, limit=15)
    if lang_n == "en":
        prompt = (
            "You are a business knowledge assistant. Write exactly ONE concise sentence (max 40 words) "
            "describing what this document is mainly about for a business reader.\n"
            "Use only the facts implied by the lists below. No bullet points. No quotes. English only.\n\n"
            f"Entities: {ent}\n"
            f"Graph relations: {rels}\n"
            f"Text excerpts: {excerpt}\n"
        )
    elif lang_n == "ko":
        prompt = (
            "당신은 기업 지식 도우미입니다. 아래 정보만 근거로, 이 문서가 무엇을 다루는지 비즈니스 독자에게 "
            "한 문장(40단어 이내)으로만 설명하세요.\n"
            "목록/따옴표/번호 금지. 한국어만 사용하세요.\n\n"
            f"엔티티: {ent}\n"
            f"그래프 관계: {rels}\n"
            f"텍스트 발췌: {excerpt}\n"
        )
    else:
        prompt = (
            "你是企业知识助手。仅根据下列信息，用「恰好一句」中文（不超过 60 字）概括该文档对业务读者的核心价值；"
            "不要分点、不要引号、不要编号。\n\n"
            f"实体：{ent}\n"
            f"图谱关系：{rels}\n"
            f"正文摘录：{excerpt}\n"
        )
    try:
        raw = str(graph_engine.llm.complete(prompt)).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("insight LLM failed: %s", e)
        return ""
    line = raw.split("\n")[0].strip().strip('"').strip("'")
    if len(line) > 220:
        line = line[:217].rstrip() + "…"
    return line


def _llm_one_sentence_insight_entity(
    canonical: str,
    products: List[str],
    domains: List[str],
    documents: List[str],
    relations: List[Dict[str, str]],
    lang: str,
) -> str:
    lang_n = normalize_lang(lang, default="zh")
    rels = _format_relations_for_prompt(relations, limit=15)
    prods = "、".join(products[:12]) if products else "(none)"
    doms = "、".join(domains[:12]) if domains else "(none)"
    docs = "、".join(documents[:8]) if documents else "(none)"
    if lang_n == "en":
        prompt = (
            "Write exactly ONE concise sentence (max 40 words) summarizing what this entity represents "
            "in the company knowledge base, for a business reader.\n"
            "Use only the facts below. English only. No bullets or quotes.\n\n"
            f"Entity: {canonical}\n"
            f"Products linked: {prods}\n"
            f"Industries: {doms}\n"
            f"Related documents: {docs}\n"
            f"Graph relations: {rels}\n"
        )
    elif lang_n == "ko":
        prompt = (
            "아래 정보만 근거로, 이 엔티티가 지식베이스에서 무엇을 의미하는지 비즈니스 독자에게 한 문장(40단어 이내)으로만 설명하세요.\n"
            "한국어만. 목록/따옴표 금지.\n\n"
            f"엔티티: {canonical}\n"
            f"연결 제품: {prods}\n"
            f"산업: {doms}\n"
            f"관련 문서: {docs}\n"
            f"그래프 관계: {rels}\n"
        )
    else:
        prompt = (
            "根据下列信息，用「恰好一句」中文（不超过 60 字）概括该实体在知识库中的业务含义；不要分点、不要引号。\n\n"
            f"实体：{canonical}\n"
            f"关联产品：{prods}\n"
            f"行业：{doms}\n"
            f"相关文档：{docs}\n"
            f"图谱关系：{rels}\n"
        )
    try:
        raw = str(graph_engine.llm.complete(prompt)).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("entity insight LLM failed: %s", e)
        return ""
    line = raw.split("\n")[0].strip().strip('"').strip("'")
    if len(line) > 220:
        line = line[:217].rstrip() + "…"
    return line


def _triples_from_relation_dicts(relations: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in relations:
        s, rel, t = r.get("source"), r.get("relation"), r.get("target")
        if s and rel and t:
            out.append({"source": str(s), "relation": str(rel), "target": str(t)})
    return out


def _compute_document_insight(
    doc_name: str,
    relations: List[Dict[str, str]],
    entities: List[str],
    snippets: List[str],
    lang: str | None,
) -> str:
    lang_n = normalize_lang(lang or "zh", default="zh")
    cache_parts = ["doc", doc_name, lang_n, GRAPH_VERSION]
    cached = _insight_cache_get(cache_parts)
    if isinstance(cached, str) and cached.strip():
        return cached.strip()

    triples = _triples_from_relation_dicts(relations)
    graph_line = _build_graph_summary_from_triples(triples, lang_n)
    if graph_line:
        out = enforce_language(graph_line.strip(), lang_n, llm=graph_engine.llm)
        _insight_cache_set(cache_parts, out)
        return out

    llm_line = _llm_one_sentence_insight_doc(entities, relations, snippets, lang_n)
    if llm_line:
        out = enforce_language(llm_line, lang_n, llm=graph_engine.llm)
        _insight_cache_set(cache_parts, out)
        return out

    return ""


def _entity_relation_triples(canonical: str) -> List[Dict[str, str]]:
    cypher = """
    MATCH (a:Entity {name: $name})-[r]->(b:Entity)
    WHERE type(r) <> 'ALIAS_OF'
      AND ($min_kg_conf <= 0 OR coalesce(r.kg_confidence, 1.0) >= $min_kg_conf)
    RETURN type(r) AS rel, a.name AS source, b.name AS target
    LIMIT 40
    """
    rows = _run_cypher(cypher, params_with_min_kg_conf({"name": canonical}))
    out: List[Dict[str, str]] = []
    for row in rows:
        rel = row.get("rel")
        src = row.get("source")
        tgt = row.get("target")
        if rel and src and tgt:
            out.append({"source": str(src), "relation": str(rel), "target": str(tgt)})
    return out


def _compute_entity_insight(
    canonical: str,
    products: List[str],
    domains: List[str],
    documents: List[str],
    lang: str | None,
) -> str:
    lang_n = normalize_lang(lang or "zh", default="zh")
    cache_parts = ["entity", canonical, lang_n, GRAPH_VERSION]
    cached = _insight_cache_get(cache_parts)
    if isinstance(cached, str) and cached.strip():
        return cached.strip()

    triples = _entity_relation_triples(canonical)
    graph_line = _build_graph_summary_from_triples(triples, lang_n)
    if graph_line:
        out = enforce_language(graph_line.strip(), lang_n, llm=graph_engine.llm)
        _insight_cache_set(cache_parts, out)
        return out

    llm_line = _llm_one_sentence_insight_entity(
        canonical, products, domains, documents, triples, lang_n
    )
    if llm_line:
        out = enforce_language(llm_line, lang_n, llm=graph_engine.llm)
        _insight_cache_set(cache_parts, out)
        return out

    return ""


def _parse_di_json_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()][:20]
    if isinstance(val, str) and val.strip():
        try:
            j = json.loads(val)
            if isinstance(j, list):
                return [str(x).strip() for x in j if str(x).strip()][:20]
        except json.JSONDecodeError:
            pass
    return []


def _document_intelligence_from_vector(filename: str) -> Dict[str, Any]:
    """从向量表任意一条 chunk 的 metadata 读取 di_* 字段。"""
    fn = (filename or "").strip()
    out: Dict[str, Any] = {
        "summary": "",
        "keywords": [],
        "topics": [],
        "entities": [],
        "key_points": [],
        "doc_type": "",
    }
    if not fn:
        return out
    table = vector_engine.full_table_name
    for col in ("metadata_", "metadata"):
        try:
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
            )
            cur = conn.cursor()
            cur.execute(
                f"SELECT {col} FROM {table} "
                f"WHERE ({col} ->> 'file_name') = %s LIMIT 1",
                (fn,),
            )
            row = cur.fetchone()
            conn.close()
            if not row or row[0] is None:
                continue
            md = row[0]
            if isinstance(md, str):
                try:
                    md = json.loads(md)
                except json.JSONDecodeError:
                    md = {}
            if not isinstance(md, dict):
                continue
            out["summary"] = str(md.get(DI_SUMMARY) or "").strip()
            out["keywords"] = _parse_di_json_list(md.get(DI_KEYWORDS))
            out["topics"] = _parse_di_json_list(md.get(DI_TOPICS))
            out["entities"] = _parse_di_json_list(md.get(DI_ENTITIES))
            out["key_points"] = _parse_di_json_list(md.get(DI_KEY_POINTS))
            out["doc_type"] = str(md.get(DI_DOC_TYPE) or "").strip().lower()
            return out
        except Exception as e:  # noqa: BLE001
            logger.debug("di metadata read failed col=%s: %s", col, e)
    return out


def _vector_first_snippet_for_file(filename: str) -> str:
    """从当前向量表取该文件任意一条 chunk 的 text 作为摘要/片段。"""
    fn = (filename or "").strip()
    if not fn:
        return ""
    table = vector_engine.full_table_name
    for col in ("metadata_", "metadata"):
        try:
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
            )
            cur = conn.cursor()
            cur.execute(
                f"SELECT text FROM {table} "
                f"WHERE ({col} ->> 'file_name') = %s "
                f"LIMIT 1",
                (fn,),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                t = str(row[0]).strip().replace("\n", " ")
                if len(t) > _SNIPPET_MAX:
                    return t[: _SNIPPET_MAX].rstrip() + "…"
                return t
        except Exception as e:  # noqa: BLE001
            logger.debug("vector snippet query failed col=%s: %s", col, e)
    return ""


def _entities_for_file(filename: str) -> List[str]:
    fn = (filename or "").strip()
    if not fn:
        return []
    cypher = """
    MATCH (n) WHERE n.file_name = $fn
    MATCH path = (n)-[*1..5]-(e:Entity)
    RETURN DISTINCT e.name AS name
    ORDER BY name
    LIMIT 40
    """
    rows = _run_cypher(cypher, {"fn": fn})
    out: List[str] = []
    seen: set[str] = set()
    for r in rows:
        name = r.get("name")
        if isinstance(name, str) and name.strip() and name not in seen:
            seen.add(name)
            out.append(name.strip())
    return out


def _relations_among_entities(entity_names: List[str]) -> List[Dict[str, str]]:
    if len(entity_names) < 2:
        return []
    cypher = """
    MATCH (x:Entity)-[r]->(y:Entity)
    WHERE x.name IN $names AND y.name IN $names
      AND ($min_kg_conf <= 0 OR coalesce(r.kg_confidence, 1.0) >= $min_kg_conf)
    RETURN DISTINCT type(r) AS rel, x.name AS source, y.name AS target
    LIMIT 50
    """
    rows = _run_cypher(cypher, params_with_min_kg_conf({"names": entity_names[:25]}))
    rels: List[Dict[str, str]] = []
    for rec in rows:
        rel = rec.get("rel")
        src = rec.get("source")
        tgt = rec.get("target")
        if rel and src and tgt and rel != "ALIAS_OF":
            rels.append({"source": str(src), "relation": str(rel), "target": str(tgt)})
    return rels


def _infer_tags(entities: List[str], relations: List[Dict[str, str]]) -> List[str]:
    tags: List[str] = []
    rel_types = {r.get("relation", "") for r in relations if r.get("relation")}
    for rt in sorted(rel_types):
        if rt and rt not in tags and rt != "ALIAS_OF":
            tags.append(rt)
    for e in entities[:6]:
        if e not in tags:
            tags.append(e)
    return tags[:12]


def _file_meta_on_disk(name: str) -> Dict[str, Any]:
    base = settings.DATA_RAW_DIR
    path = os.path.join(base, name)
    meta: Dict[str, Any] = {"size": None, "uploaded_at": None, "mtime": 0.0}
    try:
        if os.path.isfile(path):
            st = os.stat(path)
            meta["size"] = st.st_size
            meta["mtime"] = float(st.st_mtime)
            meta["uploaded_at"] = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError as e:
        logger.debug("stat failed for %s: %s", name, e)
    return meta


def list_product_documents_controller() -> Dict[str, List[Dict[str, Any]]]:
    """GET /docs — 聚合磁盘文件 + 向量摘要 + 图实体。"""
    base = settings.DATA_RAW_DIR
    if not os.path.isdir(base):
        return {"documents": []}

    docs: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(base)):
        full = os.path.join(base, fname)
        if not os.path.isfile(full):
            continue
        if not is_allowed_extension(fname):
            continue
        di = _document_intelligence_from_vector(fname)
        summary = (di.get("summary") or "").strip() or _vector_first_snippet_for_file(fname)
        entities = _entities_for_file(fname)
        rels = _relations_among_entities(entities)
        tags = _infer_tags(entities, rels)
        # 列表：摘要优先 DI；关键词可作为补充标签
        kw = di.get("keywords") or []
        if isinstance(kw, list) and kw:
            tags = list(dict.fromkeys(list(tags) + [str(x) for x in kw[:8] if x]))[:16]
        disk = _file_meta_on_disk(fname)
        docs.append(
            {
                "id": fname,
                "name": fname,
                "summary": summary or "",
                "entities": entities,
                "tags": tags,
                "keywords": di.get("keywords") or [],
                "topics": di.get("topics") or [],
                "doc_type": di.get("doc_type") or "",
                "uploaded_at": disk.get("uploaded_at"),
                "mtime": disk.get("mtime") or 0.0,
            }
        )
    return {"documents": docs}


def get_product_document_controller(doc_id: str, lang: str | None = None) -> Dict[str, Any] | None:
    """GET /docs/{id} — doc_id 为磁盘上的文件名（URL 解码后）。"""
    name = (doc_id or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = os.path.join(settings.DATA_RAW_DIR, name)
    if not os.path.isfile(path) or not is_allowed_extension(name):
        return None

    di = _document_intelligence_from_vector(name)
    summary = (di.get("summary") or "").strip() or _vector_first_snippet_for_file(name)
    entities = _entities_for_file(name)
    rels = _relations_among_entities(entities)
    tags = _infer_tags(entities, rels)
    disk = _file_meta_on_disk(name)

    # 额外：最多 5 条向量片段（同文件）
    snippets: List[str] = []
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        for col in ("metadata_", "metadata"):
            try:
                cur.execute(
                    f"SELECT text FROM {vector_engine.full_table_name} "
                    f"WHERE ({col} ->> 'file_name') = %s LIMIT 5",
                    (name,),
                )
                for row in cur.fetchall() or []:
                    if row and row[0]:
                        t = str(row[0]).strip().replace("\n", " ")
                        if len(t) > _SEARCH_SNIPPET:
                            t = t[:_SEARCH_SNIPPET].rstrip() + "…"
                        if t and t not in snippets:
                            snippets.append(t)
                if snippets:
                    break
            except Exception:  # noqa: BLE001
                continue
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.debug("detail snippets failed: %s", e)

    insight = _compute_document_insight(name, rels, entities, snippets, lang)

    return {
        "id": name,
        "doc_id": name,
        "name": name,
        "insight": insight,
        "summary": summary or "",
        "entities": entities,
        "tags": tags,
        "relations": rels,
        "related_snippets": snippets,
        "size": disk.get("size"),
        "uploaded_at": disk.get("uploaded_at"),
        "keywords": di.get("keywords") or [],
        "topics": di.get("topics") or [],
        "key_points": di.get("key_points") or [],
        "doc_type": di.get("doc_type") or "",
        "intelligence_entities": di.get("entities") or [],
    }


def search_chunks_controller(query: str, top_k: int = 10) -> Dict[str, Any]:
    """GET /search — 向量检索 top chunks。"""
    q = (query or "").strip()
    if not q:
        return {"query": "", "results": []}
    k = max(1, min(int(top_k or 10), 30))
    try:
        retriever = vector_engine.get_retriever(similarity_top_k=k)
        nodes = retriever.retrieve(q)
    except Exception as e:  # noqa: BLE001
        logger.warning("search retrieve failed: %s", e)
        return {"query": q, "results": []}

    results: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    di_cache: Dict[str, Dict[str, Any]] = {}

    def _di_for(fn: str) -> Dict[str, Any]:
        if fn not in di_cache:
            di_cache[fn] = _document_intelligence_from_vector(fn)
        return di_cache[fn]

    for nws in nodes or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        text = (getattr(node, "text", None) or "").strip()
        md = getattr(node, "metadata", None) or {}
        doc = str(md.get("file_name") or md.get("source") or "").strip() or "unknown"
        if not text:
            continue
        snip = text.replace("\n", " ")
        if len(snip) > _SEARCH_SNIPPET:
            snip = snip[:_SEARCH_SNIPPET].rstrip() + "…"
        key = (doc, snip[:80])
        if key in seen:
            continue
        seen.add(key)
        di = _di_for(doc)
        kw_raw = di.get("keywords") or []
        kw_list = [str(x).strip() for x in kw_raw[:2] if x and str(x).strip()]
        dt = str(di.get("doc_type") or "").strip().lower()
        row: Dict[str, Any] = {"doc": doc, "snippet": snip}
        if dt:
            row["doc_type"] = dt
        if kw_list:
            row["keywords"] = kw_list
        results.append(row)
    return {"query": q, "results": results}


def _entity_products_domains(canonical: str) -> tuple[List[str], List[str]]:
    cypher_p = """
    MATCH (e:Entity {name: $name})-[:PROVIDES]->(p:Entity)
    RETURN collect(DISTINCT p.name) AS products
    """
    rows = _run_cypher(cypher_p, {"name": canonical})
    products: List[str] = []
    if rows:
        raw = rows[0].get("products") or []
        if isinstance(raw, list):
            products = [str(x) for x in raw if x]

    cypher_d = """
    MATCH (e:Entity {name: $name})-[:PROVIDES]->(:Entity)-[:APPLIES_TO]->(d:Entity)
    RETURN collect(DISTINCT d.name) AS domains
    """
    rows2 = _run_cypher(cypher_d, {"name": canonical})
    domains: List[str] = []
    if rows2:
        raw2 = rows2[0].get("domains") or []
        if isinstance(raw2, list):
            domains = [str(x) for x in raw2 if x]
    return products, domains


def _weak_entity_documents(needle: str, limit: int = 30) -> List[str]:
    """
    图中无 Entity 时，用语义检索 + 正文子串匹配找可能相关文档（distinct file_name）。
    """
    q = (needle or "").strip()
    if len(q) < 2:
        return []
    seen: set[str] = set()
    out: List[str] = []

    try:
        retriever = vector_engine.get_retriever(similarity_top_k=min(24, limit))
        for nws in retriever.retrieve(q) or []:
            node = getattr(nws, "node", None)
            if node is None:
                continue
            md = getattr(node, "metadata", None) or {}
            fn = str(md.get("file_name") or "").strip()
            if fn and fn not in seen:
                seen.add(fn)
                out.append(fn)
            if len(out) >= limit:
                return out
    except Exception as e:  # noqa: BLE001
        logger.debug("weak entity vector retrieve failed: %s", e)

    safe_like = re.sub(r"[%_\\]", " ", q).strip()
    if len(safe_like) < 2:
        return out[:limit]
    pattern = f"%{safe_like}%"
    table = vector_engine.full_table_name
    for col in ("metadata_", "metadata"):
        try:
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
            )
            cur = conn.cursor()
            cur.execute(
                f"SELECT DISTINCT ({col} ->> 'file_name') AS fn FROM {table} "
                f"WHERE text IS NOT NULL AND text ILIKE %s "
                f"AND ({col} ->> 'file_name') IS NOT NULL "
                f"LIMIT %s",
                (pattern, limit),
            )
            for row in cur.fetchall() or []:
                fn = row[0]
                if isinstance(fn, str) and fn.strip() and fn.strip() not in seen:
                    seen.add(fn.strip())
                    out.append(fn.strip())
            conn.close()
        except Exception as e:  # noqa: BLE001
            logger.debug("weak entity ilike failed col=%s: %s", col, e)
    return out[:limit]


def _documents_mentioning_entity(canonical: str, limit: int = 40) -> List[str]:
    cypher = """
    MATCH (n) WHERE n.file_name IS NOT NULL
    MATCH (n)-[*1..5]-(e:Entity {name: $name})
    RETURN DISTINCT n.file_name AS fn
    ORDER BY fn
    LIMIT $limit
    """
    rows = _run_cypher(cypher, {"name": canonical, "limit": limit})
    out: List[str] = []
    for r in rows:
        fn = r.get("fn")
        if isinstance(fn, str) and fn.strip():
            out.append(fn.strip())
    return out


def get_entity_profile_controller(name: str, lang: str | None = None) -> Dict[str, Any] | None:
    """GET /entity/{name} — 实体档案（图聚合）。"""
    raw = (name or "").strip()
    if not raw:
        return None
    canonical = _resolve_canonical_entity(raw) or raw
    # 确认图中存在该实体
    check = _run_cypher(
        "MATCH (e:Entity {name: $n}) RETURN e.name AS name LIMIT 1",
        {"n": canonical},
    )
    if not check:
        fuzzy = _run_cypher(
            """
            MATCH (e:Entity)
            WHERE toLower(e.name) = toLower($n)
            RETURN e.name AS name
            LIMIT 1
            """,
            {"n": raw},
        )
        if fuzzy:
            canonical = str(fuzzy[0].get("name") or canonical)
        else:
            weak_docs = _weak_entity_documents(raw)
            return {
                "entity": raw,
                "insight": "",
                "products": [],
                "domains": [],
                "documents": weak_docs,
                "weak_profile": True,
            }

    products, domains = _entity_products_domains(canonical)
    documents = _documents_mentioning_entity(canonical)
    insight = _compute_entity_insight(canonical, products, domains, documents, lang)
    return {
        "entity": canonical,
        "insight": insight,
        "products": products,
        "domains": domains,
        "documents": documents,
        "weak_profile": False,
    }
