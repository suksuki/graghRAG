from typing import Any, Dict, Iterable, List

import textwrap


class ContextBuilder:
    """
    将多路检索/遍历结果整理为一个结构化的文本上下文字符串，供 LLM 使用。

    该模块只负责**格式化与组织信息**，不做任何检索调用。
    """

    def _format_sources(self, label: str, nodes: Iterable[Any]) -> str:
        lines: List[str] = []
        for idx, node in enumerate(nodes, start=1):
            text = getattr(node, "text", "") or ""
            if not text:
                continue
            metadata = getattr(node, "metadata", {}) if hasattr(node, "metadata") else {}
            file_name = metadata.get("file_name", "Unknown")
            snippet = text.strip().replace("\n", " ")
            snippet = snippet[:400]
            lines.append(f"[{label} {idx}] ({file_name}) {snippet}")
        return "\n".join(lines)

    def _format_edges(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
        if not nodes or not edges:
            return ""
        id_to_name: Dict[Any, str] = {}
        for n in nodes:
            props = n.get("properties", {})
            name = props.get("name") or props.get("title") or props.get("file_name") or str(n.get("id"))
            id_to_name[n.get("id")] = str(name)
        lines: List[str] = []
        for e in edges:
            s = e.get("source")
            t = e.get("target")
            rel = e.get("type", "RELATED_TO")
            s_name = id_to_name.get(s, str(s))
            t_name = id_to_name.get(t, str(t))
            lines.append(f"{s_name} --{rel}--> {t_name}")
        return "\n".join(lines)

    def build_context(
        self,
        query: str,
        vector_resp: Any,
        graph_resp: Any,
        traversal_nodes: List[Dict[str, Any]] | None,
        traversal_edges: List[Dict[str, Any]] | None,
    ) -> str:
        """
        构建给 LLM 使用的结构化上下文字符串。

        当前实现：
        - 从 vector_resp / graph_resp 的 source_nodes 中提取文本片段；
        - 将 traversal_nodes / traversal_edges 格式化为关系三元组样式；
        - 返回一段多段落的 context 文本。
        """
        parts: List[str] = []

        # 1) 用户问题
        parts.append("User question:")
        parts.append(query.strip())

        # 2) 文档事实（向量检索）
        vector_nodes = getattr(vector_resp, "source_nodes", []) if vector_resp is not None else []
        vec_block = self._format_sources("DOC", vector_nodes)
        if vec_block:
            parts.append("")
            parts.append("Facts from documents (vector retrieval):")
            parts.append(vec_block)

        # 3) 图检索结果
        graph_nodes = getattr(graph_resp, "source_nodes", []) if graph_resp is not None else []
        graph_block = self._format_sources("GRAPH", graph_nodes)
        if graph_block:
            parts.append("")
            parts.append("Facts from graph search:")
            parts.append(graph_block)

        # 4) 图遍历路径
        tn = traversal_nodes or []
        te = traversal_edges or []
        edges_block = self._format_edges(tn, te)
        if edges_block:
            parts.append("")
            parts.append("Graph relationships / paths:")
            parts.append(edges_block)

        context_str = "\n".join(parts).strip()
        # 稍作缩进规整，避免前导空格
        return textwrap.dedent(context_str)

