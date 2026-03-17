from typing import Final


class PromptBuilder:
    """
    负责将用户问题和结构化上下文字符串组合成最终提示词，供 LLM 使用。
    不做任何检索或业务逻辑，只做 prompt 组织。
    """

    _SYSTEM_PREFIX: Final[str] = (
        "You are an expert knowledge graph assistant for an enterprise knowledge base.\n"
        "Use the evidence below to answer the user's question as accurately and concisely as possible.\n"
        "If graph relationships or paths are provided, explain the relationship chain in natural language.\n"
    )

    def build_prompt(self, query: str, context: str) -> str:
        query = (query or "").strip()
        context = (context or "").strip()

        # 当没有上下文时，仅包装问题，让上层可以回退到旧行为
        if not context:
            return f"{self._SYSTEM_PREFIX}\n\nQuestion:\n{query}\n"

        return (
            f"{self._SYSTEM_PREFIX}\n\n"
            f"Question:\n{query}\n\n"
            f"Evidence:\n{context}\n\n"
            "Answer the question clearly. If useful, cite key facts and describe how entities are connected in the graph."
        )

