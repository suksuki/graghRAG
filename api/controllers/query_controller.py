from typing import Dict, Any

import logging

import nest_asyncio

from api.schemas import QueryRequest
from pipelines.query_pipeline import QueryPipeline


def query_knowledge(request: QueryRequest) -> Dict[str, Any]:
    """核心查询逻辑（Controller 层）."""
    logger = logging.getLogger(__name__)

    try:
        # 允许在已有事件循环上重入，避免 pytest-asyncio / LlamaIndex 冲突
        nest_asyncio.apply()

        query_text = request.query.strip()
        logger.info("Querying knowledge with mode=%s: %s", request.mode, query_text)

        # 问候语快速路径：不走 GraphRAG 全流程
        greetings = ["你好", "您好", "hi", "hello", "hey", "早上好", "下午好", "晚上好", "在吗"]
        if query_text.lower() in greetings or len(query_text) < 2:
            logger.info("Quick greeting detected, bypassing GraphRAG retrieval.")
            pipeline = QueryPipeline()
            # 直接用 graph_engine 主模型生成简单问候回答
            resp = pipeline.graph_engine.llm.complete(
                f"用户向你打招呼说：'{query_text}'。请作为一个专业的知识库助手礼貌且简短地回复。"
            )
            return {"answer": str(resp), "sources": [], "graph_context": []}

        pipeline = QueryPipeline()
        return pipeline.run(query_text, mode=request.mode)
    except Exception as e:  # noqa: BLE001
        logger.error("Error during query: %s", e)
        msg = str(e).lower()
        if "timeout" in msg or "timed out" in msg:
            return {
                "answer": "抱歉，由于模型规模较大且正在处理复杂逻辑，回答耗时超限，建议切换回 9B 模型进行快速对话。",
                "sources": [],
                "graph_context": [],
            }
        # 其余错误让上层路由抛 HTTPException
        raise

