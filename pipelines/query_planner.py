import logging
import re
from typing import Dict, List


logger = logging.getLogger(__name__)


class QueryPlanner:
    """
    轻量级 Query Planner：
    - 负责意图识别 / 策略映射 / 粗粒度实体提取
    - 不直接执行任何检索，仅返回 plan dict
    """

    def plan(self, query: str) -> Dict:
        intent = self._detect_intent(query)
        strategy = self._map_intent_to_strategy(intent)
        entities = self._extract_entities(query)
        plan = {
            "intent": intent,
            "strategy": strategy,
            "entities": entities,
        }
        return plan

    # ------------------------------------------------------------------
    # Intent detection
    # ------------------------------------------------------------------
    def _detect_intent(self, query: str) -> str:
        q = (query or "").strip()
        q_lower = q.lower()

        if not q:
            return "greeting"

        # greeting
        greetings = ["hi", "hello", "hey", "你好", "您好", "早上好", "下午好", "晚上好"]
        if any(tok in q_lower for tok in greetings):
            return "greeting"

        # graph_reasoning （优先于关系问句的一般匹配）
        graph_reasoning_patterns = [
            "path between",
            "relationship between",
            "how is ",
            " related to ",
            "和.+的关系",
            "之间的关系",
        ]
        if any(re.search(pat, q_lower) for pat in graph_reasoning_patterns):
            return "graph_reasoning"

        # relationship_query
        rel_keywords = ["relation", "relationship", "关系", "related to", "connection between", "关联"]
        if any(k in q_lower for k in rel_keywords):
            return "relationship_query"

        # document_search
        doc_keywords = ["document", "file", "哪篇文档", "哪个文档", "文件", "文档中", "文件中"]
        if any(k in q_lower for k in doc_keywords):
            return "document_search"

        # fallback
        return "fact_lookup"

    # ------------------------------------------------------------------
    # Strategy mapping
    # ------------------------------------------------------------------
    def _map_intent_to_strategy(self, intent: str) -> str:
        mapping = {
            "greeting": "llm_only",
            "fact_lookup": "hybrid",
            "relationship_query": "graph",
            "document_search": "vector",
            "graph_reasoning": "graph_traversal",
        }
        return mapping.get(intent, "hybrid")

    # ------------------------------------------------------------------
    # Entity extraction (very simple heuristics)
    # ------------------------------------------------------------------
    def _extract_entities(self, query: str) -> List[str]:
        if not query:
            return []

        entities: List[str] = []

        # 1) 内容在引号中的词
        quoted = re.findall(r"[\"“”'‘’]([^\"“”'‘’]+)[\"“”'‘’]", query)
        entities.extend([s.strip() for s in quoted if s.strip()])

        # 2) 简单的英文首字母大写 token / 短语
        #    e.g. "Apple", "Project Antigravity"
        tokens = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", query)
        entities.extend(tokens)

        # 3) 连续大写开头单词组成的短语
        phrases = re.findall(r"\b([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)+)\b", query)
        entities.extend(phrases)

        # 去重，保持原顺序
        seen = set()
        uniq: List[str] = []
        for e in entities:
            if e not in seen:
                seen.add(e)
                uniq.append(e)

        return uniq

