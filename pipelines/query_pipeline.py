from typing import Any, Dict, List

import asyncio
import logging

from api.deps import graph_engine, vector_engine
from core.graph_traversal import GraphTraversalEngine, extract_triples
from pipelines.context_builder import ContextBuilder
from pipelines.prompt_builder import PromptBuilder
from pipelines.query_planner import QueryPlanner


def _ensure_event_loop() -> None:
    """确保当前线程上有一个打开的事件循环。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Closed event loop")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


logger = logging.getLogger(__name__)


class QueryPipeline:
    def __init__(self) -> None:
        self.graph_engine = graph_engine
        self.vector_engine = vector_engine
        self.planner = QueryPlanner()
        self.traversal_engine = GraphTraversalEngine(self.graph_engine)
        self.context_builder = ContextBuilder()
        self.prompt_builder = PromptBuilder()

    # ------------------------- Query understanding -------------------------
    def detect_query_intent(self, query: str) -> str:
        q = query.strip().lower()
        if not q:
            return "greeting"

        greetings = ["hi", "hello", "hey", "早上好", "下午好", "晚上好", "你好", "您好", "在吗"]
        if any(tok in q for tok in greetings):
            return "greeting"

        rel_keywords = ["关系", "related to", "relationship", "关联", "how are", "connection between"]
        if any(k in q for k in rel_keywords):
            return "relationship_query"

        doc_keywords = ["哪篇文档", "which document", "which file", "文档中", "文件中"]
        if any(k in q for k in doc_keywords):
            return "document_search"

        return "fact_lookup"

    def choose_strategy(self, intent: str, mode: str | None = None) -> str:
        """
        选择检索策略：
          - 若用户显式指定 vector/graph，则严格遵守；
          - 若用户指定 hybrid 或未指定，则根据意图自动选择，优先走「快路径」：
              * greeting            -> graph_only（简单问候，用主模型快速回一句）
              * relationship_query  -> graph_only（确实需要图）
              * document_search     -> vector_only（只查哪篇文档，向量足够）
              * fact_lookup         -> vector_only（默认事实问答优先走向量）
        """
        # 显式模式优先（vector / graph）
        if mode in ("vector", "graph"):
            return {
                "vector": "vector_only",
                "graph": "graph_only",
            }[mode]

        # hybrid 或 None 视为自动模式，根据意图选择
        if intent == "greeting":
            return "graph_only"
        if intent == "relationship_query":
            return "graph_only"
        if intent in ("document_search", "fact_lookup"):
            return "vector_only"

        # 兜底：未知意图仍走向量优先
        return "vector_only"

    # ------------------------- Retrieval layer -------------------------
    def vector_retrieval(self, query: str):
        qe = self.vector_engine.get_query_engine()
        return qe.query(query)

    def graph_retrieval(self, query: str):
        qe = self.graph_engine.get_query_engine()
        return qe.query(query)

    # ------------------------- Rerank & context building -------------------------
    def combine_context(self, vector_docs: Any, graph_nodes: Any) -> Dict[str, Any]:
        return {
            "vector": getattr(vector_docs, "source_nodes", []) if vector_docs is not None else [],
            "graph": getattr(graph_nodes, "source_nodes", []) if graph_nodes is not None else [],
        }

    def rerank(self, vector_docs: Any, graph_nodes: Any) -> Dict[str, Any]:
        """
        目前简单地把图与向量的 source_nodes 合并。
        后续可以在这里加入基于得分或多路召回的重排逻辑。
        """
        context = self.combine_context(vector_docs, graph_nodes)
        context["vector_response"] = vector_docs
        context["graph_response"] = graph_nodes
        return context

    def compress_context(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        对上下文做轻量压缩：目前只做截断，保留前若干条，以防上下文过长。
        """
        max_per_channel = 5
        vector_nodes = results.get("vector", []) or []
        graph_nodes = results.get("graph", []) or []
        results["vector"] = vector_nodes[:max_per_channel]
        results["graph"] = graph_nodes[:max_per_channel]
        return results

    # ------------------------- Answer synthesis -------------------------
    def llm_synthesis(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        graph_resp = context.get("graph_response")
        vector_resp = context.get("vector_response")

        # 若存在由 ContextBuilder 构建的 llm_context，则优先用 PromptBuilder+主 LLM 生成答案
        llm_context = context.get("llm_context") or ""
        if llm_context.strip():
            prompt = self.prompt_builder.build_prompt(query, llm_context)
            resp = self.graph_engine.llm.complete(prompt)
            answer = str(resp)
            # 仍然使用压缩后的 source_nodes 作为引用来源
            source_nodes = context.get("graph") or context.get("vector") or []
        else:
            # 默认优先使用图谱答案，不足时回退向量答案（保持旧行为）
            if graph_resp is not None and str(graph_resp).strip():
                answer = str(graph_resp)
                source_nodes = context.get("graph", [])
            elif vector_resp is not None:
                answer = str(vector_resp)
                source_nodes = context.get("vector", [])
            else:
                answer = ""
                source_nodes = []

        sources = [
            {"text": node.text[:500], "file": node.metadata.get("file_name", "Unknown")}
            for node in (source_nodes or [])
        ]

        return {
            "answer": answer,
            "sources": sources,
            "graph_context": [],
            "explanation": context.get("graph_explanation"),
            "graph_paths": context.get("graph_paths") or [],
        }

    # ------------------------- Orchestrator entrypoint -------------------------
    def run(self, query: str, mode: str = "hybrid") -> Dict[str, Any]:
        """
        GraphRAG v2 查询编排流程：
          1. 意图识别
          2. 选择检索策略
          3. 多路检索
          4. 重排与上下文压缩
          5. LLM 生成最终答案
        """
        _ensure_event_loop()

        logger.info("QueryPipeline running with mode=%s, query=%s", mode, query)

        # 新增：Query Planner 负责高层规划（intent / strategy / entities）
        plan = self.planner.plan(query)
        logger.info("Query plan: %s", plan)

        # 兼容旧模式参数：若用户显式传入 mode=vector/graph，则保持旧行为覆盖 planner 的 strategy
        intent = plan.get("intent") or self.detect_query_intent(query)
        if mode in ("vector", "graph"):
            strategy = self.choose_strategy(intent, mode)
        else:
            # 将 planner 的 strategy 映射回旧的检索策略空间
            planner_strategy = plan.get("strategy")
            if planner_strategy == "vector":
                strategy = "vector_only"
            elif planner_strategy in ("graph", "graph_traversal"):
                # graph_traversal 目前也先走 graph 查询引擎
                strategy = "graph_only"
            elif planner_strategy == "hybrid":
                strategy = "hybrid"
            elif planner_strategy == "llm_only":
                # 问候语等只需要 LLM 场景
                strategy = "llm_only"
            else:
                # 兜底：沿用旧逻辑
                intent = self.detect_query_intent(query)
                strategy = self.choose_strategy(intent, mode)

        logger.info("Detected intent=%s, strategy=%s", intent, strategy)

        # 纯问候意图可在上层处理，这里仍保留兜底路径
        if intent == "greeting" or strategy == "llm_only":
            resp = self.graph_engine.llm.complete(
                f"用户向你打招呼说：'{query}'。请作为一个专业的知识库助手礼貌且简短地回复。"
            )
            return {"answer": str(resp), "sources": [], "graph_context": []}

        vector_resp = None
        graph_resp = None
        traversal_nodes: List[Dict[str, Any]] = []
        traversal_edges: List[Dict[str, Any]] = []

        if strategy in ("vector_only", "hybrid"):
            vector_resp = self.vector_retrieval(query)

        if strategy in ("graph_only", "hybrid"):
            try:
                graph_resp = self.graph_retrieval(query)
            except Exception as e:  # noqa: BLE001
                logger.error("Graph retrieval failed: %s", e)
                if strategy == "graph_only":
                    raise

        # graph_traversal: 使用 GraphTraversalEngine 获取子图上下文
        if plan.get("strategy") == "graph_traversal":
            entities = plan.get("entities") or []
            merged_nodes: Dict[Any, Any] = {}
            merged_edges: List[Any] = []
            for ent in entities:
                subgraph = self.traversal_engine.traverse(ent, max_hops=2)
                for n in subgraph.get("nodes", []):
                    merged_nodes[n["id"]] = n
                merged_edges.extend(subgraph.get("edges", []))
            traversal_nodes = list(merged_nodes.values())
            traversal_edges = merged_edges
            logger.info(
                "Graph traversal context merged: entities=%s, nodes=%s, edges=%s",
                entities,
                len(traversal_nodes),
                len(traversal_edges),
            )

        # 从遍历结果中提取三元组，用于关系解释
        graph_paths: List[Dict[str, str]] = []
        if traversal_nodes and traversal_edges:
            graph_paths = extract_triples(traversal_nodes, traversal_edges)

        ranked = self.rerank(vector_resp, graph_resp)
        compact_context = self.compress_context(ranked)

        # 使用 ContextBuilder 生成供 LLM 使用的文本上下文，目前主要用于答案生成
        built_context_str = self.context_builder.build_context(
            query,
            vector_resp,
            graph_resp,
            traversal_nodes,
            traversal_edges,
        )
        logger.info(
            "Built LLM context: len=%s, traversal_nodes=%s, traversal_edges=%s",
            len(built_context_str),
            len(traversal_nodes),
            len(traversal_edges),
        )
        compact_context["llm_context"] = built_context_str

        # 将结构化的 graph_paths 挂到上下文中，供响应和未来前端使用
        compact_context["graph_paths"] = graph_paths
        # explanation 目前由主答案 prompt 隐式承担，这里保留字段以保持兼容
        compact_context["graph_explanation"] = None

        context = compact_context
        return self.llm_synthesis(query, context)


