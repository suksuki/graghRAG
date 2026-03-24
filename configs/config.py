import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional

# 项目根目录：configs 的上级
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_env_path() -> Path:
    """.env 文件路径：优先环境变量 GRAPHRAG_ENV_FILE，否则为项目根目录下的 .env"""
    return Path(os.environ.get("GRAPHRAG_ENV_FILE", str(PROJECT_ROOT / ".env")))


def get_data_raw_dir() -> str:
    """原始数据目录：默认项目根下的 data/raw"""
    return str(PROJECT_ROOT / "data" / "raw")


def get_data_processed_dir() -> str:
    """处理后数据目录：默认项目根下的 data/processed"""
    return str(PROJECT_ROOT / "data" / "processed")


class Settings(BaseSettings):
    # API Settings
    PROJECT_NAME: str = "SME GraphRAG Platform"
    API_V1_STR: str = "/api/v1"

    # Database & Queue Settings
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4jpass"

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "rag"
    POSTGRES_PASSWORD: str = "ragpass"
    POSTGRES_DB: str = "ragdb"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM Settings
    OLLAMA_BASE_URL: str = "http://192.168.0.10:11434"
    LLM_MODEL: str = "qwen2.5:7b"            # 用于对话/查询的主模型（可由设置页或 .env 覆盖）；首字延迟高时可改为 qwen2.5:3b
    LLM_NUM_CTX: Optional[int] = 1024        # Ollama 上下文长度上限，越小 prefill 越快（当前 prompt 约 400–500 token）
    LLM_NUM_PREDICT: int = 64                # 单次生成最大 token 数，降低 decode 时间，目标 2–3 句
    EXTRACTION_MODEL: str = "qwen2.5:14b"    # 图谱三元组抽取；1.5b/3b 易不按格式输出，14b 更稳（可用 .env 覆盖）
    EMBEDDING_MODEL: str = "bge-m3:latest"
    EMBEDDING_DIM: int = 1024  # 由保存配置时自动检测写入，不需手动修改
    REQUEST_TIMEOUT: float = 1200.0  # 长超时，供大模型或重图抽取使用
    EXTRACTION_TIMEOUT: float = 120.0  # 单次抽取请求超时（秒），避免图索引阶段卡死
    EXTRACTION_NUM_WORKERS: int = 4   # 图抽取并发数，显存允许可调大
    GRAPH_MAX_NODES: int = 30         # 单次摄取最多对多少块做图索引（0=不限制），显著减少 LLM 调用
    KG_LEXICAL_FALLBACK: bool = True  # LLM 三元组为空时用语块拼一条 RELATED_TO，避免图完全空（演示/稳态）
    # 图查询默认忽略低于该置信度的关系（fallback 为 0.3）；设为 0 则不过滤
    KG_MIN_EDGE_CONFIDENCE_FOR_QUERY: float = 0.5

    # 分块（越大块数越少，图索引越快，但单块语义可能越粗）
    CHUNK_SIZE: int = 1536
    CHUNK_OVERLAP: int = 128

    # Document Intelligence（摄取时 LLM 抽取）：提示语言偏好 zh / en / ko
    DOC_INTEL_LANG: str = "zh"

    # Storage Settings（默认项目根下路径，可通过环境变量覆盖）
    DATA_RAW_DIR: str = Field(default_factory=get_data_raw_dir)
    DATA_PROCESSED_DIR: str = Field(default_factory=get_data_processed_dir)

    class Config:
        env_file = str(get_env_path())
        env_file_encoding = "utf-8"


settings = Settings()
