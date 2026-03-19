from typing import Final


class PromptBuilder:
    """
    负责将用户问题和结构化上下文字符串组合成最终提示词，供 LLM 使用。
    极简指令以减少模型内部 planning，降低延迟。
    """

    _SYSTEM_PREFIX: Final[str] = (
        "You are a fast enterprise QA system. Use structured knowledge first. "
        "If graph relations are available, prioritize them. Do not ignore relationships. "
        "Be concise (max 2 sentences). "
        "Do not repeat sentences. Remove duplicated information.\n"
    )

    def build_prompt(self, query: str, context: str) -> str:
        query = (query or "").strip()
        context = (context or "").strip()

        if not context:
            return f"{self._SYSTEM_PREFIX}Question:\n{query}\n"

        return f"{self._SYSTEM_PREFIX}Question:\n{query}\n\nEvidence:\n{context}\n\nAnswer:"

