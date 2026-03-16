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

