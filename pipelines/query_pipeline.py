from typing import Any, Dict, List

import asyncio
import logging

from api.deps import graph_engine, vector_engine


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
        # 显式模式优先
        if mode in ("vector", "graph", "hybrid"):
            return {
                "vector": "vector_only",
                "graph": "graph_only",
                "hybrid": "hybrid",
            }[mode]

        # 根据意图自动选择
        if intent == "greeting":
            return "graph_only"
        if intent == "relationship_query":
            return "graph_only"
        if intent == "document_search":
            return "vector_only"
        # 默认：事实问答走混合检索
        return "hybrid"

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
        # 默认优先使用图谱答案，不足时回退向量答案
        graph_resp = context.get("graph_response")
        vector_resp = context.get("vector_response")

        if graph_resp is not None and str(graph_resp).strip():
            answer = str(graph_resp)
            source_nodes = context.get("graph", [])
        elif vector_resp is not None:
            answer = str(vector_resp)
            source_nodes = context.get("vector", [])
        else:
            answer = ""
            source_nodes = []

        return {
            "answer": answer,
            "sources": [
                {"text": node.text[:500], "file": node.metadata.get("file_name", "Unknown")}
                for node in (source_nodes or [])
            ],
            "graph_context": [],
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

        intent = self.detect_query_intent(query)
        strategy = self.choose_strategy(intent, mode)
        logger.info("Detected intent=%s, strategy=%s", intent, strategy)

        # 纯问候意图可在上层处理，这里仍保留兜底路径
        if intent == "greeting":
            resp = self.graph_engine.llm.complete(
                f"用户向你打招呼说：'{query}'。请作为一个专业的知识库助手礼貌且简短地回复。"
            )
            return {"answer": str(resp), "sources": [], "graph_context": []}

        vector_resp = None
        graph_resp = None

        if strategy in ("vector_only", "hybrid"):
            vector_resp = self.vector_retrieval(query)

        if strategy in ("graph_only", "hybrid"):
            try:
                graph_resp = self.graph_retrieval(query)
            except Exception as e:  # noqa: BLE001
                logger.error("Graph retrieval failed: %s", e)
                if strategy == "graph_only":
                    raise

        ranked = self.rerank(vector_resp, graph_resp)
        context = self.compress_context(ranked)
        return self.llm_synthesis(query, context)


