import logging
from typing import Any, Dict, List

from api.deps import graph_engine
from core.lang_detect import detect_lang, normalize_lang
from core.query_cache import QueryCache, GRAPH_VERSION
from core.entity_normalization import normalize_entity

logger = logging.getLogger(__name__)
try:
    _graph_cache: QueryCache | None = QueryCache()
except Exception:  # noqa: BLE001
    _graph_cache = None

_GRAPH_TTL = 600
_index_ensured = False


def _lang_bucket(lang: str | None) -> str:
    return normalize_lang(lang, default="en")


def _parse_question_lines(raw: str, limit: int = 5) -> List[str]:
    questions: List[str] = []
    for line in (raw or "").splitlines():
        q = line.strip().lstrip("-").strip()
        if not q:
            continue
        if len(q) < 3:
            continue
        if len(q) > 80:
            q = q[:80].rstrip()
        questions.append(q)
        if len(questions) >= limit:
            break
    return questions


def _questions_match_lang(questions: List[str], lang: str) -> bool:
    if not questions:
        return True
    expected = _lang_bucket(lang)
    actual = detect_lang(" ".join(questions))
    return actual == expected


def _rewrite_questions(raw_questions: List[str], lang: str) -> List[str]:
    if not raw_questions:
        return []
    expected = _lang_bucket(lang)
    language_name = {"zh": "Chinese", "en": "English", "ko": "Korean"}.get(expected, "English")
    joined = "\n".join(raw_questions[:5])
    prompt = (
        f"Rewrite the following questions into {language_name}.\n"
        "Keep the meaning unchanged.\n"
        "Return 3-5 natural clickable questions.\n"
        "One question per line. No numbering. No explanation.\n\n"
        f"Questions:\n{joined}\n"
    )
    try:
        rewritten = str(graph_engine.llm.complete(prompt))
    except Exception:  # noqa: BLE001
        return []
    rewritten_questions = _parse_question_lines(rewritten)
    if _questions_match_lang(rewritten_questions, expected):
        return rewritten_questions[:5]
    return []


def _fallback_questions(entity: str, lang: str, products: List[str] | None = None, domains: List[str] | None = None) -> List[str]:
    expected = _lang_bucket(lang)
    products = list(dict.fromkeys(products or []))[:5]
    domains = list(dict.fromkeys(domains or []))[:5]
    product = products[0] if products else entity
    domain = domains[0] if domains else None
    if expected == "en":
        return [
            f"What are the core products of {entity}?",
            f"What industry use-cases does {entity} have in {domain if domain else 'its target industries'}?",
            f"What problems can {product} solve?",
        ]
    if expected == "ko":
        return [
            f"{entity}의 핵심 제품은 무엇인가요?",
            f"{entity}는 {domain if domain else '주요 산업'}에서 어떤 활용 사례가 있나요?",
            f"{product}는 어떤 문제를 해결하는 데 적합한가요?",
        ]
    return [
        f"{entity} 的核心产品有哪些？",
        f"{entity} 在 {domain if domain else '行业'} 有哪些落地案例？",
        f"{product} 适合解决什么问题？",
    ]


def _ensure_entity_name_index() -> None:
    global _index_ensured
    if _index_ensured:
        return
    try:
        _run_cypher("CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)")
        _index_ensured = True
    except Exception:  # noqa: BLE001
        pass

def _resolve_canonical_entity(query: str) -> str | None:
    q = (query or "").strip()
    if not q:
        return None
    nq = normalize_entity(q)
    _ensure_entity_name_index()
    cypher_exact = """
    MATCH (a:Entity {name: $q})
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
    RETURN coalesce(b.name, a.name) AS canonical
    LIMIT 1
    """
    rows = _run_cypher(cypher_exact, {"q": q})
    if not rows and nq and nq != q.lower():
        rows = _run_cypher(cypher_exact, {"q": nq})
    if rows:
        try:
            canonical = rows[0].get("canonical")
            if isinstance(canonical, str) and canonical.strip():
                return canonical
        except Exception:  # noqa: BLE001
            pass
    cypher_fallback = """
    MATCH (a:Entity)
    WHERE toLower(a.name) CONTAINS toLower($q)
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
    RETURN coalesce(b.name, a.name) AS canonical
    LIMIT 1
    """
    rows = _run_cypher(cypher_fallback, {"q": q})
    if not rows and nq and nq != q.lower():
        rows = _run_cypher(cypher_fallback, {"q": nq})
    if not rows:
        return None
    try:
        canonical = rows[0].get("canonical")
    except Exception:  # noqa: BLE001
        return None
    return canonical if isinstance(canonical, str) and canonical.strip() else None


def _resolve_entity_node_name(query: str) -> str | None:
    q = (query or "").strip()
    if not q:
        return None
    nq = normalize_entity(q)
    _ensure_entity_name_index()
    cypher_exact = """
    MATCH (a:Entity {name: $q})
    RETURN a.name AS name
    LIMIT 1
    """
    rows = _run_cypher(cypher_exact, {"q": q})
    if not rows and nq and nq != q.lower():
        rows = _run_cypher(cypher_exact, {"q": nq})
    if rows:
        try:
            name = rows[0].get("name")
            if isinstance(name, str) and name.strip():
                return name
        except Exception:  # noqa: BLE001
            pass
    cypher_fallback = """
    MATCH (a:Entity)
    WHERE toLower(a.name) CONTAINS toLower($q)
    RETURN a.name AS name
    LIMIT 1
    """
    rows = _run_cypher(cypher_fallback, {"q": q})
    if not rows and nq and nq != q.lower():
        rows = _run_cypher(cypher_fallback, {"q": nq})
    if not rows:
        return None
    try:
        name = rows[0].get("name")
    except Exception:  # noqa: BLE001
        return None
    return name if isinstance(name, str) and name.strip() else None


def _format_node(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": record["id"],
        "labels": record.get("labels", []),
        "properties": record.get("properties", {}),
    }


def _run_cypher(query: str, params: Dict[str, Any] | None = None):
    """Helper to run a Cypher query via the shared GraphEngine driver."""
    params = params or {}
    try:
        with graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
            return list(session.run(query, **params))
    except Exception as e:  # noqa: BLE001
        logger.error("Cypher query failed: %s", e)
        return []


def list_nodes_controller(limit: int = 100) -> Dict[str, List[Dict[str, Any]]]:
    """
    返回图中部分节点，用于 Graph Explorer 初始视图。
    """
    cypher = """
    MATCH (n)
    RETURN id(n) AS id, labels(n) AS labels, properties(n) AS properties
    LIMIT $limit
    """
    records = _run_cypher(cypher, {"limit": limit})
    nodes = [_format_node(rec) for rec in records]
    return {"nodes": nodes}


def list_relations_controller(limit: int = 100) -> Dict[str, List[Dict[str, Any]]]:
    """
    返回图中部分关系（带节点），用于全局关系概览。
    """
    cypher = """
    MATCH (n)-[r]->(m)
    RETURN
      id(n) AS source_id,
      labels(n) AS source_labels,
      properties(n) AS source_props,
      id(m) AS target_id,
      labels(m) AS target_labels,
      properties(m) AS target_props,
      type(r) AS type,
      properties(r) AS rel_props
    LIMIT $limit
    """
    records = _run_cypher(cypher, {"limit": limit})

    nodes: Dict[Any, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for rec in records:
        sid = rec["source_id"]
        tid = rec["target_id"]
        if sid not in nodes:
            nodes[sid] = {
                "id": sid,
                "labels": rec.get("source_labels", []),
                "properties": rec.get("source_props", {}),
            }
        if tid not in nodes:
            nodes[tid] = {
                "id": tid,
                "labels": rec.get("target_labels", []),
                "properties": rec.get("target_props", {}),
            }
        edges.append(
            {
                "source": sid,
                "target": tid,
                "type": rec.get("type"),
                "properties": rec.get("rel_props", {}),
            }
        )

    return {"nodes": list(nodes.values()), "edges": edges}


def graph_overview_controller() -> Dict[str, Any]:
    """
    图谱总览信息：节点数、关系数、按类型统计、部分代表实体。
    """
    overview: Dict[str, Any] = {}
    try:
        with graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
            node_count_result = session.run("MATCH (n) RETURN count(n) AS cnt")
            overview["node_count"] = node_count_result.single()["cnt"]

            edge_count_result = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            overview["edge_count"] = edge_count_result.single()["cnt"]

            type_rows = session.run(
                """
                MATCH (n)
                WITH labels(n)[0] AS type
                RETURN type, count(*) AS cnt
                ORDER BY cnt DESC
                LIMIT 10
                """
            )
            overview["entity_types"] = [
                {"type": rec["type"] or "Unknown", "count": rec["cnt"]} for rec in type_rows
            ]

            top_rows = session.run(
                """
                MATCH (n)
                WHERE exists(n.name)
                RETURN n.name AS name
                LIMIT 10
                """
            )
            overview["top_entities"] = [rec["name"] for rec in top_rows]
        return overview
    except Exception as e:  # noqa: BLE001
        logger.error("Graph overview failed: %s", e)
        return {"node_count": 0, "edge_count": 0, "entity_types": [], "top_entities": []}


def entity_types_controller() -> Dict[str, Any]:
    """
    返回按实体类型聚合的统计信息，用于 Entity Browser 顶部的类型列表。
    """
    with graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
        rows = session.run(
            """
            MATCH (n)
            WHERE exists(n.name)
            WITH labels(n)[0] AS type
            RETURN type, count(*) AS cnt
            ORDER BY cnt DESC
            LIMIT 20
            """
        )
        types = [
            {"type": rec["type"] or "Unknown", "count": rec["cnt"]}
            for rec in rows
        ]
    return {"types": types}


def suggested_questions_controller(limit: int = 10, lang: str = "zh") -> Dict[str, List[str]]:
    """
    根据图中的关系自动生成一组“推荐问题”。
    """
    cypher = """
    MATCH (a)-[r]->(b)
    WHERE exists(a.name) AND exists(b.name)
    RETURN a.name AS a_name, type(r) AS rel, b.name AS b_name
    LIMIT $limit
    """
    records = _run_cypher(cypher, {"limit": limit})

    questions: List[str] = []
    lang_bucket = _lang_bucket(lang)
    for rec in records:
        a_name = rec.get("a_name")
        b_name = rec.get("b_name")
        if not a_name or not b_name:
            continue
        if lang_bucket == "en":
            q = f"How is {a_name} related to {b_name}?"
        elif lang_bucket == "ko":
            q = f"{a_name}와 {b_name}는 어떤 관계인가요?"
        else:
            q = f"{a_name} 和 {b_name} 是什么关系？"
        questions.append(q)

    # 去重
    seen = set()
    uniq: List[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            uniq.append(q)

    return {"questions": uniq}


def entity_suggestions_controller(entity: str, limit: int = 5, lang: str = "zh") -> Dict[str, Any]:
    """
    基于指定实体的一阶关系生成中文“推荐问题”。
    """
    norm_entity = normalize_entity(entity)
    resolved_node = _resolve_entity_node_name(entity) or (entity or "").strip()
    canonical = _resolve_canonical_entity(entity) or resolved_node
    lang_bucket = _lang_bucket(lang)
    lang_key = (lang or "zh").strip().lower()
    cache_key = f"graph:suggestions:{norm_entity or canonical}|{lang_key}|{GRAPH_VERSION}"
    if _graph_cache is not None:
        cached = _graph_cache.get(cache_key)
        if isinstance(cached, dict) and _questions_match_lang(cached.get("questions") or [], lang_bucket):
            return cached
    cypher = """
    MATCH (a:Entity {name: $entity})
    MATCH (a)-[r]->(b:Entity)
    RETURN type(r) AS rel, b.name AS name
    LIMIT $limit
    """
    records = _run_cypher(cypher, {"entity": canonical, "limit": limit})
    if not records:
        records = _run_cypher(
            """
            MATCH (a:Entity)
            WHERE toLower(a.name) CONTAINS toLower($entity)
            MATCH (a)-[r]->(b:Entity)
            RETURN type(r) AS rel, b.name AS name
            LIMIT $limit
            """,
            {"entity": canonical, "limit": limit},
        )

    relations: List[Dict[str, str]] = []
    for rec in records:
        rel = rec.get("rel")
        b_name = rec.get("name")
        if not rel or not b_name:
            continue
        if rel == "ALIAS_OF":
            continue
        relations.append({"type": rel, "target": b_name})

    two_hop_rows: List[Dict[str, Any]] = []
    cypher2 = """
    MATCH (a:Entity {name: $entity})
    MATCH (a)-[:PROVIDES]->(b:Entity)
    OPTIONAL MATCH (b)-[:APPLIES_TO]->(c:Entity)
    RETURN b.name AS product, collect(DISTINCT c.name) AS domains
    LIMIT 10
    """
    rows2 = _run_cypher(cypher2, {"entity": canonical})
    if not rows2:
        rows2 = _run_cypher(
            """
            MATCH (a:Entity)
            WHERE toLower(a.name) CONTAINS toLower($entity)
            MATCH (a)-[:PROVIDES]->(b:Entity)
            OPTIONAL MATCH (b)-[:APPLIES_TO]->(c:Entity)
            RETURN b.name AS product, collect(DISTINCT c.name) AS domains
            LIMIT 10
            """,
            {"entity": canonical},
        )
    for r in rows2:
        p = r.get("product")
        ds = r.get("domains") or []
        if not p:
            continue
        if not isinstance(ds, list):
            ds = []
        two_hop_rows.append({"product": p, "domains": [x for x in ds if x]})

    if lang_bucket == "en":
        prompt = (
            "Answer ONLY in English. Do not use Chinese.\n"
            "Generate 3-5 natural clickable questions based on graph relations.\n"
            "Requirements:\n"
            "- no duplicates\n"
            "- cover products, industries, comparison, use-cases\n"
            "- one question per line, no numbering, no explanation\n\n"
            f"entity: {canonical}\n"
            f"relations: {relations}\n"
            f"two_hop: {two_hop_rows}\n"
        )
    elif lang_bucket == "ko":
        prompt = (
            "항상 한국어로 답변하세요. 영어와 중국어를 사용하지 마세요.\n"
            "당신은 기업 지식 도우미입니다. 주어진 회사/엔터티와 그래프 정보를 바탕으로 자연스럽고 클릭 가능한 한국어 질문 3-5개를 생성하세요.\n"
            "요구사항:\n"
            "- 중복 금지, 제품별 기계적인 나열 금지\n"
            "- 핵심 제품, 산업 적용, 제품 비교/차이점, 실제 활용 시나리오를 고르게 포함\n"
            "- 한 줄에 질문 하나씩만 출력하고 번호나 설명은 쓰지 마세요\n\n"
            f"entity: {canonical}\n"
            f"relations: {relations}\n"
            f"two_hop: {two_hop_rows}\n"
        )
    else:
        prompt = (
            "请始终使用中文回答。不要使用英文。\n"
            "你是企业知识助手。请基于给定的公司/实体及其图谱信息，生成 3-5 个自然、有人味、可点击的中文问题。\n"
            "要求：\n"
            "- 不重复，不逐个产品机械提问\n"
            "- 覆盖：核心产品、行业应用、产品对比/差异、落地场景\n"
            "- 每行一个问题，禁止编号，禁止解释\n\n"
            f"entity: {canonical}\n"
            f"relations: {relations}\n"
            f"two_hop: {two_hop_rows}\n"
        )

    try:
        raw = str(graph_engine.llm.complete(prompt))
    except Exception:  # noqa: BLE001
        raw = ""

    qs = _parse_question_lines(raw)
    products = [r.get("target") for r in relations if r.get("type") == "PROVIDES" and r.get("target")]
    domains = []
    for row in two_hop_rows:
        for d in row.get("domains") or []:
            domains.append(d)

    if qs and not _questions_match_lang(qs, lang_bucket):
        actual_lang = detect_lang(" ".join(qs))
        logger.warning(
            "Suggestions language mismatch: entity=%s expected=%s actual=%s cache_key=%s",
            canonical,
            lang_bucket,
            actual_lang,
            cache_key,
        )
        rewritten = _rewrite_questions(qs, lang_bucket)
        qs = rewritten if rewritten else []

    if not qs or not _questions_match_lang(qs, lang_bucket):
        qs = _fallback_questions(canonical, lang_bucket, products=products, domains=domains)

    # 去重
    seen = set()
    uniq_q: List[str] = []
    for q in qs:
        if q not in seen:
            seen.add(q)
            uniq_q.append(q)

    payload = {"entity": canonical, "canonical": canonical, "resolved": resolved_node, "relations": relations, "questions": uniq_q}
    if _graph_cache is not None:
        try:
            _graph_cache.set(cache_key, payload, ttl=_GRAPH_TTL)
        except Exception:  # noqa: BLE001
            pass
    return payload


def list_entities_controller(entity_type: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
    """
    分页返回指定类型下的实体名称列表，用于 Entity Browser。
    """
    # 简单 label 清洗：只保留字母数字和下划线，避免注入
    safe_label = "".join(ch for ch in entity_type if ch.isalnum() or ch == "_")
    if not safe_label:
        return {"type": entity_type, "page": page, "size": size, "total": 0, "entities": []}

    skip = max(page - 1, 0) * size

    with graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
        # 总数
        count_cypher = f"""
        MATCH (n:`{safe_label}`)
        WHERE exists(n.name)
        RETURN count(n) AS cnt
        """
        total = session.run(count_cypher).single()["cnt"]

        if total == 0:
            return {"type": entity_type, "page": page, "size": size, "total": 0, "entities": []}

        # 当前页
        page_cypher = f"""
        MATCH (n:`{safe_label}`)
        WHERE exists(n.name)
        RETURN n.name AS name
        ORDER BY name
        SKIP $skip
        LIMIT $size
        """
        rows = session.run(page_cypher, skip=skip, size=size)
        entities = [rec["name"] for rec in rows]

    return {
        "type": entity_type,
        "page": page,
        "size": size,
        "total": total,
        "entities": entities,
    }

def subgraph_by_entity_controller(entity: str, limit: int = 200) -> Dict[str, List[Dict[str, Any]]]:
    """
    以给定实体名称为中心，返回其一阶邻居子图。
    这里假设节点上有 `name` 属性可用于匹配。
    """
    cypher = """
    MATCH (n {name: $name})-[r]-(m)
    RETURN
      id(n) AS center_id,
      labels(n) AS center_labels,
      properties(n) AS center_props,
      id(m) AS neighbor_id,
      labels(m) AS neighbor_labels,
      properties(m) AS neighbor_props,
      type(r) AS type,
      properties(r) AS rel_props
    LIMIT $limit
    """
    records = _run_cypher(cypher, {"name": entity, "limit": limit})

    if not records:
        return {"nodes": [], "edges": []}

    nodes: Dict[Any, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for rec in records:
        cid = rec["center_id"]
        nid = rec["neighbor_id"]
        if cid not in nodes:
            nodes[cid] = {
                "id": cid,
                "labels": rec.get("center_labels", []),
                "properties": rec.get("center_props", {}),
            }
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "labels": rec.get("neighbor_labels", []),
                "properties": rec.get("neighbor_props", {}),
            }
        edges.append(
            {
                "source": cid,
                "target": nid,
                "type": rec.get("type"),
                "properties": rec.get("rel_props", {}),
            }
        )

    return {"nodes": list(nodes.values()), "edges": edges}


def path_between_entities_controller(a: str, b: str, max_hops: int = 4) -> Dict[str, List[Dict[str, Any]]]:
    """
    使用 shortestPath 查找实体 a、b 之间的最短路径（最多若干跳）。
    """
    cypher = """
    MATCH p = shortestPath(
        (a {name: $a})-[*..$max_hops]-(b {name: $b})
    )
    RETURN p
    """
    records = _run_cypher(cypher, {"a": a, "b": b, "max_hops": max_hops})
    if not records:
        return {"nodes": [], "edges": []}

    nodes: Dict[Any, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for rec in records:
        path = rec["p"]
        for n in path.nodes:
            nid = n.id
            if nid not in nodes:
                nodes[nid] = {
                    "id": nid,
                    "labels": list(n.labels),
                    "properties": dict(n),
                }
        for r in path.relationships:
            edges.append(
                {
                    "source": r.start_node.id,
                    "target": r.end_node.id,
                    "type": r.type,
                    "properties": dict(r),
                }
            )

    return {"nodes": list(nodes.values()), "edges": edges}


def node_documents_controller(entity: str, limit: int = 10) -> Dict[str, List[Dict[str, Any]]]:
    """
    获取与给定实体相关的文档节点及片段，用于右侧文档面板。
    这里假设文档节点带有 label :Document，且有 file_name/text 等属性。
    """
    cypher = """
    MATCH (d:Document)-[r]->(e {name: $name})
    RETURN d
    LIMIT $limit
    """
    records = _run_cypher(cypher, {"name": entity, "limit": limit})
    docs: List[Dict[str, Any]] = []
    for rec in records:
        d = rec["d"]
        props = dict(d)
        docs.append(
            {
                "file": props.get("file_name") or props.get("title") or str(d.id),
                "text": props.get("text") or props.get("content") or "",
                "raw": props,
            }
        )
    return {"documents": docs}

