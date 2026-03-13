"""
VectorEngine — 向量存储引擎
设计原则：
  - 每个 embedding 模型对应独立的 PostgreSQL 表（避免维度冲突、不丢历史数据）
  - 向量维度在保存设置时由 API 层通过查询 Ollama 自动检测并写入 .env
  - 本模块不再运行时猜测维度，直接读 settings.EMBEDDING_DIM
"""

import re
import logging
import psycopg2

from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core import StorageContext, VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama

from configs.config import settings

logger = logging.getLogger(__name__)


def _model_to_table_suffix(model_name: str) -> str:
    """
    将模型名转成合法的 PostgreSQL 表名后缀。
    例：'bge-m3:latest' -> 'bge_m3_latest'
         'nomic-embed-text' -> 'nomic_embed_text'
    """
    return re.sub(r"[^a-z0-9]", "_", model_name.lower()).strip("_")


def _get_table_name() -> str:
    """每个 embedding 模型对应独立的表，前缀固定为 sme_vs_。"""
    suffix = _model_to_table_suffix(settings.EMBEDDING_MODEL)
    return f"sme_vs_{suffix}"


def _get_db_table_dim(full_table_name: str) -> int | None:
    """查询 PostgreSQL，获取已有表的向量维度。表不存在时返回 None。"""
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
            "SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE c.relname = %s AND a.attname = 'embedding'",
            (full_table_name,)
        )
        row = cur.fetchone()
        conn.close()
        if row and "(" in row[0]:
            return int(row[0].split("(")[1].rstrip(")"))
    except Exception as e:
        logger.warning(f"Could not query existing table dim for '{full_table_name}': {e}")
    return None


def _drop_table(full_table_name: str):
    """删除维度错误的旧表。"""
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB
        )
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {full_table_name}")
        conn.commit()
        conn.close()
        logger.warning(f"Dropped table '{full_table_name}' due to embedding dimension mismatch.")
    except Exception as e:
        logger.error(f"Failed to drop table '{full_table_name}': {e}")


class VectorEngine:
    def __init__(self):
        self.llm = Ollama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.REQUEST_TIMEOUT
        )
        self.embed_model = OllamaEmbedding(
            model_name=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.REQUEST_TIMEOUT
        )
        Settings.llm = self.llm
        Settings.embed_model = self.embed_model

        # 维度来自配置（由 /settings/update 在保存时自动检测写入）
        self.embed_dim = settings.EMBEDDING_DIM

        # 按模型名选独立的表
        self.table_name = _get_table_name()
        self.full_table_name = f"data_{self.table_name}"

        # 如果表已存在但维度不匹配（用户手动改过 .env 等情况），删旧表
        db_dim = _get_db_table_dim(self.full_table_name)
        if db_dim is not None and db_dim != self.embed_dim:
            logger.warning(
                f"Table '{self.full_table_name}' has vector({db_dim}) but "
                f"current model needs {self.embed_dim}d. Recreating table."
            )
            _drop_table(self.full_table_name)

        self.vector_store = PGVectorStore.from_params(
            database=settings.POSTGRES_DB,
            host=settings.POSTGRES_HOST,
            password=settings.POSTGRES_PASSWORD,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            table_name=self.table_name,
            embed_dim=self.embed_dim,
        )
        self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)

        logger.info(
            f"VectorEngine ready: model='{settings.EMBEDDING_MODEL}', "
            f"dim={self.embed_dim}, table='{self.full_table_name}'"
        )

    def add_documents(self, nodes):
        """将节点写入当前模型对应的向量表。"""
        VectorStoreIndex(
            nodes,
            storage_context=self.storage_context,
            embed_model=self.embed_model,
            show_progress=True
        )

    def delete_document(self, filename: str) -> int:
        """从当前向量表中删除与指定文件相关的所有向量。"""
        from sqlalchemy import text
        for col in ["metadata_", "metadata"]:
            try:
                query = text(
                    f"DELETE FROM {self.full_table_name} "
                    f"WHERE ({col} ->> 'file_name') = :filename"
                )
                with self.vector_store._engine.connect() as conn:
                    result = conn.execute(query, {"filename": filename})
                    conn.commit()
                    if result.rowcount > 0:
                        logger.info(
                            f"Deleted {result.rowcount} vectors for '{filename}' "
                            f"from '{self.full_table_name}'"
                        )
                        return result.rowcount
            except Exception as e:
                logger.debug(f"Delete with col='{col}' failed: {e}")
        return 0

    def get_query_engine(self):
        """返回针对当前向量表的检索引擎。"""
        index = VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            embed_model=self.embed_model
        )
        return index.as_query_engine()
