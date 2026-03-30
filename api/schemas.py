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
    """文档中心列表项（GET /knowledge/docs）。"""

    id: str
    name: str
    summary: str = ""
    entities: List[str] = []
    tags: List[str] = []
    keywords: List[str] = []
    topics: List[str] = []
    doc_type: str = ""
    uploaded_at: Optional[str] = None
    mtime: float = 0.0
    size: Optional[int] = None


class ProductDocListResponse(BaseModel):
    documents: List[ProductDocItem]


class DocRelationItem(BaseModel):
    source: str
    relation: str
    target: str
    kg_source: Optional[str] = Field(
        None,
        description="图边来源：llm / fallback / legacy；仅作辅助上下文，非摘要主证据。",
    )
    kg_confidence: Optional[float] = Field(
        None,
        description="边置信度；辅助展示与降权，不可替代 supporting_chunks。",
    )


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
    """
    POST /api/v1/hybrid-search — **Vector-first, graph-augmented**.

    Vector search is the **primary evidence** source; the graph **augments** context from seeds
    derived from chunks and metadata. Graph results are supporting signal, not a replacement for chunks.
    """

    query: str = Field(
        ...,
        min_length=1,
        description=(
            "User question or keywords. "
            "Hybrid retrieval: vector similarity is primary; graph expansion follows seed entities."
        ),
    )
    top_k: int = Field(
        5,
        ge=1,
        le=30,
        description="Number of vector chunks to retrieve (primary evidence).",
    )
    graph_expand_k: int = Field(
        20,
        ge=1,
        le=100,
        description="Max graph relationships to fetch after seeding from vector/metadata (augmentation).",
    )
    min_kg_conf: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum relationship kg_confidence for graph expansion; "
            "defaults to KG_MIN_EDGE_CONFIDENCE_FOR_QUERY when omitted."
        ),
    )
    include_fallback: bool = Field(
        False,
        description=(
            "If true, include low-confidence / lexical-fallback edges in graph expansion (debug or weak-data mode)."
        ),
    )


class HybridSearchResponse(BaseModel):
    """
    Hybrid retrieval response: **chunks carry primary evidence**; **relations are supporting context**.

    Do not treat graph-only rows as sufficient answers without vector-backed text.
    """

    query: str = Field(..., description="Echo of the submitted query.")
    results: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Ranked hits: items with type `chunk` (vector, primary) or `relation` (graph, augmentation). "
            "Graph triplets should be shown as supporting context alongside chunk text."
        ),
    )
    debug: Dict[str, Any] = Field(
        default_factory=dict,
        description="Telemetry: e.g. vector_hits, graph_nodes, graph_edges, seed_entities.",
    )


class EvidenceConflictItem(BaseModel):
    """Decision v1：两条 supporting_chunks 之间启发式检出的可能冲突（非裁决）。"""

    refs: List[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="一对 ref_index，与摘要中 [n] 一致",
    )
    type: str = Field(
        default="contradiction",
        description="当前仅为 contradiction（关键词子串启发式）",
    )


class DocumentInsightDecision(BaseModel):
    conflicts: List[EvidenceConflictItem] = Field(
        default_factory=list,
        description="未检出时为空列表",
    )
    support_groups: Optional[Dict[str, List[int]]] = Field(
        None,
        description="Decision v2：仅当 conflicts 非空时返回——按关键词粗分组的 ref_index；无冲突时为 null",
    )


class InsightEventIn(BaseModel):
    """POST /log — 前端认知摩擦埋点（schema 可演进）。"""

    event: str = Field(..., min_length=1, max_length=128)
    ts: int
    session_id: str = Field(..., min_length=1, max_length=160)
    doc_id: str = ""
    insight_id: Optional[str] = Field(None, max_length=256)
    payload: Optional[Dict[str, Any]] = None


class FrictionEvalRequest(BaseModel):
    """POST /telemetry/friction-eval — 按 session（及可选 doc）拉取埋点并输出 v3 候选。"""

    session_id: str = Field(..., min_length=1, max_length=160)
    doc_id: Optional[str] = Field(None, max_length=512)
    log_candidate: bool = Field(False, description="为 true 时若判定到摩擦则追加 friction_v3_candidates.jsonl")


class FrictionEvalResponse(BaseModel):
    friction_type: Optional[str] = Field(None, description="T1|T2|T3|T4|TB|TQ")
    suggested_v3: Optional[str] = Field(None, description="A|B|C|D")
    triggers_fired: List[str] = Field(default_factory=list)
    counts: Dict[str, Any] = Field(default_factory=dict)
    signals: Dict[str, Any] = Field(default_factory=dict)
    event_count: int = 0
    session_id: str = ""
    doc_id: str = ""


class DocumentInsightRequest(BaseModel):
    """
    POST /api/v1/insights/document — **DI-first**：摘要必须锚定在 `supporting_chunks`；
    `key_relations` 仅为辅助信号，不能替代片段证据。
    """

    query: str = Field(
        ...,
        min_length=1,
        description="问题或关注焦点；用于向量检索与 grounded 摘要。",
    )
    top_k: int = Field(5, ge=1, le=20, description="参与摘要的向量片段条数上限")
    doc_id: Optional[str] = Field(
        None,
        description="可选，限制为指定 file_name 的 chunk（与 metadata file_name 一致）",
    )
    include_graph_relations: bool = Field(
        True,
        description="是否附带图中与关键实体相关的关系（经 kg_confidence 过滤）",
    )


class DocumentStructuredEvidenceItem(BaseModel):
    role: str = Field(..., description="结构化预览中的角色/职能名。")
    persons: List[str] = Field(
        default_factory=list,
        description="与该角色关联的人名列表。",
    )
    ref_indices: List[int] = Field(
        default_factory=list,
        description="支撑该预览项的 supporting_chunks.ref_index 列表。",
    )
    file_names: List[str] = Field(
        default_factory=list,
        description="支撑该预览项的来源文件名列表。",
    )


class DocumentInsightResponse(BaseModel):
    answer: Optional[str] = Field(
        None,
        description="统一问答字段；与 summary 等价（向后兼容）。",
    )
    summary: str = Field(
        ...,
        description="仅基于 supporting_chunks 的 grounded 摘要；证据不足时会明确说明。",
    )
    source: Optional[str] = Field(
        None,
        description="回答来源：rag（基于文档内容分析）或 facts（基于文档结构解析）。",
    )
    key_entities: List[str] = Field(default_factory=list)
    key_relations: List[DocRelationItem] = Field(
        default_factory=list,
        description="图关系为辅助上下文，非摘要主证据。",
    )
    supporting_chunks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="向量检索片段；含 ref_index 与摘要中 [1]、[2] 引用一一对应。",
    )
    structured_evidence: List[DocumentStructuredEvidenceItem] = Field(
        default_factory=list,
        description="结构化预览项；由服务端从 supporting_chunks/facts 保守提取，并附带 provenance。",
    )
    insufficient_evidence: bool = Field(
        False,
        description="为 true 表示未检索到片段或无法据此作答",
    )
    decision: DocumentInsightDecision = Field(
        default_factory=DocumentInsightDecision,
        description="Decision：冲突标记 + 可选 support_groups，见 docs/DOCUMENT_INTELLIGENCE_DESIGN_DISCIPLINE.md",
    )
    debug: Dict[str, Any] = Field(default_factory=dict)


class CorpusInsightResponse(BaseModel):
    summary: str = ""
    top_topics: List[str] = []
    top_entities: List[str] = []
    key_insights: List[str] = []
    closing_takeaway: str = Field("", description="置于关键洞察末尾的一句话总结，便于记忆")
    top_keywords: List[str] = []
    docs_analyzed: int = Field(0, description="实际参与聚合的、含 di_* 的文档数")
