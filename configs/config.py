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
    LLM_MODEL: str = "qwen3.5:35b"           # 用于对话/查询的主模型
    EXTRACTION_MODEL: str = "qwen2.5:7b"     # 用于图谱实体抽取的专用小模型（越小越快）
    EMBEDDING_MODEL: str = "bge-m3:latest"
    EMBEDDING_DIM: int = 1024  # 由保存配置时自动检测写入，不需手动修改
    REQUEST_TIMEOUT: float = 1200.0  # 20 minutes for heavy 35B graph extractions
    EXTRACTION_TIMEOUT: float = 120.0  # 单次抽取请求超时（秒），避免图索引阶段卡死
    EXTRACTION_NUM_WORKERS: int = 4   # 图抽取并发数，显存允许可调大
    GRAPH_MAX_NODES: int = 30         # 单次摄取最多对多少块做图索引（0=不限制），显著减少 LLM 调用

    # 分块（越大块数越少，图索引越快，但单块语义可能越粗）
    CHUNK_SIZE: int = 1536
    CHUNK_OVERLAP: int = 128

    # Storage Settings（默认项目根下路径，可通过环境变量覆盖）
    DATA_RAW_DIR: str = Field(default_factory=get_data_raw_dir)
    DATA_PROCESSED_DIR: str = Field(default_factory=get_data_processed_dir)

    class Config:
        env_file = str(get_env_path())
        env_file_encoding = "utf-8"


settings = Settings()
