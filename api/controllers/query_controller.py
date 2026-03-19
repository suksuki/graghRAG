from typing import Dict, Any

import logging

import nest_asyncio

from api.schemas import QueryRequest
from core.lang_detect import resolve_query_language
from pipelines.query_pipeline import QueryPipeline


def query_knowledge(request: QueryRequest, ui_lang: str = "zh") -> Dict[str, Any]:
    """核心查询逻辑（Controller 层）."""
    logger = logging.getLogger(__name__)

    try:
        # 允许在已有事件循环上重入，避免 pytest-asyncio / LlamaIndex 冲突
        nest_asyncio.apply()

        query_text = request.query.strip()
        lang_info = resolve_query_language(query_text, ui_lang)
        final_lang = str(lang_info["lang_final"])
        logger.info("Querying knowledge with mode=%s: %s", request.mode, query_text)

        # 问候语快速路径：不走 GraphRAG 全流程
        greetings = ["你好", "您好", "hi", "hello", "hey", "早上好", "下午好", "晚上好", "在吗"]
        if query_text.lower() in greetings or len(query_text) < 2:
            logger.info("Quick greeting detected, bypassing GraphRAG retrieval.")
            pipeline = QueryPipeline(lang=final_lang)
            # 直接用 graph_engine 主模型生成简单问候回答
            resp = pipeline.graph_engine.llm.complete(
                f"{pipeline._lang_instruction()}\n\n{pipeline._greeting_prompt(query_text)}"
            )
            return {"answer": str(resp), "sources": [], "graph_context": [], **lang_info}

        pipeline = QueryPipeline(lang=final_lang)
        return {**pipeline.run(query_text, mode=request.mode), **lang_info}
    except Exception as e:  # noqa: BLE001
        logger.error("Error during query: %s", e)
        msg = str(e).lower()
        if "timeout" in msg or "timed out" in msg:
            lang_bucket = QueryPipeline(lang=str(resolve_query_language(request.query.strip(), ui_lang)["lang_final"]))._lang_bucket()
            if lang_bucket == "en":
                answer = "Sorry, the current model timed out while handling a complex request. Try a smaller model for faster responses."
            elif lang_bucket == "ko":
                answer = "죄송합니다. 현재 모델이 복잡한 요청을 처리하는 동안 시간 제한을 초과했습니다. 더 빠른 응답을 위해 작은 모델로 전환해 보세요."
            else:
                answer = "抱歉，由于模型规模较大且正在处理复杂逻辑，回答耗时超限，建议切换回 9B 模型进行快速对话。"
            return {
                "answer": answer,
                "sources": [],
                "graph_context": [],
                **resolve_query_language(request.query.strip(), ui_lang),
            }
        # 其余错误让上层路由抛 HTTPException
        raise

