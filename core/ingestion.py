"""
SMEIngestor — 文档摄取引擎

优化点：
  1. 增量索引：已写入 Neo4j / 向量库的文件自动跳过
  2. 向量写入和图索引分别做增量检查（互相独立）
"""

import hashlib
import os
import logging
import time
import psycopg2
import nest_asyncio
import signal
from contextlib import contextmanager

from llama_index.core.node_parser import SentenceSplitter

from core.document_loader import DocumentLoader, SUPPORTED_EXTENSIONS
from core.document_intelligence import (
    apply_intelligence_to_file_nodes,
    chunks_text_for_intelligence,
    extract_document_intelligence,
)
from core.person_entity_store import (
    extract_person_entities_from_text,
    upsert_person_entities,
)
from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine
from configs.config import settings

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@contextmanager
def _time_limit(seconds: int):
    def _handle_timeout(signum, frame):  # noqa: ANN001
        raise TimeoutError(f"operation timed out after {seconds}s")

    if seconds <= 0:
        yield
        return
    prev_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)


def _file_sha256(filepath: str) -> str:
    """磁盘文件内容 SHA256（hex），用于 IngestedFile.content_hash 版本感知。"""
    h = hashlib.sha256()
    with open(filepath, "rb") as bf:
        for chunk in iter(lambda: bf.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    def __init__(self, graph_engine: GraphEngine | None = None, vector_engine: VectorEngine | None = None):
        self.graph_engine = graph_engine or GraphEngine()
        self.vector_engine = vector_engine or VectorEngine()
        self.document_loader = DocumentLoader()
        self.splitter = SentenceSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )

    def ingest_data(self, directory_path: str = None, progress_callback=None):
        """
        增量摄取：已索引的文件跳过，只处理新文件。
        向量写入和图索引分别独立判断，互不干扰。
        """
        print(">>> [INGEST] start ingest_data")

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
        graph_state = self.graph_engine.get_graph_ingest_state()
        vector_indexed = _get_vector_indexed_files(self.vector_engine)  # 向量库已有
        logger.info(
            f"Already indexed: {len(graph_state)} graph marker(s) in Neo4j, "
            f"{len(vector_indexed)} in vector store"
        )

        # ── 2. 加载全部文档 ───────────────────────────────────────────
        # 与上传白名单保持一致（见 api.utils.ALLOWED_EXTENSIONS）
        all_files = [
            f
            for f in os.listdir(path)
            if os.path.splitext(f)[1].lower()
            in SUPPORTED_EXTENSIONS
        ]

        def _needs_graph_ingest(fn: str) -> bool:
            """无 IngestedFile、或 content_hash 与磁盘不一致时需建图；无 hash 的旧节点视为已建图（兼容）。"""
            fullpath = os.path.join(path, fn)
            if not os.path.isfile(fullpath):
                return False
            if fn not in graph_state:
                return True
            stored = graph_state[fn]
            if stored is None:
                return False
            try:
                return _file_sha256(fullpath) != stored
            except OSError as e:
                logger.warning("Could not hash file for graph incremental: %s (%s)", fullpath, e)
                return True

        # 需要写向量的新文件
        new_for_vector = [f for f in all_files if f not in vector_indexed]
        # 图：无标记、或文件内容变更（content_hash 不一致）
        new_for_graph = [f for f in all_files if _needs_graph_ingest(f)]

        logger.info(
            f"New files: {len(new_for_vector)} for vector, "
            f"{len(new_for_graph)} for graph"
        )
        if new_for_graph:
            logger.info("Graph incremental file list (new_for_graph): %s", new_for_graph)

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

        input_files = [os.path.join(path, f) for f in files_to_load]
        documents = self.document_loader.load_many(input_files)
        logger.info(f"Loaded {len(documents)} document objects from {len(files_to_load)} files")
        update(f"Loaded {len(documents)} docs, splitting... (20%)", 20)

        all_nodes = self.splitter.get_nodes_from_documents(documents)
        logger.info(f"Split into {len(all_nodes)} total nodes")
        update(f"Split into {len(all_nodes)} chunks (25%)", 25)

        # 为每个 chunk 挂上 content_sha256，供 Neo4j :IngestedFile 版本感知
        disk_hashes: dict[str, str] = {}
        for fname in all_files:
            fp = os.path.join(path, fname)
            if os.path.isfile(fp):
                try:
                    disk_hashes[fname] = _file_sha256(fp)
                except OSError as e:
                    logger.warning("SHA256 skipped for %s: %s", fp, e)
        for node in all_nodes:
            fn = node.metadata.get("file_name")
            if isinstance(fn, str) and fn in disk_hashes:
                node.metadata["content_sha256"] = disk_hashes[fn]

        # ── 2b. Document Intelligence（仅新向量文件，前 N chunk → LLM JSON，写入各 chunk metadata）─
        di_lang = settings.DOC_INTEL_LANG or "zh"
        for fname in new_for_vector:
            sample = chunks_text_for_intelligence(all_nodes, fname, max_chunks=3)
            if not sample.strip():
                continue
            h = disk_hashes.get(fname, "")
            try:
                intel = extract_document_intelligence(
                    sample,
                    lang=di_lang,
                    llm=self.graph_engine.llm,
                    file_name=fname,
                    content_sha256=h,
                )
                apply_intelligence_to_file_nodes(all_nodes, fname, intel)
                logger.info("Document intelligence applied for %s", fname)
            except Exception as e:  # noqa: BLE001
                logger.warning("Document intelligence skipped for %s: %s", fname, e)

        # ── 2c. Person Entities（最小结构：person/title/projects/source_doc）────────
        for fname in new_for_vector:
            sample = chunks_text_for_intelligence(all_nodes, fname, max_chunks=6)
            if not sample.strip():
                continue
            try:
                logger.info(
                    "[PersonExtract] input_head file=%s text=%s",
                    fname,
                    sample[:200].replace("\n", " "),
                )
                entities = extract_person_entities_from_text(
                    text=sample,
                    llm=self.graph_engine.llm,
                    file_name=fname,
                )
                logger.info("[PersonExtract] result_json file=%s rows=%s", fname, entities)
                inserted_rows = 0
                if entities:
                    inserted_rows = upsert_person_entities(fname, entities)
                    logger.info("Person entities upserted for %s: %s", fname, inserted_rows)
                logger.info(
                    "[PersonExtract] inserted_rows file=%s inserted_rows=%s",
                    fname,
                    inserted_rows,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Person entities skipped for %s: %s", fname, e)

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
            mg = getattr(settings, "GRAPH_MAX_NODES", 30)
            if mg == 0:
                max_graph = len(graph_nodes)
            else:
                max_graph = min(mg or 30, len(graph_nodes))
            if len(graph_nodes) > max_graph:
                graph_nodes = graph_nodes[:max_graph]
                logger.info(
                    "Graph limited to first %s chunks (GRAPH_MAX_NODES=%s).",
                    max_graph,
                    mg,
                )
            print(f">>> [INGEST] graph_nodes count: {len(graph_nodes)}")
            num_graph = len(graph_nodes)
            logger.info(
                f"Building graph index for {num_graph} nodes using light LLM extractor."
            )
            batch_size = 1
            total_batches = (num_graph + batch_size - 1) // batch_size
            graph_pct_start = 55
            graph_pct_range = 40
            success_batches = 0
            failed_batches = 0
            update(f"Graph indexing: 0/{num_graph} chunks (55%)", graph_pct_start, graph_done=0, graph_total=num_graph)
            t_graph_start = time.perf_counter()
            for i in range(0, num_graph, batch_size):
                batch = graph_nodes[i : i + batch_size]
                batch_no = (i // batch_size) + 1
                print(f">>> [GRAPH] batch {batch_no} / {total_batches}")
                try:
                    update(
                        f"Graph indexing batch {batch_no}/{total_batches}, attempt 1...",
                        graph_pct_start + int(graph_pct_range * i / max(1, num_graph)),
                        graph_done=i,
                        graph_total=num_graph,
                    )
                    # 单批图索引需覆盖 LLM 抽取 + Neo4j 写入，5s 过短会导致永远超时或拿不到 Entity
                    _g_timeout = max(120, int(getattr(settings, "EXTRACTION_TIMEOUT", 120.0)) + 90)
                    with _time_limit(_g_timeout):
                        self.graph_engine.create_index(batch, num_workers=1, max_paths_per_chunk=2)
                    success_batches += 1
                except Exception as e:
                    print(">>> [WARN] batch skipped due timeout/error")
                    logger.warning("Graph batch skipped: %s", e)
                    failed_batches += 1
                    continue
                done = min(i + len(batch), num_graph)
                pct = graph_pct_start + int(graph_pct_range * done / num_graph)
                pct = min(pct, 95)
                update(f"Graph indexing: {done}/{num_graph} chunks ({pct}%)", pct, graph_done=done, graph_total=num_graph)
            print(f">>> [GRAPH] success batches: {success_batches}")
            print(f">>> [GRAPH] failed batches: {failed_batches}")
            logger.info(
                "Graph indexing summary: success=%s failed=%s total=%s elapsed_ms=%s",
                success_batches,
                failed_batches,
                total_batches,
                int((time.perf_counter() - t_graph_start) * 1000),
            )
            logger.info("Graph index update complete.")
        else:
            logger.info("Graph index: no new nodes, skipping.")
            if new_for_graph:
                logger.warning(
                    "graph_nodes is empty but new_for_graph is non-empty — "
                    "metadata file_name may not match (files=%s).",
                    new_for_graph,
                )
            print(">>> [INGEST][WARN] graph_nodes is empty")

        logger.info("Ingestion completed successfully.")
        update("Knowledge processing completed! (100%)", 100)
        return len(documents), len(all_nodes)


if __name__ == "__main__":
    ingestor = SMEIngestor()
    ingestor.ingest_data()
