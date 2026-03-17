import logging
from typing import Any, Dict, List

from api.deps import graph_engine

logger = logging.getLogger(__name__)


def _format_node(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": record["id"],
        "labels": record.get("labels", []),
        "properties": record.get("properties", {}),
    }


def _run_cypher(query: str, params: Dict[str, Any] | None = None):
    """Helper to run a Cypher query via the shared GraphEngine driver."""
    params = params or {}
    with graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
        return list(session.run(query, **params))


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
    with graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
        # 总节点数
        node_count_result = session.run("MATCH (n) RETURN count(n) AS cnt")
        overview["node_count"] = node_count_result.single()["cnt"]

        # 总关系数
        edge_count_result = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
        overview["edge_count"] = edge_count_result.single()["cnt"]

        # 按 label 统计
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

        # 代表实体（有 name 的节点）
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


def suggested_questions_controller(limit: int = 10) -> Dict[str, List[str]]:
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
    for rec in records:
        a_name = rec.get("a_name")
        b_name = rec.get("b_name")
        if not a_name or not b_name:
            continue
        q = f"How is {a_name} related to {b_name}?"
        questions.append(q)

    # 去重
    seen = set()
    uniq: List[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            uniq.append(q)

    return {"questions": uniq}


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

