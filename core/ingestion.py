"""
SMEIngestor — 文档摄取引擎

优化点：
  1. 增量索引：已写入 Neo4j / 向量库的文件自动跳过
  2. 向量写入和图索引分别做增量检查（互相独立）
"""

import os
import logging
import psycopg2
import nest_asyncio

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter

from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine
from configs.config import settings

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_vector_indexed_files(vector_engine: VectorEngine) -> set:
    """查询向量表，返回已收录的文件名集合。"""
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB
        )
        cur = conn.cursor()
        cur.execute(
            f"SELECT DISTINCT (metadata_ ->> 'file_name') "
            f"FROM {vector_engine.full_table_name} "
            f"WHERE metadata_ ->> 'file_name' IS NOT NULL"
        )
        result = {row[0] for row in cur.fetchall()}
        conn.close()
        return result
    except Exception as e:
        logger.warning(f"Could not query vector-indexed files: {e}")
        return set()


class SMEIngestor:
    def __init__(self):
        self.graph_engine = GraphEngine()
        self.vector_engine = VectorEngine()
        self.splitter = SentenceSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )

    def ingest_data(self, directory_path: str = None, progress_callback=None):
        """
        增量摄取：已索引的文件跳过，只处理新文件。
        向量写入和图索引分别独立判断，互不干扰。
        """
        def update(msg, pct, graph_done=None, graph_total=None, files_in_batch=None, file_names=None):
            if progress_callback:
                progress_callback(msg, pct, graph_done=graph_done, graph_total=graph_total, files_in_batch=files_in_batch, file_names=file_names)

        path = directory_path or settings.DATA_RAW_DIR

        if not os.path.exists(path) or not os.listdir(path):
            logger.warning(f"No files found in {path}")
            return 0, 0

        logger.info(f"Starting ingestion from {path}")
        update("Scanning directory...", 5)

        # ── 1. 查询已收录文件 ─────────────────────────────────────────
        graph_indexed = self.graph_engine.get_indexed_files()     # Neo4j 已有
        vector_indexed = _get_vector_indexed_files(self.vector_engine)  # 向量库已有
        logger.info(
            f"Already indexed: {len(graph_indexed)} in Neo4j, "
            f"{len(vector_indexed)} in vector store"
        )

        # ── 2. 加载全部文档 ───────────────────────────────────────────
        # 与上传白名单保持一致（见 api.utils.ALLOWED_EXTENSIONS）
        all_files = [
            f
            for f in os.listdir(path)
            if os.path.splitext(f)[1].lower()
            in {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".jpg", ".png", ".jpeg", ".xdmp"}
        ]

        # 需要写向量的新文件
        new_for_vector = [f for f in all_files if f not in vector_indexed]
        # 需要写图索引的新文件
        new_for_graph  = [f for f in all_files if f not in graph_indexed]

        logger.info(
            f"New files: {len(new_for_vector)} for vector, "
            f"{len(new_for_graph)} for graph"
        )

        if not new_for_vector and not new_for_graph:
            logger.info("All files already fully indexed. Nothing to do.")
            update("All files already indexed (100%)", 100)
            return 0, 0

        # 本批要处理的文件列表（用于界面展示）
        files_to_load = list(set(new_for_vector) | set(new_for_graph))
        update(
            f"Loading {len(files_to_load)} file(s)... (10%)",
            10,
            files_in_batch=len(files_to_load),
            file_names=files_to_load,
        )

        # 读取需要处理的文件
        reader = SimpleDirectoryReader(
            input_files=[os.path.join(path, f) for f in files_to_load]
        )
        documents = reader.load_data()
        logger.info(f"Loaded {len(documents)} document objects from {len(files_to_load)} files")
        update(f"Loaded {len(documents)} docs, splitting... (20%)", 20)

        all_nodes = self.splitter.get_nodes_from_documents(documents)
        logger.info(f"Split into {len(all_nodes)} total nodes")
        update(f"Split into {len(all_nodes)} chunks (25%)", 25)

        # ── 3. 向量写入（只处理新文件的 nodes）──────────────────────
        vector_nodes = [
            n for n in all_nodes
            if n.metadata.get("file_name") in new_for_vector
        ]
        num_vector = len(vector_nodes)
        if vector_nodes:
            logger.info(f"Inserting {num_vector} nodes into vector store...")
            update(f"Writing vectors: 0/{num_vector} (30%)", 30)
            self.vector_engine.add_documents(vector_nodes)
            update(f"Vector store done: {num_vector}/{num_vector} (55%)", 55)
            logger.info("Vector store update complete.")
        else:
            logger.info("Vector store: no new nodes, skipping.")
            update("Vector store done (no new).", 55)

        # ── 4. 图索引（只处理新文件的 nodes，按批更新进度）────────────
        graph_nodes = [
            n for n in all_nodes
            if n.metadata.get("file_name") in new_for_graph
        ]
        if graph_nodes:
            max_graph = settings.GRAPH_MAX_NODES
            if max_graph and len(graph_nodes) > max_graph:
                graph_nodes = graph_nodes[:max_graph]
                logger.info(
                    f"Graph limited to first {max_graph} chunks (GRAPH_MAX_NODES) to speed up indexing."
                )
            num_graph = len(graph_nodes)
            logger.info(
                f"Building graph index for {num_graph} nodes using '{settings.EXTRACTION_MODEL}'."
            )
            # 按批处理并更新进度：55%～95% 留给图索引，每批完成后推进
            batch_size = max(1, min(5, num_graph // 6))  # 约 6～12 次进度更新
            graph_pct_start = 55
            graph_pct_range = 40  # 55 -> 95
            update(f"Graph indexing: 0/{num_graph} chunks (55%)", graph_pct_start, graph_done=0, graph_total=num_graph)
            for i in range(0, num_graph, batch_size):
                batch = graph_nodes[i : i + batch_size]
                self.graph_engine.create_index(batch)
                done = min(i + len(batch), num_graph)
                pct = graph_pct_start + int(graph_pct_range * done / num_graph)
                pct = min(pct, 95)
                update(f"Graph indexing: {done}/{num_graph} chunks ({pct}%)", pct, graph_done=done, graph_total=num_graph)
            logger.info("Graph index update complete.")
        else:
            logger.info("Graph index: no new nodes, skipping.")

        logger.info("Ingestion completed successfully.")
        update("Knowledge processing completed! (100%)", 100)
        return len(documents), len(all_nodes)


if __name__ == "__main__":
    ingestor = SMEIngestor()
    ingestor.ingest_data()
