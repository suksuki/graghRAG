"""
GraphEngine — Neo4j 知识图谱引擎

优化点：
  1. 图抽取使用专用小模型（EXTRACTION_MODEL），查询使用主模型（LLM_MODEL）
  2. 增量索引：跳过已写入 Neo4j 的文件
  3. 支持并发抽取（num_workers 可配置）
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from llama_index.core import PropertyGraphIndex, Settings
from llama_index.core.graph_stores.types import (
    KG_NODES_KEY,
    KG_RELATIONS_KEY,
    EntityNode,
    Relation,
)
from llama_index.core.indices.property_graph.transformations import SimpleLLMPathExtractor
from llama_index.core.schema import BaseNode, MetadataMode
from llama_index.core.indices.property_graph.utils import default_parse_triplets_fn
from llama_index.core.prompts import PromptTemplate
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from configs.config import settings

logger = logging.getLogger(__name__)

# 无括号但「恰好两段英文逗号、三段文本」→ 包成 (s,p,o) 供 default_parse_triplets_fn 识别
_BARE_TRIPLET_LINE = re.compile(r"^[^,]+,\s*[^,]+,\s*[^,]+$")


def _normalize_triplet_response_for_parser(response: str) -> str:
    """全角括号、行内中文逗号 → 半角；无括号的三元组行自动加括号。"""
    if not (response and response.strip()):
        return response or ""
    lines: list[str] = []
    for raw in response.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.lstrip().startswith(("(", "（")):
            s = s.replace("（", "(").replace("）", ")")
            if "，" in s:
                s = s.replace("，", ",")
        else:
            s_try = s.replace("，", ",") if "，" in s else s
            if _BARE_TRIPLET_LINE.match(s_try) and s_try.count(",") == 2:
                s = f"({s_try.strip()})"
            else:
                s = s_try
        lines.append(s)
    return "\n".join(lines)


def _parse_kg_triplets_with_log(response: str, max_length: int = 128):
    """
    SimpleLLMPathExtractor 使用 default_parse_triplets_fn：只认
    每行一条 (主语, 谓语, 宾语)，且三段之间必须是英文逗号 ,。
    自定义 prompt 若让模型输出 JSON 或散文，解析结果恒为 0。
    """
    normalized = _normalize_triplet_response_for_parser(response)
    triples = default_parse_triplets_fn(normalized, max_length=max_length)
    preview = (normalized or "").strip().replace("\n", " | ")[:450]
    logger.info("KG LLM raw (trunc): %s", preview)
    logger.info("KG triplet parsed: count=%s sample=%s", len(triples), triples[:3])
    print(f">>> [GRAPH] triplet_parse: count={len(triples)} sample={triples[:2]!r}")
    return triples


# 仅用于 lexical fallback 写入 Neo4j 属性，便于查询降权 / 过滤（LLM 路径一般无此键，可按 coalesce 当 1.0）
KG_FALLBACK_CONFIDENCE = 0.3
KG_LLM_CONFIDENCE = 1.0

_KG_FB_STOPWORDS_ZH = frozenset(
    {"是", "的", "了", "在", "和", "与", "为", "及", "提供", "包括", "以及", "一个", "这种"}
)
_KG_FB_STOPWORDS_EN = frozenset(
    {
        "is",
        "are",
        "was",
        "were",
        "provides",
        "provide",
        "includes",
        "include",
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
    }
)


def _fallback_part_keep(p: str) -> bool:
    if len(p) < 2:
        return False
    pl = p.lower()
    if pl in _KG_FB_STOPWORDS_EN or p in _KG_FB_STOPWORDS_ZH:
        return False
    return True


def _fallback_triplets_from_text(text: str) -> List[Tuple[str, str, str]]:
    """LLM 未产出可解析三元组时，用语块拼弱 RELATED_TO 边，保证图可写、UI 不空。"""
    if not text or not str(text).strip():
        return []
    s = str(text)
    # 勿用 [\u4e00-\u9fffA-Za-z0-9]+：会把「中文+数字」整句粘成一项
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9]{2,}|\d{4,}", s)
    parts = [p for p in parts if _fallback_part_keep(p)]
    if len(parts) >= 3:
        p0, p1, p2 = parts[0], parts[1], parts[2]
        chain: List[Tuple[str, str, str]] = []
        if p0 != p1:
            chain.append((p0, "RELATED_TO", p1))
        if p1 != p2:
            chain.append((p1, "RELATED_TO", p2))
        if chain:
            return chain
    if len(parts) >= 2:
        a, b = parts[0], parts[1]
        if a != b:
            return [(a, "RELATED_TO", b)]
    if len(parts) == 1 and len(parts[0]) > 8:
        p = parts[0]
        if re.fullmatch(r"[\u4e00-\u9fff]+", p):
            mid = max(3, len(p) // 2)
            return [(p[:mid], "RELATED_TO", p[mid:])]
    cjk_only = re.sub(r"[^\u4e00-\u9fff]", "", s)
    if len(cjk_only) >= 4:
        mid = max(2, len(cjk_only) // 2)
        a, b = cjk_only[:mid], cjk_only[mid:]
        if a != b:
            return [(a, "RELATED_TO", b)]
    return []


def _tag_llm_triplet_provenance(
    entity_nodes: Sequence[Any], relations: Sequence[Any]
) -> None:
    """LLM 主路径显式打标，与 fallback 对称，便于统计与调权。"""
    for n in entity_nodes:
        props = getattr(n, "properties", None)
        if not isinstance(props, dict):
            continue
        if props.get("kg_source") == "fallback":
            continue
        props.setdefault("kg_source", "llm")
        props.setdefault("kg_confidence", KG_LLM_CONFIDENCE)
    for rel in relations:
        props = getattr(rel, "properties", None)
        if not isinstance(props, dict):
            continue
        if props.get("kg_source") == "fallback":
            continue
        props.setdefault("kg_source", "llm")
        props.setdefault("kg_confidence", KG_LLM_CONFIDENCE)


class TripletExtractorWithFallback(SimpleLLMPathExtractor):
    """在 SimpleLLMPathExtractor 之后：若本 chunk 无节点/关系，则套用语块 fallback。"""

    async def _aextract(self, node: BaseNode) -> BaseNode:
        out = await super()._aextract(node)
        kn = out.metadata.get(KG_NODES_KEY) or []
        kr = out.metadata.get(KG_RELATIONS_KEY) or []
        if kn or kr:
            _tag_llm_triplet_provenance(kn, kr)
        if not getattr(settings, "KG_LEXICAL_FALLBACK", True):
            return out
        if kn or kr:
            return out
        text = out.get_content(metadata_mode=MetadataMode.LLM)
        trips = _fallback_triplets_from_text(text)
        if not trips:
            return out
        logger.warning(
            "KG LLM produced no triplets for a chunk; using lexical fallback %s",
            trips[0],
        )
        print(f">>> [GRAPH] lexical_fallback: {trips!r}")
        base_md = out.metadata.copy()
        # 与 LLM 边区分，供 Cypher 过滤 / 检索降权，例如 WHERE coalesce(r.kg_confidence, 1.0) > 0.5
        fb_md = {
            **base_md,
            "kg_source": "fallback",
            "kg_confidence": KG_FALLBACK_CONFIDENCE,
        }
        existing_nodes: list[Any] = []
        existing_relations: list[Any] = []
        for subj, rel, obj in trips:
            subj_node = EntityNode(name=subj, properties=fb_md)
            obj_node = EntityNode(name=obj, properties=fb_md)
            rel_node = Relation(
                label=rel,
                source_id=subj_node.id,
                target_id=obj_node.id,
                properties=fb_md,
            )
            existing_nodes.extend([subj_node, obj_node])
            existing_relations.append(rel_node)
        out.metadata[KG_NODES_KEY] = existing_nodes
        out.metadata[KG_RELATIONS_KEY] = existing_relations
        return out


class GraphEngine:
    def __init__(self):
        # 主模型：对话 / 查询。显式 context_window 避免 client.show() 冷启动；thinking=False 去掉思考输出以降低延迟。
        _ctx = getattr(settings, "LLM_NUM_CTX", None) or 2048
        _num_predict = getattr(settings, "LLM_NUM_PREDICT", None) or 64
        _ollama_kw = {
            "request_timeout": settings.REQUEST_TIMEOUT,
            "context_window": _ctx,
            "additional_kwargs": {
                "num_ctx": _ctx,
                "num_predict": _num_predict,
                "temperature": 0,
            },
            "keep_alive": "30m",
            "thinking": False,  # 禁用 thinking 输出，首字更快、无干扰
        }
        self.llm = Ollama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            **_ollama_kw
        )
        # 抽取模型：prompt+few-shot 较长，ctx 略放大；num_predict 避免多行三元组被截断
        self.extraction_llm = Ollama(
            model=settings.EXTRACTION_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.EXTRACTION_TIMEOUT,
            context_window=2048,
            additional_kwargs={"num_ctx": 2048, "num_predict": 256, "temperature": 0},
            keep_alive="30m",
            thinking=False,
        )
        self.embed_model = OllamaEmbedding(
            model_name=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            request_timeout=settings.REQUEST_TIMEOUT
        )

        Settings.llm = self.llm
        Settings.embed_model = self.embed_model

        self.graph_store = Neo4jPropertyGraphStore(
            username=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
            url=settings.NEO4J_URI,
        )

    # ------------------------------------------------------------------
    # 增量索引：获取 Neo4j 中已有的文件名集合
    # ------------------------------------------------------------------
    def get_graph_ingest_state(self) -> Dict[str, Optional[str]]:
        """
        返回 :IngestedFile 上已记录的「图索引完成」状态。
        key = file_name, value = content_hash（无此属性时为 None，表示旧数据未记录 hash）。
        """
        try:
            with self.graph_store._driver.session() as session:
                result = session.run(
                    "MATCH (f:IngestedFile) WHERE f.file_name IS NOT NULL "
                    "RETURN f.file_name AS fn, f.content_hash AS h"
                )
                out: Dict[str, Optional[str]] = {}
                for record in result:
                    fn = record.get("fn")
                    if not fn:
                        continue
                    h = record.get("h")
                    if isinstance(h, str) and h.strip():
                        out[str(fn)] = h.strip()
                    else:
                        out[str(fn)] = None
                return out
        except Exception as e:
            logger.warning("Could not query IngestedFile state from Neo4j: %s", e)
            return {}

    def get_indexed_files(self) -> set:
        """
        返回已有 :IngestedFile 标记的文件名（与 get_graph_ingest_state().keys() 一致）。
        增量「是否需要建图」请用 get_graph_ingest_state + 磁盘文件 hash 比对（见 ingestion）。
        """
        return set(self.get_graph_ingest_state().keys())

    # ------------------------------------------------------------------
    # 图索引构建
    # ------------------------------------------------------------------
    def _score_chunk_text(self, text: str) -> int:
        t = (text or "").strip()
        if not t:
            return 0
        s = 0
        if any(k in t for k in ("产品", "平台", "系统")):
            s += 2
        if re.search(r"\b[A-Za-z]{3,}\b", t):
            s += 2
        if any(k in t for k in ("应用", "行业", "金融", "政府")):
            s += 1
        if len(t) > 50:
            s += 1
        return s

    def _select_high_value_nodes(self, nodes: list[Any], top_k: int = 5) -> list[Any]:
        scored: list[tuple[int, Any]] = []
        seen: set[str] = set()
        for node in nodes:
            text = (getattr(node, "text", "") or "").strip()
            if not text:
                continue
            # 去重：对前缀做归一化，避免重复页头/模板块反复送 LLM
            key = re.sub(r"\s+", " ", text[:80]).lower()
            if key in seen:
                continue
            seen.add(key)
            scored.append((self._score_chunk_text(text), node))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:top_k]]

    def create_index(self, nodes, num_workers: int = 1, max_paths_per_chunk: int = 2):
        """
        受控 LLM 抽取（轻量配置）写入 Neo4j。
        - num_workers 固定 1
        - max_paths_per_chunk 固定 2
        """
        if not nodes:
            logger.info("No new nodes to index into Neo4j, skipping graph extraction.")
            print(">>> [GRAPH] create_index called with 0 nodes, skip.")
            return None

        n = len(nodes)
        print(f">>> [GRAPH] create_index received nodes: {n}")
        logger.info(
            "Graph ingestion starting (LLM-LIGHT): nodes=%s, workers=1, max_paths_per_chunk=2",
            n,
        )
        nodes = self._select_high_value_nodes(list(nodes), top_k=5)
        logger.info("Graph high-value node selection: selected=%s", len(nodes))

        # Neo4j property graph 不接受嵌套 map 作为属性；仅保留稳定且原子化的 metadata
        safe_nodes = []
        for node in nodes:
            md = getattr(node, "metadata", {}) or {}
            safe_md = {}
            for k in ("file_name", "doc_id", "source", "content_sha256"):
                v = md.get(k)
                if isinstance(v, (str, int, float, bool)) and v is not None:
                    safe_md[k] = v
            try:
                node.metadata = safe_md
            except Exception:  # noqa: BLE001
                pass
            safe_nodes.append(node)

        # 与 default_parse_triplets_fn 对齐；保留 {max_knowledge_triplets} / {text} 供 LlamaIndex 注入
        extract_prompt = PromptTemplate(
            "You are a knowledge graph extraction system.\n\n"
            "Your task is to extract knowledge triplets from the given text.\n\n"
            "=====================\n"
            "STRICT OUTPUT RULES\n"
            "=====================\n\n"
            "1. Output ONLY knowledge triplets (at most {max_knowledge_triplets} lines).\n"
            "2. One triplet per line.\n"
            "3. Each line MUST be in the exact format:\n"
            "   (subject, predicate, object)\n"
            "4. Use ONLY ASCII comma \",\" as separator.\n"
            "5. DO NOT use Chinese comma \"，\".\n"
            "6. DO NOT output JSON.\n"
            "7. DO NOT output explanations.\n"
            "8. DO NOT output headings (e.g. \"Here are the results\").\n"
            "9. DO NOT output empty lines.\n"
            "10. Predicate should be SHORT and preferably in English "
            "(e.g. IS_A, LOCATED_IN, PROVIDES, APPLIES_TO, USED_BY).\n"
            "11. If the text contains any entities, you MUST output at least ONE triplet.\n\n"
            "=====================\n"
            "EXAMPLES\n"
            "=====================\n\n"
            "Text:\n"
            "阿里巴巴是一家中国科技公司，总部在杭州\n\n"
            "Output:\n"
            "(阿里巴巴, IS_A, 科技公司)\n"
            "(阿里巴巴, LOCATED_IN, 杭州)\n\n"
            "---\n\n"
            "Text:\n"
            "Apple is a company based in California.\n\n"
            "Output:\n"
            "(Apple, IS_A, company)\n"
            "(Apple, LOCATED_IN, California)\n\n"
            "---\n\n"
            "Text:\n"
            "Acme Corp provides a risk platform for banks.\n\n"
            "Output:\n"
            "(Acme Corp, PROVIDES, risk platform)\n"
            "(risk platform, USED_BY, banks)\n\n"
            "=====================\n"
            "INPUT\n"
            "=====================\n\n"
            "Text:\n"
            "{text}\n\n"
            "=====================\n"
            "OUTPUT\n"
            "=====================\n"
        )

        kg_extractor = TripletExtractorWithFallback(
            llm=self.extraction_llm,
            extract_prompt=extract_prompt,
            parse_fn=_parse_kg_triplets_with_log,
            max_paths_per_chunk=2,
            num_workers=1,
        )

        # 写入前后统计：区分「抽取失败」与「写入失败」
        try:
            with self.graph_store._driver.session() as session:  # type: ignore[attr-defined]
                res = session.run(
                    "MATCH (e:Entity) RETURN count(e) AS c"
                )
                ent_before = int(res.single()["c"])
                res2 = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
                rel_before = int(res2.single()["c"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Neo4j pre-count failed (continuing): %s", e)
            ent_before = rel_before = -1

        PropertyGraphIndex(
            nodes=safe_nodes,
            property_graph_store=self.graph_store,
            kg_extractors=[kg_extractor],
            llm=self.extraction_llm,
            embed_model=self.embed_model,
            show_progress=False,
        )

        # file marker for incremental graph ingestion
        indexed_files: set[str] = set()
        for node in safe_nodes:
            md = getattr(node, "metadata", {}) or {}
            fn = str(md.get("file_name") or "").strip()
            if fn:
                indexed_files.add(fn)

        try:
            with self.graph_store._driver.session() as session:  # type: ignore[attr-defined]
                res = session.run(
                    "MATCH (e:Entity) RETURN count(e) AS c"
                )
                ent_after = int(res.single()["c"])
                res2 = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
                rel_after = int(res2.single()["c"])
                res3 = session.run("MATCH (n) RETURN count(n) AS cnt")
                cnt_all = int(res3.single()["cnt"])
        except Exception as e:  # noqa: BLE001
            print(">>> [ERROR] Neo4j post-write stats failed:", e)
            logger.error("Failed to count graph after write: %s", e)
            ent_after = rel_after = cnt_all = -1

        d_ent = ent_after - ent_before if ent_before >= 0 and ent_after >= 0 else None
        d_rel = rel_after - rel_before if rel_before >= 0 and rel_after >= 0 else None
        # 成功判定：任一新增关系，或至少 1 个新 Entity（原先要求 Entity>=2 会导致小文档永远不写 IngestedFile）
        rel_ok = d_rel is not None and d_rel > 0
        ent_ok = d_ent is not None and d_ent >= 1
        graph_grew = rel_ok or ent_ok
        msg = (
            f">>> [GRAPH] write delta: Entity {d_ent!s}, REL {d_rel!s} "
            f"(Entity {ent_before}->{ent_after}, REL {rel_before}->{rel_after}, "
            f"all_nodes={cnt_all})"
        )
        print(msg + f" | mark_ok={graph_grew} (REL>0 or Entity>=1)")
        logger.info(
            "Graph write delta: entity_delta=%s rel_delta=%s entity_count=%s rel_count=%s total_nodes=%s "
            "mark_ok=%s",
            d_ent,
            d_rel,
            ent_after,
            rel_after,
            cnt_all,
            graph_grew,
        )

        if d_ent is not None and d_rel is not None and not graph_grew:
            logger.warning(
                "⚠️ NO NEW GRAPH DATA (need REL>0 or Entity>=1): "
                "entity_delta=%s rel_delta=%s files=%s — "
                "check EXTRACTION_MODEL / EXTRACTION_TIMEOUT / ingestion batch timeout.",
                d_ent,
                d_rel,
                sorted(indexed_files),
            )
            print(
                ">>> ⚠️ NO GRAPH EXTRACTED (need REL>0 or Entity delta>=1) — "
                "check extraction LLM and timeouts."
            )

        # 仅在图谱实际增长时标记文件已建图，避免「空图」却不再重试
        if indexed_files and graph_grew:
            hashes: Dict[str, str] = {}
            for node in safe_nodes:
                md = getattr(node, "metadata", {}) or {}
                fn = str(md.get("file_name") or "").strip()
                h = md.get("content_sha256")
                if fn and isinstance(h, str) and h.strip():
                    hashes[fn] = h.strip()
            ts = datetime.now(timezone.utc).isoformat()
            with self.graph_store._driver.session() as session:  # type: ignore[attr-defined]
                for fn in indexed_files:
                    session.run(
                        """
                        MERGE (f:IngestedFile {file_name: $fn})
                        SET f.file_name = $fn,
                            f.content_hash = $hash,
                            f.updated_at = $updated_at
                        """,
                        fn=fn,
                        hash=hashes.get(fn, ""),
                        updated_at=ts,
                    )
            logger.info(
                "Graph ingestion done (LLM-LIGHT): IngestedFile markers=%s (with content_hash)",
                len(indexed_files),
            )
        elif indexed_files:
            logger.info(
                "Graph batch finished but IngestedFile NOT set (no graph growth); "
                "next ingest will retry graph for: %s",
                sorted(indexed_files),
            )

        # 调试：总节点数
        try:
            if cnt_all >= 0:
                print(f">>> [GRAPH] Neo4j node_count after write: {cnt_all}")
        except Exception as e:  # noqa: BLE001
            print(">>> [ERROR] Neo4j count failed:", e)
            logger.error("Failed to count nodes after graph write: %s", e)

        return None

    # ------------------------------------------------------------------
    # 删除文档
    # ------------------------------------------------------------------
    def delete_document(self, filename: str) -> int:
        """从 Neo4j 删除与指定文件相关的所有节点。"""
        query = "MATCH (n) WHERE n.file_name = $filename DETACH DELETE n"
        try:
            with self.graph_store._driver.session() as session:
                result = session.run(query, filename=filename)
                summary = result.consume()
                deleted = summary.counters.nodes_deleted
                logger.info(f"Deleted {deleted} Neo4j nodes for file '{filename}'")
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete graph nodes for '{filename}': {e}")
            return 0

    # ------------------------------------------------------------------
    # 查询引擎
    # ------------------------------------------------------------------
    def get_query_engine(self):
        """返回图查询引擎（使用主模型）。"""
        index = PropertyGraphIndex.from_existing(
            property_graph_store=self.graph_store,
            llm=self.llm,
            embed_model=self.embed_model,
        )

        from llama_index.core.indices.property_graph.sub_retrievers.vector import VectorContextRetriever
        vector_retriever = VectorContextRetriever(
            index.property_graph_store,
            embed_model=self.embed_model,
            include_text=True,
            similarity_top_k=5
        )

        return index.as_query_engine(sub_retrievers=[vector_retriever])
