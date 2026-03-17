import logging
from typing import Any, Dict, List

from core.graph_engine import GraphEngine


logger = logging.getLogger(__name__)


class GraphTraversalEngine:
    """
    简单的图遍历引擎：
    - 使用 Neo4j shortest/expanded 路径查询
    - 返回标准化的 nodes / edges 结构，供上层作为图上下文使用
    """

    def __init__(self, graph_engine: GraphEngine) -> None:
        self._driver = graph_engine.graph_store._driver  # type: ignore[attr-defined]

    def traverse(self, entity: str, max_hops: int = 2) -> Dict[str, List[Dict[str, Any]]]:
        """
        以给定实体 name 为起点，做 1..max_hops 跳的无向遍历。
        """
        if not entity:
            return {"nodes": [], "edges": []}

        cypher = """
        MATCH p = (a {name: $name})-[*1..$max_hops]-(b)
        RETURN p
        LIMIT 200
        """
        logger.info("Graph traversal start: entity=%s, hops=%s", entity, max_hops)

        MAX_TRAVERSAL_NODES = 50
        MAX_TRAVERSAL_EDGES = 100

        with self._driver.session() as session:
            records = list(session.run(cypher, name=entity, max_hops=max_hops))

        if not records:
            logger.info("Graph traversal result: entity=%s, hops=%s, nodes=0, edges=0", entity, max_hops)
            return {"nodes": [], "edges": []}

        nodes: Dict[Any, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        for rec in records:
            if len(nodes) >= MAX_TRAVERSAL_NODES or len(edges) >= MAX_TRAVERSAL_EDGES:
                break
            path = rec["p"]
            for n in path.nodes:
                if len(nodes) >= MAX_TRAVERSAL_NODES:
                    break
                nid = n.id
                if nid not in nodes:
                    nodes[nid] = {
                        "id": nid,
                        "labels": list(n.labels),
                        "properties": dict(n),
                    }
            for r in path.relationships:
                if len(edges) >= MAX_TRAVERSAL_EDGES:
                    break
                edges.append(
                    {
                        "source": r.start_node.id,
                        "target": r.end_node.id,
                        "type": r.type,
                        "properties": dict(r),
                    }
                )

        logger.info(
            "Graph traversal result: entity=%s, hops=%s, nodes=%s, edges=%s",
            entity,
            max_hops,
            len(nodes),
            len(edges),
        )
        return {"nodes": list(nodes.values()), "edges": edges}


def extract_triples(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    从遍历得到的 nodes/edges 中提取简单的三元组字符串：
    \"Source -> RELATION -> Target\"。
    """
    triples: List[Dict[str, str]] = []
    node_map: Dict[str, Dict[str, Any]] = {str(n["id"]): n for n in nodes}
    seen: set[str] = set()
    MAX_TRIPLES = 20

    for e in edges:
        if len(triples) >= MAX_TRIPLES:
            break
        source = node_map.get(str(e.get("source")))
        target = node_map.get(str(e.get("target")))
        if not source or not target:
            continue

        s_props = source.get("properties", {}) or {}
        t_props = target.get("properties", {}) or {}
        s_name = s_props.get("name")
        t_name = t_props.get("name")
        rel = e.get("type")

        if not s_name or not t_name or not rel:
            continue

        key = f"{s_name}::{rel}::{t_name}"
        if key in seen:
            continue
        seen.add(key)
        triples.append({"source": str(s_name), "relation": str(rel), "target": str(t_name)})

    return triples

