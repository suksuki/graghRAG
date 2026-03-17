from fastapi import APIRouter, Query

from api.controllers.graph_controller import (
    list_nodes_controller,
    list_relations_controller,
    subgraph_by_entity_controller,
    path_between_entities_controller,
    node_documents_controller,
    graph_overview_controller,
    suggested_questions_controller,
    entity_types_controller,
    list_entities_controller,
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


@router.get("/overview")
def graph_overview():
    """
    图谱总览：节点/关系数量、按类型统计、代表实体列表。
    """
    return graph_overview_controller()


@router.get("/entity_types")
def entity_types():
    """
    返回实体类型列表，用于 Entity Browser 的类型选择。
    """
    return entity_types_controller()


@router.get("/suggested_questions")
def suggested_questions(limit: int = Query(10, ge=1, le=50)):
    """
    返回一组基于图关系自动生成的推荐问题，帮助用户了解可以问什么。
    """
    return suggested_questions_controller(limit=limit)


@router.get("/entities")
def list_entities(
    type: str = Query(..., description="实体类型（对应节点的第一个 label）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
):
    """
    分页返回指定类型的实体名称列表，用于 Entity Browser。
    """
    return list_entities_controller(entity_type=type, page=page, size=size)

