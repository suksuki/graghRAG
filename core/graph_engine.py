"""
GraphEngine — Neo4j 知识图谱引擎

优化点：
  1. 图抽取使用专用小模型（EXTRACTION_MODEL），查询使用主模型（LLM_MODEL）
  2. 增量索引：跳过已写入 Neo4j 的文件
  3. 支持并发抽取（num_workers 可配置）
"""

import logging
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from llama_index.core import PropertyGraphIndex, Settings
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from configs.config import settings

logger = logging.getLogger(__name__)


class GraphEngine:
    def __init__(self):
        # 主模型：对话 / 查询
        self.llm = Ollama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.REQUEST_TIMEOUT
        )
        # 抽取模型：图谱实体关系抽取（用小模型，快很多）
        # 使用较短超时，避免单块卡住导致“图索引一直卡着”
        self.extraction_llm = Ollama(
            model=settings.EXTRACTION_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.EXTRACTION_TIMEOUT
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
    def create_index(self, nodes, num_workers: int = None, max_paths_per_chunk: int = 5):
        """
        用小模型对 nodes 进行实体关系抽取，写入 Neo4j。
        注意：每个 node（文本块）会调用一次 LLM，块多时耗时会明显长于向量化；属正常现象。
        - extraction_llm: 比主模型小，速度快
        - num_workers: 并发数（根据 GPU 显存调整，建议 1-4）
        - max_paths_per_chunk: 每块最多抽几条关系，越小单次 LLM 越快
        """
        from llama_index.core.indices.property_graph import SimpleLLMPathExtractor

        if not nodes:
            logger.info("No new nodes to index into Neo4j, skipping graph extraction.")
            return None

        if num_workers is None:
            num_workers = settings.EXTRACTION_NUM_WORKERS
        n = len(nodes)
        logger.info(
            f"Graph extraction starting: model={settings.EXTRACTION_MODEL}, "
            f"nodes={n}, workers={num_workers}, timeout={settings.EXTRACTION_TIMEOUT}s per request. "
            f"Each chunk triggers one LLM call — expect ~{n} calls, may take several minutes."
        )

        kg_extractor = SimpleLLMPathExtractor(
            llm=self.extraction_llm,
            max_paths_per_chunk=max_paths_per_chunk,
            num_workers=num_workers,
        )

        index = PropertyGraphIndex(
            nodes,
            property_graph_store=self.graph_store,
            kg_extractors=[kg_extractor],
            llm=self.llm,
            embed_model=self.embed_model,
            show_progress=True
        )
        return index

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
