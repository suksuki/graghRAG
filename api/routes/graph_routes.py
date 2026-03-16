from fastapi import APIRouter, Query

from api.controllers.graph_controller import (
    list_nodes_controller,
    list_relations_controller,
    subgraph_by_entity_controller,
    path_between_entities_controller,
    node_documents_controller,
)

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/nodes")
def list_nodes(limit: int = Query(100, ge=1, le=1000)):
    """
    返回图中的部分节点，用于 Graph Explorer 初始展示。
    """
    return list_nodes_controller(limit=limit)


@router.get("/relations")
def list_relations(limit: int = Query(100, ge=1, le=1000)):
    """
    返回图中的部分关系及其节点。
    """
    return list_relations_controller(limit=limit)


@router.get("/subgraph")
def subgraph(entity: str = Query(..., description="中心实体名称（节点的 name 属性）"), limit: int = Query(200, ge=1, le=2000)):
    """
    以给定实体（name 属性）为中心，返回其一阶邻居子图。
    """
    return subgraph_by_entity_controller(entity=entity, limit=limit)


@router.get("/path")
def graph_path(
    a: str = Query(..., description="起点实体名称（name 属性）"),
    b: str = Query(..., description="终点实体名称（name 属性）"),
    max_hops: int = Query(4, ge=1, le=8),
):
    """
    查找实体 a 和 b 之间的最短路径。
    """
    return path_between_entities_controller(a=a, b=b, max_hops=max_hops)


@router.get("/node_documents")
def node_documents(entity: str = Query(..., description="实体名称（name 属性）"), limit: int = Query(10, ge=1, le=50)):
    """
    获取与给定实体相关的文档及文本片段，用于前端文档侧边栏。
    """
    return node_documents_controller(entity=entity, limit=limit)

