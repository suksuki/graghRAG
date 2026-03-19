"""
GraphEngine — Neo4j 知识图谱引擎

优化点：
  1. 图抽取使用专用小模型（EXTRACTION_MODEL），查询使用主模型（LLM_MODEL）
  2. 增量索引：跳过已写入 Neo4j 的文件
  3. 支持并发抽取（num_workers 可配置）
"""

import logging
import re
from typing import Any, Iterable, Optional
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from llama_index.core import PropertyGraphIndex, Settings
from llama_index.core.indices.property_graph.transformations import SimpleLLMPathExtractor
from llama_index.core.prompts import PromptTemplate
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from configs.config import settings

logger = logging.getLogger(__name__)


class GraphEngine:
    def __init__(self):
        # 主模型：对话 / 查询。显式 context_window 避免 client.show() 冷启动；thinking=False 去掉思考输出以降低延迟。
        _ctx = getattr(settings, "LLM_NUM_CTX", None) or 2048
        _num_predict = getattr(settings, "LLM_NUM_PREDICT", None) or 64
        _ollama_kw = {
            "request_timeout": settings.REQUEST_TIMEOUT,
            "context_window": _ctx,
            "additional_kwargs": {
                "num_ctx": _ctx,
                "num_predict": _num_predict,
                "temperature": 0,
            },
            "keep_alive": "30m",
            "thinking": False,  # 禁用 thinking 输出，首字更快、无干扰
        }
        self.llm = Ollama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            **_ollama_kw
        )
        # 轻量抽取模型：严格限制 token，避免 ingestion 阻塞
        self.extraction_llm = Ollama(
            model=settings.EXTRACTION_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.EXTRACTION_TIMEOUT,
            context_window=1024,
            additional_kwargs={"num_ctx": 1024, "num_predict": 32, "temperature": 0},
            keep_alive="30m",
            thinking=False,
        )
        self.embed_model = OllamaEmbedding(
            model_name=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.REQUEST_TIMEOUT
        )

        Settings.llm = self.llm
        Settings.embed_model = self.embed_model

        self.graph_store = Neo4jPropertyGraphStore(
            username=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
            url=settings.NEO4J_URI,
        )

    # ------------------------------------------------------------------
    # 增量索引：获取 Neo4j 中已有的文件名集合
    # ------------------------------------------------------------------
    def get_indexed_files(self) -> set:
        """返回 Neo4j 中已收录的文件名集合，用于跳过已处理文件。"""
        try:
            with self.graph_store._driver.session() as session:
                result = session.run(
                    "MATCH (n) WHERE n.file_name IS NOT NULL "
                    "RETURN DISTINCT n.file_name AS fn"
                )
                return {record["fn"] for record in result}
        except Exception as e:
            logger.warning(f"Could not query indexed files from Neo4j: {e}")
            return set()

    # ------------------------------------------------------------------
    # 图索引构建
    # ------------------------------------------------------------------
    def _score_chunk_text(self, text: str) -> int:
        t = (text or "").strip()
        if not t:
            return 0
        s = 0
        if any(k in t for k in ("产品", "平台", "系统")):
            s += 2
        if re.search(r"\b[A-Za-z]{3,}\b", t):
            s += 2
        if any(k in t for k in ("应用", "行业", "金融", "政府")):
            s += 1
        if len(t) > 50:
            s += 1
        return s

    def _select_high_value_nodes(self, nodes: list[Any], top_k: int = 5) -> list[Any]:
        scored: list[tuple[int, Any]] = []
        seen: set[str] = set()
        for node in nodes:
            text = (getattr(node, "text", "") or "").strip()
            if not text:
                continue
            # 去重：对前缀做归一化，避免重复页头/模板块反复送 LLM
            key = re.sub(r"\s+", " ", text[:80]).lower()
            if key in seen:
                continue
            seen.add(key)
            scored.append((self._score_chunk_text(text), node))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:top_k]]

    def create_index(self, nodes, num_workers: int = 1, max_paths_per_chunk: int = 2):
        """
        受控 LLM 抽取（轻量配置）写入 Neo4j。
        - num_workers 固定 1
        - max_paths_per_chunk 固定 2
        """
        if not nodes:
            logger.info("No new nodes to index into Neo4j, skipping graph extraction.")
            print(">>> [GRAPH] create_index called with 0 nodes, skip.")
            return None

        n = len(nodes)
        print(f">>> [GRAPH] create_index received nodes: {n}")
        logger.info(
            "Graph ingestion starting (LLM-LIGHT): nodes=%s, workers=1, max_paths_per_chunk=2",
            n,
        )
        nodes = self._select_high_value_nodes(list(nodes), top_k=5)
        logger.info("Graph high-value node selection: selected=%s", len(nodes))

        # Neo4j property graph 不接受嵌套 map 作为属性；仅保留稳定且原子化的 metadata
        safe_nodes = []
        for node in nodes:
            md = getattr(node, "metadata", {}) or {}
            safe_md = {}
            for k in ("file_name", "doc_id", "source"):
                v = md.get(k)
                if isinstance(v, (str, int, float, bool)) and v is not None:
                    safe_md[k] = v
            try:
                node.metadata = safe_md
            except Exception:  # noqa: BLE001
                pass
            safe_nodes.append(node)

        extract_prompt = PromptTemplate(
            "Extract concise knowledge triplets from text.\n\n"
            "Entities:\n"
            "- Company\n"
            "- Product / System\n"
            "- Industry / Domain\n\n"
            "Relations:\n"
            "- PROVIDES\n"
            "- APPLIES_TO\n\n"
            "Rules:\n"
            "- Only explicit facts\n"
            "- No hallucination\n"
            "- Keep at most 2 triplets per chunk\n\n"
            "Text:\n"
            "{text}\n"
        )

        kg_extractor = SimpleLLMPathExtractor(
            llm=self.extraction_llm,
            extract_prompt=extract_prompt,
            max_paths_per_chunk=2,
            num_workers=1,
        )

        PropertyGraphIndex(
            nodes=safe_nodes,
            property_graph_store=self.graph_store,
            kg_extractors=[kg_extractor],
            llm=self.extraction_llm,
            embed_model=self.embed_model,
            show_progress=False,
        )

        # file marker for incremental graph ingestion
        indexed_files: set[str] = set()
        for node in safe_nodes:
            md = getattr(node, "metadata", {}) or {}
            fn = str(md.get("file_name") or "").strip()
            if fn:
                indexed_files.add(fn)
        if indexed_files:
            with self.graph_store._driver.session() as session:  # type: ignore[attr-defined]
                for fn in indexed_files:
                    session.run(
                        """
                        MERGE (f:IngestedFile {file_name: $fn})
                        SET f.file_name = $fn
                        """,
                        fn=fn,
                    )
        logger.info("Graph ingestion done (LLM-LIGHT): file_markers=%s", len(indexed_files))

        # 调试：写入后统计一次节点数量
        try:
            with self.graph_store._driver.session() as session:  # type: ignore[attr-defined]
                res = session.run("MATCH (n) RETURN count(n) AS cnt")
                cnt = res.single()["cnt"]
                print(f">>> [GRAPH] Neo4j node_count after write: {cnt}")
        except Exception as e:  # noqa: BLE001
            print(">>> [ERROR] Neo4j count failed:", e)
            logger.error("Failed to count nodes after graph write: %s", e)

        return None

    # ------------------------------------------------------------------
    # 删除文档
    # ------------------------------------------------------------------
    def delete_document(self, filename: str) -> int:
        """从 Neo4j 删除与指定文件相关的所有节点。"""
        query = "MATCH (n) WHERE n.file_name = $filename DETACH DELETE n"
        try:
            with self.graph_store._driver.session() as session:
                result = session.run(query, filename=filename)
                summary = result.consume()
                deleted = summary.counters.nodes_deleted
                logger.info(f"Deleted {deleted} Neo4j nodes for file '{filename}'")
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete graph nodes for '{filename}': {e}")
            return 0

    # ------------------------------------------------------------------
    # 查询引擎
    # ------------------------------------------------------------------
    def get_query_engine(self):
        """返回图查询引擎（使用主模型）。"""
        index = PropertyGraphIndex.from_existing(
            property_graph_store=self.graph_store,
            llm=self.llm,
            embed_model=self.embed_model,
        )

        from llama_index.core.indices.property_graph.sub_retrievers.vector import VectorContextRetriever
        vector_retriever = VectorContextRetriever(
            index.property_graph_store,
            embed_model=self.embed_model,
            include_text=True,
            similarity_top_k=5
        )

        return index.as_query_engine(sub_retrievers=[vector_retriever])
