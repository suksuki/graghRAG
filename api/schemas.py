from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class QueryRequest(BaseModel):
    """查询请求体."""

    query: str
    mode: str = "hybrid"  # hybrid, graph, vector


class QueryResponse(BaseModel):
    """查询响应体."""

    answer: str
    sources: List[Dict[str, Any]]
    graph_context: Optional[List[str]] = None
    # 可选：pipeline 各阶段耗时（ms），便于在 UI 显示或排查瓶颈
    pipeline_latency_ms: Optional[Dict[str, Any]] = None
    # GraphRAG 可视化字段（可选）
    graph: Optional[Dict[str, Any]] = None
    debug: Optional[Dict[str, Any]] = None
    lang_ui: Optional[str] = None
    lang_detected: Optional[str] = None
    lang_final: Optional[str] = None
    suggest_switch: Optional[bool] = None


class TestRequest(BaseModel):
    """连接测试请求体."""

    type: Optional[str] = None
    url: Optional[str] = None


# --- 知识产品化 P0（文档中心 / 搜索 / 实体档案）---


class ProductDocItem(BaseModel):
    """文档中心列表项（GET /docs）。"""

    id: str
    name: str
    summary: str = ""
    entities: List[str] = []
    tags: List[str] = []
    keywords: List[str] = []
    topics: List[str] = []
    doc_type: str = ""


class ProductDocListResponse(BaseModel):
    documents: List[ProductDocItem]


class DocRelationItem(BaseModel):
    source: str
    relation: str
    target: str


class ProductDocDetailResponse(BaseModel):
    id: str
    doc_id: str
    name: str
    insight: str = ""
    summary: str = ""
    entities: List[str] = []
    tags: List[str] = []
    relations: List[DocRelationItem] = []
    related_snippets: List[str] = []
    size: Optional[int] = None
    uploaded_at: Optional[str] = None
    keywords: List[str] = []
    topics: List[str] = []
    key_points: List[str] = []
    doc_type: str = ""
    intelligence_entities: List[str] = []


class SearchChunkResult(BaseModel):
    doc: str
    snippet: str


class SearchChunksResponse(BaseModel):
    query: str
    results: List[SearchChunkResult]


class EntityProfileResponse(BaseModel):
    entity: str
    insight: str = ""
    products: List[str] = []
    domains: List[str] = []
    documents: List[str] = []
    weak_profile: bool = False


class CorpusInsightRequest(BaseModel):
    """POST /insights/corpus — 跨文档洞察（聚合 di_*）。"""

    top_k_docs: int = Field(20, ge=1, le=50, description="扫描最近修改的文档数量上限")


class HybridSearchRequest(BaseModel):
    """POST /api/v1/hybrid-search — Vector-first, graph-augmented（向量主路径，图扩展增强）。"""

    query: str = Field(..., min_length=1, description="用户问题或关键词")
    top_k: int = Field(5, ge=1, le=30, description="向量召回条数")
    graph_expand_k: int = Field(20, ge=1, le=100, description="图扩展关系条数上限")
    min_kg_conf: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="关系最小 kg_confidence；默认取配置 KG_MIN_EDGE_CONFIDENCE_FOR_QUERY",
    )
    include_fallback: bool = Field(
        False,
        description="为 true 时图扩展包含低置信度 / fallback 边（min 视为 0）",
    )


class HybridSearchResponse(BaseModel):
    query: str
    results: List[Dict[str, Any]]
    debug: Dict[str, Any] = Field(default_factory=dict)


class CorpusInsightResponse(BaseModel):
    summary: str = ""
    top_topics: List[str] = []
    top_entities: List[str] = []
    key_insights: List[str] = []
    closing_takeaway: str = Field("", description="置于关键洞察末尾的一句话总结，便于记忆")
    top_keywords: List[str] = []
    docs_analyzed: int = Field(0, description="实际参与聚合的、含 di_* 的文档数")

