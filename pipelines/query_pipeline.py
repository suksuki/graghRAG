from typing import Any, Dict, List

import asyncio
import logging
import re
import time

from api.deps import graph_engine, vector_engine
from core.lang_guard import enforce_language
from core.graph_traversal import GraphTraversalEngine, extract_triples
from core.query_cache import GRAPH_VERSION, QueryCache
from core.entity_normalization import normalize_entity
from core.vector_store import _get_embed_call_count, _reset_embed_call_count
from pipelines.context_builder import ContextBuilder, MAX_CONTEXT_CHUNKS
from pipelines.prompt_builder import PromptBuilder
from pipelines.query_planner import QueryPlanner
from llama_index.llms.ollama import Ollama
from configs.config import settings


def _ensure_event_loop() -> None:
    """确保当前线程上有一个打开的事件循环。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Closed event loop")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


logger = logging.getLogger(__name__)


class QueryPipeline:
    def __init__(self, redis_url: str = "redis://localhost:6379/0", lang: str = "zh") -> None:
        self.graph_engine = graph_engine
        self.vector_engine = vector_engine
        self.lang = (lang or "zh").strip().lower()
        self.answer_llm = Ollama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.REQUEST_TIMEOUT,
            context_window=2048,
            additional_kwargs={"num_ctx": 2048, "num_predict": 128, "temperature": 0.2},
            keep_alive="30m",
            thinking=False,
        )
        self.planner = QueryPlanner()
        self.traversal_engine = GraphTraversalEngine(self.graph_engine)
        self.context_builder = ContextBuilder()
        self.prompt_builder = PromptBuilder()
        self.max_context_chunks = 2
        self.max_graph_relations = 10
        self.max_two_hop = 5
        self.precompute_ttl_seconds = 24 * 3600
        try:
            self.query_cache: QueryCache | None = QueryCache(url=redis_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("Query cache disabled (Redis unavailable): %s", e)
            self.query_cache = None
        self._precompute_mem: Dict[str, Dict[str, Any]] = {}

    def _lang_bucket(self) -> str:
        lang = (self.lang or "zh").strip().lower()
        if lang.startswith("zh"):
            return "zh"
        if lang.startswith("ko"):
            return "ko"
        if lang.startswith("en"):
            return "en"
        return "en"

    def _lang_instruction(self) -> str:
        lang = self._lang_bucket()
        if lang == "en":
            return "Answer ONLY in English. Do not use Chinese."
        if lang == "ko":
            return "항상 한국어로 답변하세요. 영어와 중국어를 사용하지 마세요."
        return "请始终使用中文回答。不要使用英文。"

    def _greeting_prompt(self, query: str) -> str:
        lang = self._lang_bucket()
        if lang == "en":
            return f"The user greeted you with: '{query}'. Reply politely and briefly as a professional knowledge assistant."
        if lang == "ko":
            return f"사용자가 다음과 같이 인사했습니다: '{query}'. 전문적인 지식 도우미처럼 정중하고 짧게 답변하세요."
        return f"用户向你打招呼说：'{query}'。请作为一个专业的知识库助手礼貌且简短地回复。"

    def _with_lang_instruction(self, prompt: str) -> str:
        return f"{self._lang_instruction()}\n\n{prompt}"

    def _should_retry_language(self, text: str) -> bool:
        t = text or ""
        if not t.strip():
            return False
        ascii_letters = len(re.findall(r"[A-Za-z]", t))
        zh_chars = len(re.findall(r"[\u4e00-\u9fff]", t))
        ko_chars = len(re.findall(r"[\uac00-\ud7a3]", t))
        total = max(len(t), 1)
        lang = self._lang_bucket()
        if lang == "en":
            return (zh_chars / total) > 0.2
        if lang == "ko":
            return (ko_chars / total) < 0.1 and ((ascii_letters + zh_chars) / total) > 0.2
        return (ascii_letters / total) > 0.5

    def _rewrite_in_target_language(self, text: str) -> str:
        prompt = (
            f"{self._lang_instruction()}\n"
            "Rewrite the following answer into the target language only, preserving meaning and structure.\n\n"
            f"{text}"
        )
        try:
            return str(self.answer_llm.complete(prompt))
        except Exception:  # noqa: BLE001
            return text

    # ------------------------- Query understanding -------------------------
    def detect_query_intent(self, query: str) -> str:
        q = query.strip().lower()
        if not q:
            return "greeting"

        greetings = ["hi", "hello", "hey", "早上好", "下午好", "晚上好", "你好", "您好", "在吗"]
        if any(tok in q for tok in greetings):
            return "greeting"

        rel_keywords = ["关系", "related to", "relationship", "关联", "how are", "connection between"]
        if any(k in q for k in rel_keywords):
            return "relationship_query"

        doc_keywords = ["哪篇文档", "which document", "which file", "文档中", "文件中"]
        if any(k in q for k in doc_keywords):
            return "document_search"

        return "fact_lookup"

    def choose_strategy(self, intent: str, mode: str | None = None) -> str:
        """
        选择检索策略：
          - 若用户显式指定 vector/graph，则严格遵守；
          - 若用户指定 hybrid 或未指定，则根据意图自动选择，优先走「快路径」：
              * greeting            -> graph_only（简单问候，用主模型快速回一句）
              * relationship_query  -> graph_only（确实需要图）
              * document_search     -> vector_only（只查哪篇文档，向量足够）
              * fact_lookup         -> vector_only（默认事实问答优先走向量）
        """
        # 显式模式优先（vector / graph）
        if mode in ("vector", "graph"):
            return {
                "vector": "vector_only",
                "graph": "graph_only",
            }[mode]

        # hybrid 或 None 视为自动模式，根据意图选择
        if intent == "greeting":
            return "graph_only"
        if intent == "relationship_query":
            return "graph_only"
        if intent in ("document_search", "fact_lookup"):
            return "vector_only"

        # 兜底：未知意图仍走向量优先
        return "vector_only"

    # ------------------------- Retrieval layer -------------------------
    def vector_retrieval(self, query: str, top_k: int = 5):
        """仅做向量检索，1 次 query embedding + 向量搜索，不经过 query_engine 的 response_synthesizer（避免重复 embedding）。"""
        retriever = self.vector_engine.get_retriever(similarity_top_k=top_k)
        nodes_with_scores = retriever.retrieve(query)
        # 把 score 写入 node.metadata，便于下游按相关性排序再截断（避免丢掉最重要信息）
        source_nodes = []
        for nws in nodes_with_scores:
            node = nws.node
            if not hasattr(node, "metadata") or node.metadata is None:
                node.metadata = {}
            node.metadata["score"] = getattr(nws, "score", 0.0)
            source_nodes.append(node)
        print(f">>> [QUERY] vector top_k: {len(source_nodes)}")
        return type("VectorResponse", (), {"source_nodes": source_nodes})()

    def graph_retrieval(self, query: str):
        qe = self.graph_engine.get_query_engine()
        return qe.query(query)

    # ------------------------- Simple GraphRAG v1 helpers -------------------------
    def _extract_entities_from_nodes(self, nodes: List[Any], max_entities: int = 5) -> List[str]:
        """
        从向量检索到的文本块中用简单规则提取实体名称：
        - 优先提取包含“公司”的中文短语
        - 其次提取较长的英文单词（假定为专有名词）
        """
        entities: List[str] = []
        seen = set()
        company_pat = re.compile(r"[\u4e00-\u9fff]{2,10}公司")
        en_pat = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
        for node in nodes:
            text = (getattr(node, "text", "") or "")[:300]
            for m in company_pat.findall(text):
                if m not in seen:
                    seen.add(m)
                    entities.append(m)
                    if len(entities) >= max_entities:
                        return entities
            for m in en_pat.findall(text):
                if m not in seen:
                    seen.add(m)
                    entities.append(m)
                    if len(entities) >= max_entities:
                        return entities
        return entities[:max_entities]

    def graph_retrieve_from_entities(self, entities: List[str]) -> Dict[str, Any]:
        """
        根据实体列表从 Neo4j 检索一跳关系，返回关系字符串列表。
        """
        relations: List[str] = []
        triples: List[Dict[str, str]] = []
        print(">>> [GRAPH] graph_retrieve called")
        if not entities:
            print(">>> [GRAPH RETRIEVE] relations count: 0")
            return {"relations": relations, "triples": triples}

        try:
            graph_version = self._graph_version()
            with self.graph_engine.graph_store._driver.session() as session:  # type: ignore[attr-defined]
                try:
                    session.run("CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)")
                except Exception:  # noqa: BLE001
                    pass
                for ent in entities:
                    ent_raw = (ent or "").strip()
                    ent_norm_key = normalize_entity(ent_raw)
                    ent_norm = ent_raw
                    cache_key = f"graph:retrieve:{ent_norm_key or ent_raw}|{graph_version}"
                    if self.query_cache is not None:
                        cached = self.query_cache.get(cache_key)
                        if isinstance(cached, dict) and isinstance(cached.get("triples"), list):
                            ctriples = (cached.get("triples") or [])[: self.max_graph_relations]
                            ctr = (cached.get("relations") or [])[: self.max_graph_relations]
                            triples.extend(ctriples)
                            relations.extend(ctr)
                            pre_payload = self._build_precompute_payload(
                                self._build_graph_summary(ctriples, min_relations=5),
                                ctriples,
                            )
                            pre_src = ""
                            if ctriples and isinstance(ctriples[0], dict):
                                pre_src = str(ctriples[0].get("source") or "").strip()
                            pre_entity = pre_src or ent_norm_key or ent_raw
                            self._set_precompute(pre_entity, pre_payload, graph_version=graph_version)
                            continue
                    if ent_norm:
                        rows0 = session.run(
                            """
                            MATCH (a:Entity {name: $q})
                            OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
                            RETURN coalesce(b.name, a.name) AS canonical
                            LIMIT 1
                            """,
                            q=ent_norm,
                        )
                        rec0 = rows0.single()
                        if not rec0 and ent_norm_key and ent_norm_key != ent_norm.lower():
                            rows0 = session.run(
                                """
                                MATCH (a:Entity {name: $q})
                                OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
                                RETURN coalesce(b.name, a.name) AS canonical
                                LIMIT 1
                                """,
                                q=ent_norm_key,
                            )
                            rec0 = rows0.single()
                        if not rec0:
                            rows0 = session.run(
                                """
                                MATCH (a:Entity)
                                WHERE toLower(a.name) CONTAINS toLower($q)
                                OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
                                RETURN coalesce(b.name, a.name) AS canonical
                                LIMIT 1
                                """,
                                q=ent_norm,
                            )
                            rec0 = rows0.single()
                        if not rec0 and ent_norm_key and ent_norm_key != ent_norm.lower():
                            rows0 = session.run(
                                """
                                MATCH (a:Entity)
                                WHERE toLower(a.name) CONTAINS toLower($q)
                                OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
                                RETURN coalesce(b.name, a.name) AS canonical
                                LIMIT 1
                                """,
                                q=ent_norm_key,
                            )
                            rec0 = rows0.single()
                        if rec0 and rec0.get("canonical"):
                            ent_norm = str(rec0.get("canonical"))
                    # 2-hop: Entity ->(PROVIDES)-> Entity ->(APPLIES_TO)-> Entity
                    rows = session.run(
                        """
                        MATCH (a:Entity {name: $entity})
                        MATCH (a)-[:PROVIDES]->(b:Entity)
                        OPTIONAL MATCH (b)-[:APPLIES_TO]->(c:Entity)
                        RETURN a.name AS entity_name, b.name AS product, collect(DISTINCT c.name) AS domains
                        LIMIT 10
                        """,
                        entity=ent_norm,
                    )
                    data_rows = list(rows)
                    if not data_rows:
                        rows = session.run(
                            """
                            MATCH (a:Entity)
                            WHERE toLower(a.name) CONTAINS toLower($entity)
                            OPTIONAL MATCH (a)-[:ALIAS_OF]->(b:Entity)
                            WITH coalesce(b, a) AS a2
                            MATCH (a2)-[:PROVIDES]->(b:Entity)
                            OPTIONAL MATCH (b)-[:APPLIES_TO]->(c:Entity)
                            RETURN a2.name AS entity_name, b.name AS product, collect(DISTINCT c.name) AS domains
                            LIMIT 10
                            """,
                            entity=ent_norm,
                        )
                        data_rows = list(rows)
                    local_relations: List[str] = []
                    local_triples: List[Dict[str, str]] = []
                    for rec in data_rows:
                        a_name = rec.get("entity_name") or ent_norm
                        product = rec.get("product")
                        domains = rec.get("domains") or []
                        if product:
                            if len(local_triples) < self.max_graph_relations:
                                local_relations.append(f"{a_name} -[PROVIDES]- {product}")
                                local_triples.append({"source": str(a_name), "relation": "PROVIDES", "target": str(product)})
                        if isinstance(domains, list):
                            for d in domains:
                                if d:
                                    if len(local_triples) < self.max_graph_relations:
                                        local_relations.append(f"{product} -[APPLIES_TO]- {d}")
                                        local_triples.append({"source": str(product), "relation": "APPLIES_TO", "target": str(d)})
                                    else:
                                        break
                        if len(local_triples) >= self.max_graph_relations:
                            break
                    relations.extend(local_relations)
                    triples.extend(local_triples)
                    pre_payload = self._build_precompute_payload(
                        self._build_graph_summary(local_triples, min_relations=5),
                        local_triples,
                    )
                    self._set_precompute(ent_norm or ent_raw, pre_payload, graph_version=graph_version)
                    if self.query_cache is not None:
                        try:
                            self.query_cache.set(cache_key, {"relations": local_relations, "triples": local_triples}, ttl=600)
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as e:  # noqa: BLE001
            logger.error("Graph entity retrieval failed: %s", e)

        print(f">>> [GRAPH RETRIEVE] relations count: {len(relations)}")
        return {"relations": relations, "triples": triples}

    def _build_graph_2hop(self, triples: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        prod_to_domains: Dict[str, List[str]] = {}
        products: List[str] = []
        for t in triples or []:
            if not isinstance(t, dict):
                continue
            rel = t.get("relation")
            src = t.get("source") or ""
            tgt = t.get("target") or ""
            if rel == "PROVIDES" and tgt:
                products.append(str(tgt))
                prod_to_domains.setdefault(str(tgt), [])
            elif rel == "APPLIES_TO" and src and tgt:
                prod_to_domains.setdefault(str(src), []).append(str(tgt))

        uniq_products = list(dict.fromkeys(products))
        out: List[Dict[str, Any]] = []
        for p in uniq_products:
            ds = list(dict.fromkeys(prod_to_domains.get(p, [])))
            out.append({"product": p, "domains": ds})
        return out

    def _build_graph_summary(self, triples: List[Dict[str, str]], min_relations: int) -> str | None:
        if not triples or len(triples) <= min_relations:
            return None
        companies = [t.get("source") for t in triples if t.get("relation") == "PROVIDES" and t.get("source")]
        company = companies[0] if companies else None
        products = [t.get("target") for t in triples if t.get("relation") == "PROVIDES" and t.get("target")]
        domains = [t.get("target") for t in triples if t.get("relation") == "APPLIES_TO" and t.get("target")]
        products_uniq = list(dict.fromkeys([p for p in products if p]))
        domains_uniq = list(dict.fromkeys([d for d in domains if d]))
        if not company or (not products_uniq and not domains_uniq):
            return None
        lang = self._lang_bucket()
        if lang == "en":
            top_products = ", ".join(products_uniq[:3]) if products_uniq else "related products"
            top_domains = ", ".join(domains_uniq[:3]) if domains_uniq else "multiple industries"
            return f"{company} provides {top_products} and is mainly applied in {top_domains}."
        if lang == "ko":
            top_products = ", ".join(products_uniq[:3]) if products_uniq else "관련 제품"
            top_domains = ", ".join(domains_uniq[:3]) if domains_uniq else "여러 산업"
            return f"{company}는 {top_products}를 제공하며, 주로 {top_domains} 분야에 적용됩니다."
        top_products = "、".join(products_uniq[:3]) if products_uniq else "相关产品"
        top_domains = "、".join(domains_uniq[:3]) if domains_uniq else "多个行业"
        return f"{company} 提供 {top_products}，主要应用于 {top_domains}"

    def _guard_summary(self, summary: str | None) -> str:
        return enforce_language(summary or "", self._lang_bucket(), llm=self.answer_llm)

    def _graph_quality_ok(self, relations_count: int, summary: str | None) -> bool:
        return (relations_count >= 3) or bool(summary)

    def _graph_version(self) -> str:
        if self.query_cache is not None:
            try:
                return self.query_cache.get_graph_version()
            except Exception:  # noqa: BLE001
                pass
        return GRAPH_VERSION

    def _precompute_key(self, entity: str, graph_version: str | None = None, lang: str | None = None) -> str:
        ek = normalize_entity(entity or "") or (entity or "").strip().lower()
        gv = graph_version or self._graph_version()
        lk = (lang or self.lang or "zh").strip().lower()
        return f"graph:precompute:{ek}:{lk}:{gv}"

    def _query_cache_key(self, normalized_query: str, graph_version: str | None = None) -> str:
        gv = graph_version or self._graph_version()
        return f"{normalized_query}|{self._lang_bucket()}|{gv}"

    def _build_precompute_payload(self, summary: str | None, relations: List[Dict[str, str]]) -> Dict[str, Any]:
        return {
            "summary": self._guard_summary(summary),
            "relations": (relations or [])[: self.max_graph_relations],
            "suggestions": [],
        }

    def _is_precompute_valid(self, pre: Dict[str, Any] | None) -> bool:
        if not isinstance(pre, dict):
            return False
        summary = str(pre.get("summary") or "").strip()
        relations = pre.get("relations") or []
        rel_count = len(relations) if isinstance(relations, list) else 0
        return bool(summary) or (rel_count > 0)

    def _set_precompute(self, entity: str, payload: Dict[str, Any], graph_version: str | None = None) -> None:
        key = self._precompute_key(entity, graph_version=graph_version)
        self._precompute_mem[key] = payload
        if self.query_cache is not None:
            try:
                self.query_cache.set(key, payload, ttl=self.precompute_ttl_seconds)
            except Exception:  # noqa: BLE001
                pass

    def _get_precompute(self, entity: str, graph_version: str | None = None) -> Dict[str, Any] | None:
        key = self._precompute_key(entity, graph_version=graph_version)
        val: Dict[str, Any] | None = None
        if self.query_cache is not None:
            try:
                cached_val = self.query_cache.get(key)
                if isinstance(cached_val, dict):
                    val = dict(cached_val)
            except Exception:  # noqa: BLE001
                pass
        if val is None:
            mem_val = self._precompute_mem.get(key)
            if isinstance(mem_val, dict):
                val = dict(mem_val)
        if not isinstance(val, dict):
            return None
        if isinstance(val.get("summary"), str):
            guarded_summary = self._guard_summary(val.get("summary"))
            if guarded_summary != val.get("summary"):
                val["summary"] = guarded_summary
                self._precompute_mem[key] = dict(val)
                if self.query_cache is not None:
                    try:
                        self.query_cache.set(key, val, ttl=self.precompute_ttl_seconds)
                    except Exception:  # noqa: BLE001
                        pass
        return val

    def _build_precompute_answer(self, pre: Dict[str, Any], query: str) -> str:
        summary = self._guard_summary(str((pre or {}).get("summary") or "").strip())
        rels = (pre or {}).get("relations") or []
        lines: List[str] = []
        if summary:
            return summary
        if isinstance(rels, list) and rels:
            rel_lines: List[str] = []
            for t in rels[: self.max_graph_relations]:
                if not isinstance(t, dict):
                    continue
                s = str(t.get("source") or "").strip()
                r = str(t.get("relation") or "").strip()
                o = str(t.get("target") or "").strip()
                if s and r and o:
                    rel_lines.append(f"- {s} -[{r}]-> {o}")
            if rel_lines:
                lang = self._lang_bucket()
                if lang == "en":
                    lines.append("Known graph relations:")
                elif lang == "ko":
                    lines.append("확인된 그래프 관계:")
                else:
                    lines.append("已知图谱关系：")
                lines.extend(rel_lines)
        if not lines:
            lang = self._lang_bucket()
            if lang == "en":
                return f"No structured graph knowledge related to \"{query}\" was found."
            if lang == "ko":
                return f"\"{query}\"와 관련된 구조화된 그래프 정보를 찾지 못했습니다."
            return f"未在知识图谱中检索到与“{query}”相关的结构化信息。"
        return "\n".join(lines)

    def _normalize_graph_payload(self, graph: Dict[str, Any] | None) -> Dict[str, Any]:
        g = graph or {}
        rels = g.get("relations") if isinstance(g.get("relations"), list) else []
        two_hop = g.get("two_hop") if isinstance(g.get("two_hop"), list) else []
        summary = self._guard_summary(g.get("summary") if isinstance(g.get("summary"), str) else "")
        count = int(g.get("count", len(rels)) or 0)
        return {
            "used": bool(g.get("used", count > 0 or bool(summary) or len(two_hop) > 0)),
            "relations": rels,
            "count": count,
            "two_hop": two_hop,
            "summary": summary,
        }

    def _resolve_entity_for_graph(self, query: str, plan: Dict[str, Any]) -> Dict[str, str]:
        planned_entities = plan.get("entities") if isinstance(plan.get("entities"), list) else []
        if planned_entities:
            raw = str(planned_entities[0]).strip()
        elif "的" in query:
            raw = query.split("的")[0].strip()
        else:
            raw = query.strip()
        canonical = normalize_entity(raw or query.strip()) or raw or query.strip()
        used = canonical
        return {"raw": raw, "canonical": canonical, "used_for_graph": used}

    # ------------------------- Rerank & context building -------------------------
    def combine_context(self, vector_docs: Any, graph_nodes: Any) -> Dict[str, Any]:
        return {
            "vector": getattr(vector_docs, "source_nodes", []) if vector_docs is not None else [],
            "graph": getattr(graph_nodes, "source_nodes", []) if graph_nodes is not None else [],
        }

    def rerank(self, vector_docs: Any, graph_nodes: Any) -> Dict[str, Any]:
        """
        目前简单地把图与向量的 source_nodes 合并。
        后续可以在这里加入基于得分或多路召回的重排逻辑。
        """
        context = self.combine_context(vector_docs, graph_nodes)
        context["vector_response"] = vector_docs
        context["graph_response"] = graph_nodes
        return context

    def compress_context(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        对上下文做轻量压缩：按 score 降序后只保留 top N 条，压低 LLM context 且保留最相关。
        """
        def _score(n: Any) -> float:
            return float((getattr(n, "metadata", None) or {}).get("score", 0.0))

        vector_nodes = results.get("vector", []) or []
        graph_nodes = results.get("graph", []) or []
        results["vector"] = sorted(vector_nodes, key=_score, reverse=True)[: self.max_context_chunks]
        results["graph"] = sorted(graph_nodes, key=_score, reverse=True)[: self.max_context_chunks]
        return results

    # ------------------------- Answer synthesis -------------------------
    def llm_synthesis(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        graph_resp = context.get("graph_response")
        vector_resp = context.get("vector_response")

        # 若存在由 ContextBuilder 构建的 llm_context，则优先用 PromptBuilder+主 LLM 生成答案
        llm_context = context.get("llm_context") or ""
        if llm_context.strip():
            prompt = self.prompt_builder.build_prompt(query, llm_context)
            prompt = self._with_lang_instruction(prompt)
            _plen = len(prompt)
            logger.info("[Prompt] len=%d chars, approx_tokens~%d (prefill 与首字延迟正相关)", _plen, _plen // 2)
            resp = self.answer_llm.complete(prompt)
            answer = str(resp)
            # 仍然使用压缩后的 source_nodes 作为引用来源
            source_nodes = context.get("graph") or context.get("vector") or []
        else:
            # 默认优先使用图谱答案，不足时回退向量答案（保持旧行为）
            if graph_resp is not None and str(graph_resp).strip():
                answer = str(graph_resp)
                source_nodes = context.get("graph", [])
            elif vector_resp is not None:
                answer = str(vector_resp)
                source_nodes = context.get("vector", [])
            else:
                answer = ""
                source_nodes = []

        sources = [
            {"text": node.text[:500], "file": node.metadata.get("file_name", "Unknown")}
            for node in (source_nodes or [])
        ]

        # 轻量去重：避免重复句段影响体验
        def _dedupe_sentences(text: str) -> str:
            t = (text or "").strip()
            if not t:
                return t
            parts = re.split(r"(?<=[。！？.!?])\s+", t)
            seen = set()
            out = []
            for p in parts:
                s = (p or "").strip()
                if not s:
                    continue
                key = re.sub(r"\s+", " ", s)
                if key in seen:
                    continue
                seen.add(key)
                out.append(s)
            return " ".join(out).strip()

        answer = _dedupe_sentences(answer)
        if self._should_retry_language(answer):
            answer = _dedupe_sentences(self._rewrite_in_target_language(answer))

        return {
            "answer": answer,
            "sources": sources,
            "graph_context": [],
            "explanation": context.get("graph_explanation"),
            "graph_paths": context.get("graph_paths") or [],
        }

    # ------------------------- Orchestrator entrypoint -------------------------
    def run(self, query: str, mode: str = "hybrid") -> Dict[str, Any]:
        """
        GraphRAG v2 查询编排流程：
          1. 意图识别
          2. 选择检索策略
          3. 多路检索
          4. 重排与上下文压缩
          5. LLM 生成最终答案
        """
        _ensure_event_loop()
        t_start = time.perf_counter()

        normalized_query = query.strip().lower()
        normalized_query = re.sub(r"[?!.]+$", "", normalized_query)
        graph_version = self._graph_version()
        cache_key = self._query_cache_key(normalized_query, graph_version=graph_version)
        # 关闭 Redis 缓存以便调试 GraphRAG 行为

        logger.info("QueryPipeline running with mode=%s, query=%s", mode, query)

        # 新增：Query Planner 负责高层规划（intent / strategy / entities）
        t0 = time.perf_counter()
        plan = self.planner.plan(query)
        planner_ms = (time.perf_counter() - t0) * 1000
        logger.info("Query plan: %s", plan)

        # 兼容旧模式参数：若用户显式传入 mode=vector/graph，则保持旧行为覆盖 planner 的 strategy
        intent = plan.get("intent") or self.detect_query_intent(query)
        if mode in ("vector", "graph"):
            strategy = self.choose_strategy(intent, mode)
        else:
            # 将 planner 的 strategy 映射回旧的检索策略空间
            planner_strategy = plan.get("strategy")
            if planner_strategy in ("vector", "vector_only"):
                strategy = "vector_only"
            elif planner_strategy in ("graph", "graph_traversal"):
                # graph_traversal 目前也先走 graph 查询引擎
                strategy = "graph_only"
            elif planner_strategy == "hybrid":
                # Graph-first: hybrid 先按 vector_only 分支执行（先图后向量回退）
                strategy = "vector_only"
            elif planner_strategy == "llm_only":
                # 问候语等只需要 LLM 场景
                strategy = "llm_only"
            else:
                # 兜底：沿用旧逻辑
                intent = self.detect_query_intent(query)
                strategy = self.choose_strategy(intent, mode)

        logger.info("Detected intent=%s, strategy=%s", intent, strategy)

        # llm_only 兜底路径（保留）
        if strategy == "llm_only":
            t_llm = time.perf_counter()
            resp = self.answer_llm.complete(
                self._with_lang_instruction(
                    self._greeting_prompt(query)
                )
            )
            llm_ms = (time.perf_counter() - t_llm) * 1000
            result = {"answer": str(resp), "sources": [], "graph_context": []}
            if self.query_cache and result.get("answer"):
                try:
                    self.query_cache.set(cache_key, result)
                except Exception:  # noqa: BLE001
                    pass
            total_ms = (time.perf_counter() - t_start) * 1000
            logger.info(
                "[QueryPipeline] planner: %.0fms vector_retrieval: 0ms graph_retrieval: 0ms traversal: 0ms llm_generation: %.0fms total: %.0fms",
                planner_ms, llm_ms, total_ms,
            )
            result["pipeline_latency_ms"] = {
                "planner_ms": round(planner_ms),
                "vector_retrieval_ms": 0,
                "graph_retrieval_ms": 0,
                "traversal_ms": 0,
                "llm_generation_ms": round(llm_ms),
                "total_ms": round(total_ms),
            }
            return result

        # vector_only：强制执行 GraphRAG v2（graph 优先，必要时再走 vector）
        if strategy == "vector_only":
            if intent == "greeting":
                entities: List[str] = []
                print(f">>> [QUERY] entities: {entities}")
                relations: List[str] = []
                triples: List[Dict[str, str]] = []
                print(f">>> [GRAPH] relations: {len(relations)}")
                vector_used = True
                t_vec = time.perf_counter()
                _reset_embed_call_count()
                vector_resp = self.vector_retrieval(query, top_k=1)
                vec_ms = (time.perf_counter() - t_vec) * 1000
                logger.info("[EmbedCall] greeting path embedding calls total: %s", _get_embed_call_count())
                vector_nodes = getattr(vector_resp, "source_nodes", []) or []
                print(">>> [PIPELINE] building context")
                if vector_nodes:
                    _t = (getattr(vector_nodes[0], "text", "") or "").strip().replace("\n", " ")[:300]
                    chunks_block = "[1] " + _t
                else:
                    chunks_block = "None"
                context_str = (
                    "[Knowledge]\nNone\n\n"
                    "[Text Evidence]\n"
                    f"{chunks_block}\n\n"
                    f"Question:\n{query}\n"
                )
                context_tokens = len(context_str) // 2
                print(f">>> [CONTEXT] length: {context_tokens} tokens")
                t_llm = time.perf_counter()
                result = self.llm_synthesis(
                    query,
                    {
                        "llm_context": context_str,
                        "vector": vector_nodes,
                        "graph": [],
                        "graph_paths": [],
                        "graph_explanation": None,
                    },
                )
                llm_ms = (time.perf_counter() - t_llm) * 1000
                chunks_count = 1 if vector_nodes else 0
                result["graph"] = {"used": False, "relations": [], "count": 0}
                result["debug"] = {
                    "context_tokens": context_tokens,
                    "vector_used": vector_used,
                    "chunks_used": chunks_count,
                    "graph_used": False,
                    "graph_relations_count": 0,
                    "answer_mode": "vector",
                    "precompute_hit": False,
                }
                result["debug_relations_count"] = 0
                result["debug_vector_chunks_count"] = chunks_count
                total_ms = (time.perf_counter() - t_start) * 1000
                result["pipeline_latency_ms"] = {
                    "planner_ms": round(planner_ms),
                    "vector_retrieval_ms": round(vec_ms),
                    "graph_retrieval_ms": 0,
                    "traversal_ms": 0,
                    "llm_generation_ms": round(llm_ms),
                    "total_ms": round(total_ms),
                }
                return result

            entity_dbg = self._resolve_entity_for_graph(query, plan)
            entity = entity_dbg["used_for_graph"]
            entities = [entity.strip()] if entity.strip() else []
            print(f">>> [QUERY] entities: {entities}")
            print("=== ENTITY DEBUG ===")
            print(f"raw: {entity_dbg['raw']}")
            print(f"canonical: {entity_dbg['canonical']}")
            print(f"used_for_graph: {entity_dbg['used_for_graph']}")
            print("=== END ===")

            graph_data = self.graph_retrieve_from_entities(entities)
            relations = (graph_data or {}).get("relations") or []
            triples = (graph_data or {}).get("triples") or []
            pre_entity = str((triples[0] or {}).get("source") or entity).strip() if triples else entity
            relations = list(set(relations))
            relations = relations[:12]
            graph_summary = self._build_graph_summary(triples, min_relations=5)
            graph_used = self._graph_quality_ok(len(relations), graph_summary)
            if not graph_used:
                relations = []
            print(f">>> [GRAPH] relations: {len(relations)}")
            precompute_hit = False

            vector_nodes: List[Any] = []
            vec_ms = 0.0
            if graph_used:
                print(">>> [QUERY] vector skipped (graph hit)")
                vector_used = False
            else:
                t_vec = time.perf_counter()
                _reset_embed_call_count()
                vector_resp = self.vector_retrieval(query)
                vec_ms = (time.perf_counter() - t_vec) * 1000
                logger.info("[EmbedCall] vector_only path embedding calls total: %s", _get_embed_call_count())
                vector_nodes = getattr(vector_resp, "source_nodes", []) or []
                print(f">>> [QUERY] vector top_k: {len(vector_nodes)}")
                vector_used = True

            # 压缩表达：A -[REL]- B  ->  A rels: b1, b2
            rel_groups: Dict[str, Dict[str, List[str]]] = {}
            for r in relations:
                # format: "A -[REL]- B"
                m = re.match(r"^(.*)\s-\[(.*)\]-\s(.*)$", r)
                if not m:
                    continue
                a, rel, b = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                rel_groups.setdefault(a, {}).setdefault(rel, []).append(b)

            knowledge_lines: List[str] = []
            for a, rel_map in rel_groups.items():
                for rel, bs in rel_map.items():
                    bs_uniq = list(dict.fromkeys(bs))[:8]
                    verb = {
                        "PROVIDES": "provides",
                        "APPLIES_TO": "applies to",
                    }.get(rel, rel.lower())
                    knowledge_lines.append(f"{a} {verb}: {', '.join(bs_uniq)}")
            knowledge_block = "\n".join(knowledge_lines) if knowledge_lines else "None"

            top_chunks: List[str] = []
            k_chunks = 2 if relations else self.max_context_chunks
            for idx, node in enumerate(vector_nodes[:k_chunks], start=1):
                snippet = (getattr(node, "text", "") or "").strip().replace("\n", " ")
                top_chunks.append(f"[{idx}] {snippet[:300]}")
            chunks_block = "\n".join(top_chunks) if top_chunks else "None"

            print(">>> [PIPELINE] building context")
            context_str = (
                "[Knowledge]\n"
                f"{knowledge_block}\n\n"
                "[Text Evidence]\n"
                f"{chunks_block}\n\n"
                f"Question:\n{query}\n"
            )
            context_tokens = len(context_str) // 2
            # 控制总 token < 400：必要时降级减少 chunk 与知识行数
            if context_tokens > 400:
                chunks_block = "\n".join(top_chunks[:1]) if top_chunks else "None"
                knowledge_block2 = "\n".join(knowledge_lines[:6]) if knowledge_lines else "None"
                context_str = (
                    "[Knowledge]\n"
                    f"{knowledge_block2}\n\n"
                    "[Text Evidence]\n"
                    f"{chunks_block}\n\n"
                    f"Question:\n{query}\n"
                )
                context_tokens = len(context_str) // 2
            print(f">>> [CONTEXT] length: {context_tokens} tokens")

            llm_ms = 0.0
            if graph_used:
                pre = self._get_precompute(pre_entity, graph_version=graph_version)
                if self._is_precompute_valid(pre):
                    precompute_hit = True
                    result = {
                        "answer": self._build_precompute_answer(pre, query),
                        "sources": [],
                        "graph_context": [],
                    }
                else:
                    t_llm = time.perf_counter()
                    result = self.llm_synthesis(
                        query,
                        {
                            "llm_context": context_str,
                            "vector": vector_nodes,
                            "graph": [],
                            "graph_paths": [],
                            "graph_explanation": None,
                        },
                    )
                    llm_ms = (time.perf_counter() - t_llm) * 1000
            else:
                t_llm = time.perf_counter()
                result = self.llm_synthesis(
                    query,
                    {
                        "llm_context": context_str,
                        "vector": vector_nodes,
                        "graph": [],
                        "graph_paths": [],
                        "graph_explanation": None,
                    },
                )
                llm_ms = (time.perf_counter() - t_llm) * 1000

            relations_count = len(triples)
            chunks_count = len(top_chunks)
            result["debug_relations_count"] = relations_count
            result["debug_vector_chunks_count"] = chunks_count
            result["debug_context_tokens"] = context_tokens
            # UI 可视化：graph/debug 字段
            result["graph"] = self._normalize_graph_payload({
                "used": graph_used,
                "relations": triples[: self.max_graph_relations],
                "count": relations_count,
                "two_hop": self._build_graph_2hop(triples)[: self.max_two_hop],
                "summary": graph_summary,
            })
            result["debug"] = {
                "context_tokens": context_tokens,
                "vector_used": vector_used,
                "chunks_used": chunks_count,
                "graph_used": graph_used,
                "graph_relations_count": relations_count,
                "answer_mode": "graph" if graph_used else "vector",
                "precompute_hit": precompute_hit,
                "entity_raw": entity_dbg["raw"],
                "entity_canonical": entity_dbg["canonical"],
                "entity_used_for_graph": entity_dbg["used_for_graph"],
            }

            if self.query_cache and result.get("answer"):
                try:
                    self.query_cache.set(cache_key, result)
                except Exception:  # noqa: BLE001
                    pass

            total_ms = (time.perf_counter() - t_start) * 1000
            logger.info(
                "[QueryPipeline] planner: %.0fms vector_retrieval: %.0fms graph_retrieval: 0ms traversal: 0ms llm_generation: %.0fms total: %.0fms",
                planner_ms, vec_ms, llm_ms, total_ms,
            )
            result["pipeline_latency_ms"] = {
                "planner_ms": round(planner_ms),
                "vector_retrieval_ms": round(vec_ms),
                "graph_retrieval_ms": 0,
                "traversal_ms": 0,
                "llm_generation_ms": round(llm_ms),
                "total_ms": round(total_ms),
            }
            return result

        vector_resp = None
        graph_resp = None
        traversal_nodes: List[Dict[str, Any]] = []
        traversal_edges: List[Dict[str, Any]] = []
        vec_ms = graph_ms = trav_ms = 0.0

        if strategy in ("vector_only", "hybrid"):
            t_vec = time.perf_counter()
            _reset_embed_call_count()
            vector_resp = self.vector_retrieval(query)
            vec_ms = (time.perf_counter() - t_vec) * 1000
            logger.info("[EmbedCall] full path vector_retrieval embedding calls total: %s", _get_embed_call_count())

        if strategy in ("graph_only", "hybrid"):
            t_graph = time.perf_counter()
            try:
                graph_resp = self.graph_retrieval(query)
            except Exception as e:  # noqa: BLE001
                logger.error("Graph retrieval failed: %s", e)
                if strategy == "graph_only":
                    raise
            graph_ms = (time.perf_counter() - t_graph) * 1000

        # graph_traversal: 使用 GraphTraversalEngine 获取子图上下文
        if plan.get("strategy") == "graph_traversal":
            t_trav = time.perf_counter()
            entities = plan.get("entities") or []
            merged_nodes: Dict[Any, Any] = {}
            merged_edges: List[Any] = []
            for ent in entities:
                subgraph = self.traversal_engine.traverse(ent, max_hops=2)
                for n in subgraph.get("nodes", []):
                    merged_nodes[n["id"]] = n
                merged_edges.extend(subgraph.get("edges", []))
            traversal_nodes = list(merged_nodes.values())
            traversal_edges = merged_edges
            trav_ms = (time.perf_counter() - t_trav) * 1000
            logger.info(
                "Graph traversal context merged: entities=%s, nodes=%s, edges=%s",
                entities,
                len(traversal_nodes),
                len(traversal_edges),
            )

        # 从遍历结果中提取三元组，用于关系解释
        graph_paths: List[Dict[str, str]] = []
        if traversal_nodes and traversal_edges:
            graph_paths = extract_triples(traversal_nodes, traversal_edges)

        ranked = self.rerank(vector_resp, graph_resp)
        compact_context = self.compress_context(ranked)

        # 使用 ContextBuilder 生成供 LLM 使用的文本上下文，目前主要用于答案生成
        built_context_str = self.context_builder.build_context(
            query,
            vector_resp,
            graph_resp,
            traversal_nodes,
            traversal_edges,
        )
        logger.info(
            "Built LLM context: len=%s, traversal_nodes=%s, traversal_edges=%s",
            len(built_context_str),
            len(traversal_nodes),
            len(traversal_edges),
        )
        compact_context["llm_context"] = built_context_str

        # 将结构化的 graph_paths 挂到上下文中，供响应和未来前端使用
        compact_context["graph_paths"] = graph_paths
        # explanation 目前由主答案 prompt 隐式承担，这里保留字段以保持兼容
        compact_context["graph_explanation"] = None

        context = compact_context
        t_llm = time.perf_counter()
        result = self.llm_synthesis(query, context)
        llm_ms = (time.perf_counter() - t_llm) * 1000
        if self.query_cache and result.get("answer"):
            try:
                self.query_cache.set(cache_key, result)
            except Exception:  # noqa: BLE001
                pass
        total_ms = (time.perf_counter() - t_start) * 1000
        logger.info(
            "[QueryPipeline] planner: %.0fms vector_retrieval: %.0fms graph_retrieval: %.0fms traversal: %.0fms llm_generation: %.0fms total: %.0fms",
            planner_ms, vec_ms, graph_ms, trav_ms, llm_ms, total_ms,
        )
        result["pipeline_latency_ms"] = {
            "planner_ms": round(planner_ms),
            "vector_retrieval_ms": round(vec_ms),
            "graph_retrieval_ms": round(graph_ms),
            "traversal_ms": round(trav_ms),
            "llm_generation_ms": round(llm_ms),
            "total_ms": round(total_ms),
        }
        return result

    def run_stream(self, query: str, mode: str = "hybrid"):
        """
        与 run() 逻辑一致，但 LLM 部分改为流式输出；每次 yield 一个 dict，便于序列化为 NDJSON。
        yield 事件: {"type": "chunk", "text": "..."} 或 {"type": "done", "first_token_ms", "total_ms", "answer", "sources", "pipeline_latency_ms"}。
        """
        _ensure_event_loop()
        t_start = time.perf_counter()
        normalized_query = query.strip().lower()
        normalized_query = re.sub(r"[?!.]+$", "", normalized_query)
        graph_version = self._graph_version()
        cache_key = self._query_cache_key(normalized_query, graph_version=graph_version)
        # 关闭 Redis 缓存以便调试 GraphRAG 行为

        plan = self.planner.plan(query)
        planner_ms = (time.perf_counter() - (t_start)) * 1000
        intent = plan.get("intent") or self.detect_query_intent(query)
        if mode in ("vector", "graph"):
            strategy = self.choose_strategy(intent, mode)
        else:
            planner_strategy = plan.get("strategy")
            if planner_strategy in ("vector", "vector_only"):
                strategy = "vector_only"
            elif planner_strategy in ("graph", "graph_traversal"):
                strategy = "graph_only"
            elif planner_strategy == "hybrid":
                # Graph-first: hybrid 先按 vector_only 分支执行（先图后向量回退）
                strategy = "vector_only"
            elif planner_strategy == "llm_only":
                strategy = "llm_only"
            else:
                intent = self.detect_query_intent(query)
                strategy = self.choose_strategy(intent, mode)

        if intent == "greeting" or strategy == "llm_only":
            graph_payload = {"used": False, "relations": [], "count": 0}
            vec_ms_g = 0
            if intent == "greeting":
                t_vec = time.perf_counter()
                _reset_embed_call_count()
                try:
                    vr_g = self.vector_retrieval(query, top_k=1)
                    vec_ms_g = (time.perf_counter() - t_vec) * 1000
                    vnodes_g = getattr(vr_g, "source_nodes", []) or []
                except Exception:  # noqa: BLE001
                    vnodes_g = []
                if vnodes_g:
                    _tg = (getattr(vnodes_g[0], "text", "") or "").strip().replace("\n", " ")[:300]
                    chunks_block_g = "[1] " + _tg
                else:
                    chunks_block_g = "None"
                ctx_g = (
                    "[Knowledge]\nNone\n\n[Text Evidence]\n"
                    f"{chunks_block_g}\n\nQuestion:\n{query}\n"
                )
                dbg = {
                    "context_tokens": max(1, len(ctx_g) // 2),
                    "vector_used": True,
                    "chunks_used": 1 if vnodes_g else 0,
                    "graph_used": False,
                    "graph_relations_count": 0,
                    "answer_mode": "vector",
                    "precompute_hit": False,
                }
            else:
                _gp = self._greeting_prompt(query)
                dbg = {
                    "context_tokens": max(1, len(_gp) // 2),
                    "vector_used": False,
                    "chunks_used": 0,
                    "graph_used": False,
                    "graph_relations_count": 0,
                    "answer_mode": "vector",
                    "precompute_hit": False,
                }
            t_llm = time.perf_counter()
            resp = self.answer_llm.complete(
                self._with_lang_instruction(
                    self._greeting_prompt(query)
                )
            )
            llm_ms = (time.perf_counter() - t_llm) * 1000
            total_ms = (time.perf_counter() - t_start) * 1000
            answer = str(resp)
            yield {
                "type": "done",
                "answer": answer,
                "sources": [],
                "graph": graph_payload,
                "debug": dbg,
                "pipeline_latency_ms": {
                    "planner_ms": round(planner_ms),
                    "vector_retrieval_ms": round(vec_ms_g),
                    "graph_retrieval_ms": 0,
                    "traversal_ms": 0,
                    "llm_generation_ms": round(llm_ms),
                    "total_ms": round(total_ms),
                    "prompt_chars": 0,
                    "prompt_tokens": 0,
                },
                "first_token_ms": round(llm_ms),
                "total_ms": round(total_ms),
            }
            return

        if strategy == "vector_only":
            entity_dbg = self._resolve_entity_for_graph(query, plan)
            ent = entity_dbg["used_for_graph"]
            print("=== ENTITY DEBUG ===")
            print(f"raw: {entity_dbg['raw']}")
            print(f"canonical: {entity_dbg['canonical']}")
            print(f"used_for_graph: {entity_dbg['used_for_graph']}")
            print("=== END ===")
            graph_data = self.graph_retrieve_from_entities([ent]) if ent else {"relations": [], "triples": []}
            triples = (graph_data or {}).get("triples") or []
            pre_entity = str((triples[0] or {}).get("source") or ent).strip() if triples else ent
            rels = (graph_data or {}).get("relations") or []
            rels = list(dict.fromkeys(rels))[: self.max_graph_relations]
            graph_summary = self._build_graph_summary(triples, min_relations=5)
            graph_used = self._graph_quality_ok(len(rels), graph_summary)
            precompute_hit = False

            vec_ms = 0.0
            if graph_used:
                # graph-first hit: skip vector context
                rel_groups: Dict[str, Dict[str, List[str]]] = {}
                for r in rels:
                    m = re.match(r"^(.*)\s-\[(.*)\]-\s(.*)$", r)
                    if not m:
                        continue
                    a, rel, b = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                    rel_groups.setdefault(a, {}).setdefault(rel, []).append(b)
                knowledge_lines: List[str] = []
                for a, rel_map in rel_groups.items():
                    for rel, bs in rel_map.items():
                        bs_uniq = list(dict.fromkeys(bs))[:8]
                        verb = {"PROVIDES": "provides", "APPLIES_TO": "applies to"}.get(rel, rel.lower())
                        knowledge_lines.append(f"{a} {verb}: {', '.join(bs_uniq)}")
                knowledge_block = "\n".join(knowledge_lines) if knowledge_lines else "None"
                built_context_str = (
                    "Answer ONLY based on the provided knowledge graph.\n"
                    "Do not use external knowledge.\n"
                    "Do not hallucinate.\n\n"
                    "[Knowledge]\n"
                    f"{knowledge_block}\n\n"
                    "[Text Evidence]\nNone\n\n"
                    f"Question:\n{query}\n"
                )
                sources = []
                vector_used = False
                chunks_used = 0
            else:
                t_vec = time.perf_counter()
                _reset_embed_call_count()
                vector_resp = self.vector_retrieval(query)
                vec_ms = (time.perf_counter() - t_vec) * 1000
                ranked = self.rerank(vector_resp, None)
                compact_context = self.compress_context(ranked)
                built_context_str = self.context_builder.build_context(query, vector_resp, None, [], [])
                compact_context["llm_context"] = built_context_str
                compact_context["graph_paths"] = []
                compact_context["graph_explanation"] = None
                source_nodes = compact_context.get("vector") or []
                sources = [{"text": getattr(n, "text", "")[:500], "file": getattr(n, "metadata", {}).get("file_name", "Unknown")} for n in source_nodes]
                vector_used = True
                chunks_used = len(source_nodes)

            graph_payload = {
                "used": graph_used,
                "relations": triples[: self.max_graph_relations],
                "count": len(triples),
                "two_hop": self._build_graph_2hop(triples)[: self.max_two_hop],
                "summary": graph_summary,
            }
            graph_payload = self._normalize_graph_payload(graph_payload)

            debug_payload = {
                "context_tokens": max(1, len(built_context_str) // 2),
                "vector_used": vector_used,
                "chunks_used": chunks_used,
                "graph_used": graph_used,
                "graph_relations_count": len(triples),
                "answer_mode": "graph" if graph_used else "vector",
                "precompute_hit": False,
                "entity_raw": entity_dbg["raw"],
                "entity_canonical": entity_dbg["canonical"],
                "entity_used_for_graph": entity_dbg["used_for_graph"],
            }
            prompt = self.prompt_builder.build_prompt(query, built_context_str)
            prompt = self._with_lang_instruction(prompt)
            _plen = len(prompt)
            llm_ms = 0.0
            first_token_ms: float | None = None
            answer = ""
            if graph_used:
                pre = self._get_precompute(pre_entity, graph_version=graph_version)
                if self._is_precompute_valid(pre):
                    precompute_hit = True
                    answer = self._build_precompute_answer(pre, query)
                    first_token_ms = 0.0
                    debug_payload["precompute_hit"] = True
                else:
                    logger.info("[Prompt] len=%d chars, approx_tokens~%d (prefill 与首字延迟正相关)", _plen, _plen // 2)
                    t_llm = time.perf_counter()
                    full_parts: List[str] = []
                    for chunk in self.answer_llm.stream_complete(prompt):
                        # 只发最终文本，丢弃 thinking（Ollama 已设 thinking=False，此处做防御性过滤）
                        if getattr(chunk, "additional_kwargs", {}).get("thinking_delta") and not (getattr(chunk, "delta", None) or getattr(chunk, "text", "")):
                            continue
                        delta = getattr(chunk, "delta", None) or getattr(chunk, "text", "") or ""
                        if isinstance(delta, str) and delta.strip():
                            if first_token_ms is None:
                                first_token_ms = (time.perf_counter() - t_llm) * 1000
                            full_parts.append(delta)
                            yield {"type": "chunk", "text": delta}
                    llm_ms = (time.perf_counter() - t_llm) * 1000
                    answer = "".join(full_parts)
            else:
                logger.info("[Prompt] len=%d chars, approx_tokens~%d (prefill 与首字延迟正相关)", _plen, _plen // 2)
                t_llm = time.perf_counter()
                full_parts = []
                for chunk in self.answer_llm.stream_complete(prompt):
                    # 只发最终文本，丢弃 thinking（Ollama 已设 thinking=False，此处做防御性过滤）
                    if getattr(chunk, "additional_kwargs", {}).get("thinking_delta") and not (getattr(chunk, "delta", None) or getattr(chunk, "text", "")):
                        continue
                    delta = getattr(chunk, "delta", None) or getattr(chunk, "text", "") or ""
                    if isinstance(delta, str) and delta.strip():
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - t_llm) * 1000
                        full_parts.append(delta)
                        yield {"type": "chunk", "text": delta}
                llm_ms = (time.perf_counter() - t_llm) * 1000
                answer = "".join(full_parts)
            total_ms = (time.perf_counter() - t_start) * 1000
            if self.query_cache and answer:
                try:
                    self.query_cache.set(cache_key, {"answer": answer, "sources": sources, "graph_context": [], "graph_paths": []})
                except Exception:  # noqa: BLE001
                    pass
            lat = {"planner_ms": round(planner_ms), "vector_retrieval_ms": round(vec_ms), "graph_retrieval_ms": 0, "traversal_ms": 0, "llm_generation_ms": round(llm_ms), "total_ms": round(total_ms), "first_token_ms": round(first_token_ms or 0), "prompt_chars": _plen, "prompt_tokens": _plen // 2}
            yield {"type": "done", "answer": answer, "sources": sources, "pipeline_latency_ms": lat, "first_token_ms": round(first_token_ms or 0), "total_ms": round(total_ms), "graph": graph_payload, "debug": debug_payload}
            return

        vec_ms = graph_ms = trav_ms = 0.0
        vector_resp = None
        if strategy in ("vector_only", "hybrid"):
            t_vec = time.perf_counter()
            _reset_embed_call_count()
            vector_resp = self.vector_retrieval(query)
            vec_ms = (time.perf_counter() - t_vec) * 1000
        graph_resp = None
        if strategy in ("graph_only", "hybrid"):
            t_graph = time.perf_counter()
            try:
                graph_resp = self.graph_engine.get_query_engine().query(query)
            except Exception:  # noqa: BLE001
                pass
            graph_ms = (time.perf_counter() - t_graph) * 1000
        traversal_nodes = []
        traversal_edges = []
        if plan.get("strategy") == "graph_traversal":
            t_trav = time.perf_counter()
            entities = plan.get("entities") or []
            merged_nodes = {}
            merged_edges = []
            for ent in entities:
                subgraph = self.traversal_engine.traverse(ent, max_hops=2)
                for n in subgraph.get("nodes", []):
                    merged_nodes[n["id"]] = n
                merged_edges.extend(subgraph.get("edges", []))
            traversal_nodes = list(merged_nodes.values())
            traversal_edges = merged_edges
            trav_ms = (time.perf_counter() - t_trav) * 1000
        graph_paths = extract_triples(traversal_nodes, traversal_edges) if traversal_nodes and traversal_edges else []
        ranked = self.rerank(vector_resp, graph_resp)
        compact_context = self.compress_context(ranked)
        built_context_str = self.context_builder.build_context(query, vector_resp, graph_resp, traversal_nodes, traversal_edges)
        compact_context["llm_context"] = built_context_str
        compact_context["graph_paths"] = graph_paths
        source_nodes = compact_context.get("graph") or compact_context.get("vector") or []
        sources = [{"text": getattr(n, "text", "")[:500], "file": getattr(n, "metadata", {}).get("file_name", "Unknown")} for n in source_nodes]
        prompt = self.prompt_builder.build_prompt(query, built_context_str)
        prompt = self._with_lang_instruction(prompt)
        _plen = len(prompt)
        logger.info("[Prompt] len=%d chars, approx_tokens~%d (prefill 与首字延迟正相关)", _plen, _plen // 2)
        t_llm = time.perf_counter()
        first_token_ms = None
        full_parts = []
        for chunk in self.answer_llm.stream_complete(prompt):
            if getattr(chunk, "additional_kwargs", {}).get("thinking_delta") and not (getattr(chunk, "delta", None) or getattr(chunk, "text", "")):
                continue
            delta = getattr(chunk, "delta", None) or getattr(chunk, "text", "") or ""
            if isinstance(delta, str) and delta.strip():
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t_llm) * 1000
                full_parts.append(delta)
                yield {"type": "chunk", "text": delta}
        llm_ms = (time.perf_counter() - t_llm) * 1000
        total_ms = (time.perf_counter() - t_start) * 1000
        answer = "".join(full_parts)
        if self.query_cache and answer:
            try:
                self.query_cache.set(cache_key, {"answer": answer, "sources": sources, "graph_context": [], "graph_paths": graph_paths})
            except Exception:  # noqa: BLE001
                    pass
        lat = {"planner_ms": round(planner_ms), "vector_retrieval_ms": round(vec_ms), "graph_retrieval_ms": round(graph_ms), "traversal_ms": round(trav_ms), "llm_generation_ms": round(llm_ms), "total_ms": round(total_ms), "first_token_ms": round(first_token_ms or 0), "prompt_chars": _plen, "prompt_tokens": _plen // 2}
        _src = compact_context.get("graph") or compact_context.get("vector") or []
        _vused = bool(
            vector_resp is not None and len(getattr(vector_resp, "source_nodes", []) or []) > 0
        )
        if graph_paths:
            rels = graph_paths[: self.max_graph_relations]
            graph_payload_h = {
                "used": len(rels) > 0,
                "relations": rels,
                "count": len(graph_paths),
            }
            _summary = self._build_graph_summary(rels, min_relations=5)
            _two_hop = self._build_graph_2hop(rels)[: self.max_two_hop]
            if _summary is not None:
                graph_payload_h["summary"] = _summary
            if _two_hop:
                graph_payload_h["two_hop"] = _two_hop
        else:
            ent = None
            if isinstance(plan.get("entities"), list) and plan.get("entities"):
                ent = str(plan.get("entities")[0]).strip()
            if not ent:
                ent = query.split("的")[0].strip() if "的" in query else query.strip()
            graph_data = self.graph_retrieve_from_entities([ent]) if ent else {"relations": [], "triples": []}
            triples = (graph_data or {}).get("triples") or []
            graph_payload_h = {
                "used": len(triples) > 0,
                "relations": triples[: self.max_graph_relations],
                "count": len(triples),
                "two_hop": self._build_graph_2hop(triples)[: self.max_two_hop],
                "summary": self._build_graph_summary(triples, min_relations=5),
            }
        graph_payload_h = self._normalize_graph_payload(graph_payload_h)
        debug_payload_h = {
            "context_tokens": max(1, len(built_context_str) // 2),
            "vector_used": _vused,
            "chunks_used": len(_src),
            "graph_used": bool(graph_payload_h.get("used")),
            "graph_relations_count": int(graph_payload_h.get("count", 0) or 0),
            "answer_mode": "graph" if bool(graph_payload_h.get("used")) else "vector",
            "precompute_hit": False,
        }
        yield {
            "type": "done",
            "answer": answer,
            "sources": sources,
            "graph": graph_payload_h,
            "debug": debug_payload_h,
            "pipeline_latency_ms": lat,
            "first_token_ms": round(first_token_ms or 0),
            "total_ms": round(total_ms),
        }


