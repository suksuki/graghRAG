from typing import Dict, Any, Optional

import logging
import httpx

from configs.config import settings, get_env_path
from api.schemas import TestRequest
import api.deps as deps
from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine
from core.ingestion import SMEIngestor

logger = logging.getLogger(__name__)


def get_app_settings() -> Dict[str, Any]:
    return {
        "llm_model": settings.LLM_MODEL,
        "extraction_model": settings.EXTRACTION_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "neo4j_uri": settings.NEO4J_URI,
        "postgres_host": settings.POSTGRES_HOST,
    }


async def test_connection_controller(
    test_req: Optional[TestRequest] = None,
    type: Optional[str] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """测试 LLM / 图数据库 连接，返回状态字典，不抛 HTTPException。"""
    test_type = type
    target_url = url
    if test_req:
        test_type = test_req.type or test_type
        target_url = test_req.url or target_url

    try:
        if test_type == "llm":
            base = (target_url or settings.OLLAMA_BASE_URL).rstrip("/")
            logger.info(f"Testing LLM connection at: {base}/api/tags")
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{base}/api/tags", timeout=10.0)
                res.raise_for_status()
                models = [m["name"] for m in res.json().get("models", [])]
                return {"status": "success", "message": f"Connected! Found {len(models)} models."}
        elif test_type == "graph":
            with deps.graph_engine.graph_store._driver.session() as session:
                session.run("RETURN 1")
            return {"status": "success", "message": "Neo4j database connection successful."}
        return {"status": "error", "message": "Invalid test type"}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Connection test failed: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}


async def get_ollama_models_controller(url: Optional[str] = None) -> Dict[str, Any]:
    """列出 Ollama 模型列表。"""
    try:
        base = (url or settings.OLLAMA_BASE_URL).rstrip("/")
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{base}/api/tags", timeout=10.0)
            res.raise_for_status()
            models = [m["name"] for m in res.json().get("models", [])]
            return {"models": models}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to fetch models from Ollama at {url or settings.OLLAMA_BASE_URL}: {e}")
        return {"models": []}


async def update_settings_controller(update: Dict[str, str]) -> Dict[str, Any]:
    """更新配置与 .env，并重建引擎。"""
    try:
        # 1. 更新内存中的配置
        if "llm_model" in update:
            settings.LLM_MODEL = update["llm_model"]
        if "extraction_model" in update:
            settings.EXTRACTION_MODEL = update["extraction_model"]
        if "embedding_model" in update:
            settings.EMBEDDING_MODEL = update["embedding_model"]
        if "ollama_base_url" in update:
            settings.OLLAMA_BASE_URL = update["ollama_base_url"]

        # 2. 自动探测 embedding 维度
        if "embedding_model" in update or "ollama_base_url" in update:
            try:
                embed_url = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/embed"
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        embed_url,
                        json={"model": settings.EMBEDDING_MODEL, "input": "dimension probe"},
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                    embeddings = resp.json().get("embeddings", [])
                    if embeddings:
                        detected_dim = len(embeddings[0])
                        settings.EMBEDDING_DIM = detected_dim
                        logger.info(
                            "Auto-detected embedding dim=%s for model '%s'",
                            detected_dim,
                            settings.EMBEDDING_MODEL,
                        )
            except Exception as dim_err:  # noqa: BLE001
                logger.warning(f"Could not auto-detect embedding dim: {dim_err}")

        # 3. 持久化到 .env：只更新已知键，保留其他键、注释与顺序
        env_path = get_env_path()
        known_updates = {
            "LLM_MODEL": settings.LLM_MODEL,
            "EXTRACTION_MODEL": settings.EXTRACTION_MODEL,
            "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
            "EMBEDDING_DIM": str(settings.EMBEDDING_DIM),
            "OLLAMA_BASE_URL": settings.OLLAMA_BASE_URL,
            "NEO4J_URI": settings.NEO4J_URI,
            "NEO4J_USER": settings.NEO4J_USER,
            "NEO4J_PASSWORD": settings.NEO4J_PASSWORD,
            "POSTGRES_HOST": settings.POSTGRES_HOST,
            "POSTGRES_PORT": str(settings.POSTGRES_PORT),
            "POSTGRES_USER": settings.POSTGRES_USER,
            "POSTGRES_PASSWORD": settings.POSTGRES_PASSWORD,
            "POSTGRES_DB": settings.POSTGRES_DB,
        }
        lines_out = []
        seen = set()
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k = s.split("=", 1)[0].strip()
                        if k in known_updates:
                            lines_out.append(f"{k}={known_updates[k]}\n")
                            seen.add(k)
                            continue
                    lines_out.append(line if line.endswith("\n") else line + "\n")
        for k, v in known_updates.items():
            if k not in seen:
                lines_out.append(f"{k}={v}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines_out)

        # 4. 重新初始化引擎（使用已更新的 settings 配置）
        deps.graph_engine = GraphEngine()
        deps.vector_engine = VectorEngine()
        deps.ingestor = SMEIngestor()

        logger.info(
            "Settings updated: LLM=%s, Embedding=%s(%sd), URL=%s",
            settings.LLM_MODEL,
            settings.EMBEDDING_MODEL,
            settings.EMBEDDING_DIM,
            settings.OLLAMA_BASE_URL,
        )
        return {
            "status": "success",
            "message": "Settings saved.",
            "embedding_dim": settings.EMBEDDING_DIM,
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to update settings: {e}")
        return {"status": "error", "message": str(e)}

