"""
单请求文档洞察（DI-first）：向量召回 → supporting_chunks → 实体/图关系辅助 → LLM 仅基于片段的 grounded summary。

不得编造片段外事实；证据不足时在 summary 中明确说明。
"""

from __future__ import annotations

import logging
import os
import json
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2

from configs.config import settings
from core.document_intelligence import DI_ENTITIES
from core.hybrid_search_service import _parse_di_entities
from core.kg_edge_filter import (
    min_kg_conf_query_param,
    normalize_kg_rel_properties_for_api,
    params_with_min_kg_conf,
)
from core.doc_summary_store import fetch_doc_summary, upsert_doc_summary

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 14_000

# Decision v1：片段间「可能相反」的轻量关键词对（启发式，无模型；不误判为裁决）
_CONTRADICTION_PATTERN_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("increase", "decrease"),
    ("rise", "fall"),
    ("支持", "反对"),
    ("增长", "下降"),
    ("允许", "禁止"),
)


def detect_evidence_conflicts(supporting: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    在 supporting_chunks 两两之间做子串级启发式检测；仅用于提示用户自行对照，不表示语义推理结论。
    """
    if not supporting or len(supporting) < 2:
        return []
    seen_pairs: Set[Tuple[int, int]] = set()
    out: List[Dict[str, Any]] = []
    n = len(supporting)
    for i in range(n):
        for j in range(i + 1, n):
            s1 = supporting[i].get("snippet") or ""
            s2 = supporting[j].get("snippet") or ""
            c1 = str(s1).lower()
            c2 = str(s2).lower()
            try:
                r1 = int(supporting[i].get("ref_index") or 0)
                r2 = int(supporting[j].get("ref_index") or 0)
            except (TypeError, ValueError):
                continue
            if r1 < 1 or r2 < 1 or r1 == r2:
                continue
            if not c1.strip() or not c2.strip():
                continue
            for a, b in _CONTRADICTION_PATTERN_PAIRS:
                if (a in c1 and b in c2) or (b in c1 and a in c2):
                    key = (min(r1, r2), max(r1, r2))
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        out.append({"refs": [key[0], key[1]], "type": "contradiction"})
                    break
    return out


# Decision v2：与片段文本关键词粗对齐的「立场」桶（仅用于有 conflicts 时的结构展示，非裁决）
_STANCE_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("increase", ("increase", "增长", "上升")),
    ("decrease", ("decrease", "下降", "下跌")),
    ("rise", ("rise",)),
    ("fall", ("fall",)),
    ("support", ("支持",)),
    ("oppose", ("反对",)),
    ("allow", ("允许",)),
    ("forbid", ("禁止",)),
)


def _stance_key_for_snippet(snippet: str) -> str:
    t = str(snippet or "").lower()
    for key, hints in _STANCE_HINTS:
        if any(h in t for h in hints):
            return key
    return "other"


def build_support_groups(supporting: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """按 snippet 关键词将 ref_index 分桶；同一条只进一个桶（先匹配先赢）。"""
    groups: Dict[str, List[int]] = {}
    for ch in supporting:
        try:
            ref = int(ch.get("ref_index") or 0)
        except (TypeError, ValueError):
            continue
        if ref < 1:
            continue
        key = _stance_key_for_snippet(ch.get("snippet") or "")
        groups.setdefault(key, []).append(ref)
    out: Dict[str, List[int]] = {}
    for k, refs in groups.items():
        out[k] = sorted(set(refs))
    return out


def _doc_key_for_match(s: Optional[str]) -> str:
    """与 chunk metadata 的 file_name 对齐：去路径、统一小写，避免 doc_id 与元数据写法不一致。"""
    if not s:
        return ""
    t = str(s).strip().replace("\\", "/")
    return os.path.basename(t).lower()
_LANG_NAME = {
    "zh": "Chinese (Simplified)",
    "en": "English",
    "ko": "Korean",
}

# 有据摘要四段结构标题（须与 prompt 一致，便于前端按 #### 解析）
_STRUCTURE_SECTION_TITLES: Dict[str, List[str]] = {
    "zh": ["核心结论", "关键实体", "重要关系", "补充说明"],
    "en": ["Core conclusion", "Key entities", "Important relations", "Additional notes"],
    "ko": ["핵심 결론", "핵심 엔티티", "중요 관계", "추가 설명"],
}

_PERSON_QUERY_HINTS: Tuple[str, ...] = (
    "谁",
    "是谁",
    "title",
    "职位",
    "负责",
    "项目",
    "manager",
    "owner",
)
_SUMMARY_QUERY_HINTS: Tuple[str, ...] = (
    "总结",
    "概述",
    "流程",
    "简介",
    "summary",
    "overview",
    "what is",
)
_TEAM_QUERY_HINTS: Tuple[str, ...] = (
    "团队",
    "部门",
    "team",
    "dept",
    "department",
    "부서",
    "팀",
    "marketing",
    "market",
    "市场",
)
_PPT_SUFFIXES: Tuple[str, ...] = (".ppt", ".pptx")
_STRUCTURED_LINE_REGEX = re.compile(r"^\s*([^()（）\n]+?)\s*[(（]\s*([^()（）\n]+?)\s*[)）]\s*$")


def _node_score(nws: Any) -> float:
    for attr in ("score", "similarity"):
        v = getattr(nws, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _chunk_order_key(nws: Any) -> Tuple[int, int, str]:
    """
    Prefer original document order when stitching context:
    page_number/page -> start_char_idx/chunk_idx -> id
    """
    node = getattr(nws, "node", None)
    md = getattr(node, "metadata", None) or {}
    def _as_int(v: Any, d: int) -> int:
        try:
            return int(v)
        except Exception:  # noqa: BLE001
            return d
    page = _as_int(md.get("page_number", md.get("page", 10**9)), 10**9)
    start = _as_int(md.get("start_char_idx", md.get("chunk_idx", 10**9)), 10**9)
    nid = str(getattr(node, "id_", None) or getattr(node, "node_id", None) or "")
    return (page, start, nid)


def _collect_key_entities(nodes_with_scores: List[Any]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for nws in nodes_with_scores or []:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        md = getattr(node, "metadata", None) or {}
        for key in (DI_ENTITIES, "di_entities", "entities"):
            if key not in md:
                continue
            for x in _parse_di_entities(md.get(key)):
                n = str(x).strip()
                if len(n) < 2 or n in seen:
                    continue
                seen.add(n)
                out.append(n)
    return out[:40]


def _extract_structured_evidence(
    supporting: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    从 supporting_chunks 中提取结构化预览项，并保留 provenance。
    这是保守的展示辅助，不是新的事实来源。
    """
    grouped: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
    for ch in supporting or []:
        text = str(ch.get("chunk_text") or ch.get("snippet") or "").strip()
        if not text:
            continue
        ref_index = ch.get("ref_index")
        try:
            ref_num = int(ref_index)
        except (TypeError, ValueError):
            ref_num = None
        file_name = str(ch.get("file_name") or "").strip()
        for line in text.splitlines():
            m = _STRUCTURED_LINE_REGEX.match(line)
            if not m:
                continue
            role = str(m.group(1) or "").strip()
            persons = tuple(
                p.strip()
                for p in re.split(r"[、,，]", str(m.group(2) or "").strip())
                if p.strip()
            )
            if not role or not persons:
                continue
            key = (role, persons)
            row = grouped.setdefault(
                key,
                {
                    "role": role,
                    "persons": list(persons),
                    "ref_indices": [],
                    "file_names": [],
                },
            )
            if ref_num is not None and ref_num not in row["ref_indices"]:
                row["ref_indices"].append(ref_num)
            if file_name and file_name not in row["file_names"]:
                row["file_names"].append(file_name)
    rows = list(grouped.values())
    for row in rows:
        row["ref_indices"].sort()
        row["file_names"].sort()
    rows.sort(key=lambda item: (item["ref_indices"][0] if item["ref_indices"] else 10**9, item["role"]))
    return rows


def _retrieve_doc_scoped(
    *,
    vector_engine: Any,
    query: str,
    similarity_top_k: int,
    doc_filter: str,
) -> List[Any]:
    """在 retriever 层按 file_name 做前过滤；低命中时补充同文档前序 chunk。"""
    from llama_index.core import VectorStoreIndex
    from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters

    doc_raw = str(doc_filter or "").strip()
    filters = MetadataFilters(
        filters=[
            MetadataFilter(
                key="file_name",
                operator=FilterOperator.EQ,
                value=doc_raw,
            )
        ]
    )
    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_engine.vector_store,
        embed_model=vector_engine.embed_model,
    )
    retriever = index.as_retriever(similarity_top_k=similarity_top_k, filters=filters)
    primary = retriever.retrieve(query) or []

    # Fallback: doc-scoped local reading for structure-heavy docs (e.g., PPT).
    # If semantic retrieval returns too few hits, append early chunks from the same doc.
    min_hits = 3
    fallback_take = max(10, similarity_top_k)
    if len(primary) >= min_hits:
        return primary

    table_name = getattr(vector_engine, "full_table_name", "")
    if not table_name:
        return primary

    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT node_id, text, metadata_
            FROM {table_name}
            WHERE (metadata_ ->> 'file_name') = %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (doc_raw, int(fallback_take)),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.debug("doc-scoped fallback chunk read failed: %s", e)
        return primary

    merged: List[Any] = list(primary)
    seen_ids: Set[str] = set()
    for nws in merged:
        node = getattr(nws, "node", None)
        nid = str(getattr(node, "id_", None) or getattr(node, "node_id", None) or "")
        if nid:
            seen_ids.add(nid)

    for node_id, text, metadata in rows:
        nid = str(node_id or "")
        if nid and nid in seen_ids:
            continue
        md = metadata if isinstance(metadata, dict) else {}
        node = SimpleNamespace(id_=nid or None, node_id=nid or None, text=str(text or ""), metadata=md)
        merged.append(SimpleNamespace(node=node, score=0.0))
        if nid:
            seen_ids.add(nid)

    return merged[: max(similarity_top_k, len(primary))]


def _graph_relations_for_entities(
    graph_driver: Any, names: List[str], limit: int = 28
) -> List[Dict[str, Any]]:
    if not names:
        return []
    cy = """
    MATCH (e:Entity)-[r]->(n)
    WHERE e.name IN $names AND n.name IS NOT NULL
      AND type(r) <> 'ALIAS_OF'
      AND ($min_kg_conf <= 0 OR coalesce(r.kg_confidence, 1.0) >= $min_kg_conf)
    RETURN e.name AS source, type(r) AS relation, n.name AS target, properties(r) AS rel_props
    LIMIT $limit
    """
    try:
        with graph_driver.session() as session:
            rows = list(
                session.run(
                    cy,
                    **params_with_min_kg_conf(
                        {"names": names[:20], "limit": int(limit)}
                    ),
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("document insight graph relations failed: %s", e)
        return []
    seen: Set[Tuple[str, str, str]] = set()
    out: List[Dict[str, Any]] = []
    for rec in rows:
        s, rel, t = rec.get("source"), rec.get("relation"), rec.get("target")
        if not (s and rel and t):
            continue
        key = (str(s), str(rel), str(t))
        if key in seen:
            continue
        seen.add(key)
        norm = normalize_kg_rel_properties_for_api(dict(rec.get("rel_props") or {}))
        out.append(
            {
                "source": key[0],
                "relation": key[1],
                "target": key[2],
                "kg_source": norm.get("kg_source"),
                "kg_confidence": norm.get("kg_confidence"),
            }
        )
    return out


def _build_grounded_summary_prompt(
    query: str, sources_text: str, lang: str
) -> str:
    lang_name = _LANG_NAME.get(lang, _LANG_NAME["zh"])
    titles = _STRUCTURE_SECTION_TITLES.get(lang) or _STRUCTURE_SECTION_TITLES["zh"]
    heading_examples = "\n".join(f"   #### {t}" for t in titles)
    return (
        "You are a document intelligence assistant.\n\n"
        "STRICT RULES:\n"
        "1. Use ONLY information explicitly stated in SOURCES below.\n"
        "2. Do NOT invent entities, numbers, or relationships not in SOURCES.\n"
        "3. If SOURCES are empty or do not answer the question, say clearly that "
        "the retrieved excerpts are insufficient (one or two sentences).\n"
        "4. When evidence exists, write a structured summary (see rule 8), not a single unstructured paragraph.\n"
        f"5. Write entirely in {lang_name} (all headings and bullets in that language).\n"
        "6. SOURCES are numbered [1], [2], ... After each factual claim in a bullet, "
        "append bracket citations using ONLY those numbers, e.g. ...[1] or ...[1][3]. "
        "Every substantive bullet should have at least one citation.\n"
        "7. Do NOT cite a number that does not appear in SOURCES.\n"
        "8. FORMAT (STRICT): Output exactly four sections in this order. Each section MUST begin with "
        "its own line: a markdown level-4 heading using EXACTLY this pattern (four hash marks, space, title):\n"
        f"{heading_examples}\n"
        "   Use the titles above character-for-character (same spelling and punctuation).\n"
        "   After each heading, write 1–3 bullet lines. Each bullet MUST start with \"- \" (hyphen + space).\n"
        "   If SOURCES give nothing grounded for a section, use a single bullet briefly stating that "
        "the excerpts are insufficient for that aspect (still in the target language).\n"
        "   Do not add a fifth section. Do not skip a section. No text before the first #### line.\n\n"
        f"User question / focus:\n{query.strip()}\n\n"
        "SOURCES (retrieved chunks only; numbers match supporting_chunks.ref_index):\n"
        "-----\n"
        f"{sources_text}\n"
        "-----\n\n"
        "Summary:"
    )


def _is_person_struct_query(query: str) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    return any(k in q for k in _PERSON_QUERY_HINTS)


def _is_summary_query(query: str) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    return any(k in q for k in _SUMMARY_QUERY_HINTS)


def _should_try_facts(query: str) -> bool:
    q = str(query or "").strip()
    if not q:
        return False
    if _is_person_struct_query(q):
        return True
    # 允许“带姓名但无显式关键词”的问法命中 facts，降低 query 分类误判。
    extra_hints = ("经理", "总监", "负责人", "主管", "leader", "owner")
    ql = q.lower()
    return any(h in q for h in extra_hints if not h.isascii()) or any(
        h in ql for h in extra_hints if h.isascii()
    )


def _is_team_query(query: str) -> bool:
    q = str(query or "").strip()
    if not q:
        return False
    ql = q.lower()
    return any(h in q for h in _TEAM_QUERY_HINTS if not h.isascii()) or any(
        h in ql for h in _TEAM_QUERY_HINTS if h.isascii()
    )


def _extract_json_array(raw: str) -> List[Any]:
    s = str(raw or "").strip()
    if not s:
        return []
    try:
        data = json.loads(s)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", s)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


def _extract_team_candidates_v2(*, llm: Any, chunks_text: str) -> List[Dict[str, str]]:
    text = str(chunks_text or "").strip()
    if not text:
        return []
    if len(text) > 10000:
        text = text[:9999] + "…"
    prompt = (
        "请从以下文本中提取所有团队/部门名称。\n"
        "要求：\n"
        "- 只返回真实出现的团队/部门名称\n"
        "- 不要编造\n"
        "- 仅输出 JSON 数组（字符串数组）\n\n"
        f"文本：\n{text}\n"
    )
    raw = str(llm.complete(prompt)).strip()
    arr = _extract_json_array(raw)
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for x in arr:
        name = str(x or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "description": ""})
    return out[:12]


def _classify_candidate_types_v2(*, llm: Any, names: List[str]) -> Dict[str, str]:
    """
    Use LLM to classify candidate types, avoiding hardcoded language rules.
    Returns mapping: name -> team|person|role|other
    """
    clean_names = [str(x or "").strip() for x in names if str(x or "").strip()]
    if not clean_names:
        return {}
    prompt = (
        "请对以下候选项做类型分类，仅输出 JSON 对象，key 为原文名称，value 只能是："
        "team / person / role / other。\n\n"
        f"候选：{json.dumps(clean_names, ensure_ascii=False)}\n"
    )
    raw = str(llm.complete(prompt)).strip()
    out: Dict[str, str] = {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for k, v in data.items():
                kk = str(k or "").strip()
                vv = str(v or "").strip().lower()
                if not kk:
                    continue
                if vv not in ("team", "person", "role", "other"):
                    vv = "other"
                out[kk] = vv
            return out
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    for k, v in data.items():
                        kk = str(k or "").strip()
                        vv = str(v or "").strip().lower()
                        if not kk:
                            continue
                        if vv not in ("team", "person", "role", "other"):
                            vv = "other"
                        out[kk] = vv
            except json.JSONDecodeError:
                pass
    return out


def decision_engine_v1(
    *, llm: Any, query: str, candidates: List[Dict[str, str]], task: str
) -> Optional[Dict[str, str]]:
    """
    Minimal decision engine v1:
    - unified LLM selection call style
    - selected must be in candidates; otherwise fallback
    """
    if task != "team_match" or not candidates:
        return None

    names = [str(c.get("name") or "").strip() for c in candidates if str(c.get("name") or "").strip()]
    if not names:
        return None
    desc = []
    for i, c in enumerate(candidates, start=1):
        desc.append(f"{i}. {c.get('name')}: {c.get('description')}")
    cand_lines = []
    for i, line in enumerate(desc, start=1):
        _ = i
        cand_lines.append(line)
    prompt = (
        "用户问题：\n"
        f"{query}\n\n"
        "候选集合：\n"
        f"{chr(10).join(cand_lines)}\n\n"
        "任务：从候选中选择最符合问题的一个。\n"
        "只输出 JSON：\n"
        '{"selected": "候选中的原文名或null", "reason": "简短理由", "confidence": "high或low"}\n'
        "约束：只能从候选中选择；若没有合适的返回 null；不可编造。"
    )
    raw = str(llm.complete(prompt)).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            selected = data.get("selected")
            selected = None if selected is None else str(selected).strip()
            if not selected or selected.lower() == "null":
                return None
            if selected not in names:
                return None
            reason = str(data.get("reason") or "").strip()
            conf = str(data.get("confidence") or "").strip().lower()
            conf = "high" if conf == "high" else "low"
            return {"selected": selected, "reason": reason, "confidence": conf}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    selected = data.get("selected")
                    selected = None if selected is None else str(selected).strip()
                    if not selected or selected.lower() == "null":
                        return None
                    if selected not in names:
                        return None
                    reason = str(data.get("reason") or "").strip()
                    conf = str(data.get("confidence") or "").strip().lower()
                    conf = "high" if conf == "high" else "low"
                    return {"selected": selected, "reason": reason, "confidence": conf}
            except json.JSONDecodeError:
                pass
    return None


def _summary_from_person_rows(rows: List[Dict[str, Any]], lang: str) -> str:
    lines: List[str] = []
    if lang == "en":
        for i, r in enumerate(rows, start=1):
            title = r.get("title") or "N/A"
            projects = r.get("projects") or []
            p = ", ".join(projects) if projects else "N/A"
            lines.append(f"- {r.get('person')}: title={title}; projects={p}.[{i}]")
        return "Structured person info from this document:\n" + "\n".join(lines)
    if lang == "ko":
        for i, r in enumerate(rows, start=1):
            title = r.get("title") or "없음"
            projects = r.get("projects") or []
            p = ", ".join(projects) if projects else "없음"
            lines.append(f"- {r.get('person')}: 직함={title}; 담당 프로젝트={p}.[{i}]")
        return "문서 구조화 인물 정보:\n" + "\n".join(lines)
    for i, r in enumerate(rows, start=1):
        title = r.get("title") or "暂无"
        projects = r.get("projects") or []
        p = "、".join(projects) if projects else "暂无"
        lines.append(f"- {r.get('person')}：职位={title}；负责项目={p}。[{i}]")
    return "根据该文档的结构化人员信息：\n" + "\n".join(lines)


def _is_ppt_file(file_name: Optional[str]) -> bool:
    fn = str(file_name or "").strip().lower()
    return fn.endswith(_PPT_SUFFIXES)


def _answer_with_summary(*, llm: Any, summary_text: str, query: str, lang: str) -> str:
    if lang == "en":
        prompt = (
            "Answer the question based ONLY on the document summary.\n\n"
            "[Document Summary]\n"
            f"{summary_text}\n\n"
            "[Question]\n"
            f"{query}\n\n"
            "Rules:\n"
            "- Only use the summary.\n"
            "- Do not invent facts.\n"
            "- Keep the answer concise.\n"
        )
    elif lang == "ko":
        prompt = (
            "아래 문서 요약만 근거로 질문에 답하세요.\n\n"
            "[문서 요약]\n"
            f"{summary_text}\n\n"
            "[질문]\n"
            f"{query}\n\n"
            "규칙:\n"
            "- 요약에 있는 내용만 사용\n"
            "- 추측 금지\n"
            "- 간결하게 답변\n"
        )
    else:
        prompt = (
            "基于以下文档摘要回答问题：\n\n"
            "【文档摘要】\n"
            f"{summary_text}\n\n"
            "【问题】\n"
            f"{query}\n\n"
            "要求：\n"
            "- 只基于摘要回答\n"
            "- 不要编造\n"
            "- 不要扩展\n"
        )
    return str(llm.complete(prompt)).strip()


def _summary_answer_invalid(answer: str) -> bool:
    a = str(answer or "").strip()
    if not a or len(a) < 20:
        return True
    weak_hints = ("未提及", "insufficient", "not mentioned", "없")
    return any(h in a.lower() if h.isascii() else h in a for h in weak_hints)


def _extract_json_object(raw: str) -> Dict[str, Any]:
    s = str(raw or "").strip()
    if not s:
        return {}
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _plan_query(llm: Any, query: str) -> Dict[str, Any]:
    prompt = (
        "用户问题：\n"
        f"{query}\n\n"
        "判断：\n"
        "1) 是否需要查文档\n"
        "2) 关注点是什么\n\n"
        "仅输出 JSON：\n"
        '{"need_retrieval": true, "focus": "...", "intent": "factual|summary|reasoning"}'
    )
    try:
        raw = str(llm.complete(prompt)).strip()
    except Exception:
        return {"need_retrieval": True, "focus": "", "intent": "reasoning"}
    obj = _extract_json_object(raw)
    need = bool(obj.get("need_retrieval", True))
    focus = str(obj.get("focus") or "").strip()
    intent = str(obj.get("intent") or "reasoning").strip().lower()
    if intent not in ("factual", "summary", "reasoning"):
        intent = "reasoning"
    return {"need_retrieval": need, "focus": focus, "intent": intent}


def _build_agentic_answer_prompt(query: str, chunks_text: str, lang: str) -> str:
    if lang == "en":
        return (
            "Answer based on the following document content:\n\n"
            f"{chunks_text}\n\n"
            f"Question:\n{query}\n\n"
            "Requirements:\n"
            "- Must be grounded in the content\n"
            "- Do not hallucinate\n"
            "- If a user term is not directly mentioned, explicitly state it is not directly mentioned\n"
            "- Then, if the document contains semantically related concepts, you may list them as possibly related\n"
            "- Do NOT claim direct equivalence between the user term and those related concepts\n"
        )
    if lang == "ko":
        return (
            "다음 문서 내용만 근거로 답변하세요:\n\n"
            f"{chunks_text}\n\n"
            f"질문:\n{query}\n\n"
            "요구사항:\n"
            "- 반드시 문서 내용 근거\n"
            "- 추측 금지\n"
            "- 사용자 용어가 문서에 직접 없으면 직접 없다고 명시\n"
            "- 그 후 문서에 의미상 가까운 개념이 있으면 '관련 가능성'으로만 제시\n"
            "- 사용자 용어와 관련 개념을 직접 같은 것으로 단정하지 말 것\n"
        )
    return (
        "基于以下文档内容回答：\n\n"
        f"{chunks_text}\n\n"
        f"问题：\n{query}\n\n"
        "要求：\n"
        "- 必须基于内容\n"
        "- 不要编造\n"
        "- 若用户术语未被文档直接提及，先明确说明“文档未直接提及该术语”\n"
        "- 然后，如果文档中存在语义可能接近的概念，可用“可能相关”方式提示\n"
        "- 不允许把用户术语与文档概念直接等价替换\n"
    )


def run_document_insight(
    *,
    vector_engine: Any,
    graph_driver: Any,
    llm: Any,
    query: str,
    top_k: int = 5,
    doc_id: Optional[str] = None,
    include_graph_relations: bool = True,
    lang: str = "zh",
) -> Dict[str, Any]:
    q = (query or "").strip()
    top_k = max(1, min(int(top_k or 5), 20))
    doc_filter = (doc_id or "").strip() or None
    filter_key = _doc_key_for_match(doc_filter) if doc_filter else ""
    summary_fallback_to_rag = False
    planner = _plan_query(llm, q)
    focus = str(planner.get("focus") or "").strip()
    retrieval_query = q if not focus else f"{q} {focus}"

    if doc_filter and _should_try_facts(q):
        try:
            from core.person_entity_store import fetch_person_entities

            person_rows = fetch_person_entities(file_name=doc_filter, query_text=q, limit=8)
            if person_rows:
                supporting = []
                for i, r in enumerate(person_rows, start=1):
                    title = r.get("title") or ""
                    projects = r.get("projects") or []
                    p = "、".join(projects) if projects else ""
                    snippet = f"person={r.get('person')}; title={title or 'null'}; projects={p or '[]'}"
                    supporting.append(
                        {
                            "id": f"person::{doc_filter}::{i}",
                            "ref_index": i,
                            "file_name": r.get("source_doc") or doc_filter,
                            "snippet": snippet,
                            "score": 1.0,
                        }
                    )
                summary = _summary_from_person_rows(person_rows, lang)
                structured_evidence = []
                for item in supporting:
                    snippet = str(item.get("snippet") or "")
                    match = re.match(r"person=([^;]+);\s*title=([^;]+);", snippet)
                    if not match:
                        continue
                    person = str(match.group(1) or "").strip()
                    title = str(match.group(2) or "").strip()
                    if not person or not title or title == "null":
                        continue
                    structured_evidence.append(
                        {
                            "role": title,
                            "persons": [person],
                            "ref_indices": [int(item["ref_index"])],
                            "file_names": [str(item.get("file_name") or doc_filter)],
                        }
                    )
                return {
                    "summary": summary,
                    "source": "facts",
                    "key_entities": [str(r.get("person") or "") for r in person_rows][:30],
                    "key_relations": [],
                    "supporting_chunks": supporting,
                    "structured_evidence": structured_evidence,
                    "insufficient_evidence": False,
                    "decision": {
                        "conflicts": [],
                        "support_groups": None,
                    },
                    "debug": {
                        "pre_filter_hits": 0,
                        "post_filter_hits": len(person_rows),
                        "final_used_chunks": len(supporting),
                        "doc_scope_applied": True,
                        "chunk_count": len(supporting),
                        "doc_filter": doc_filter,
                        "doc_match_key": filter_key or None,
                        "vector_hits_pre_doc_filter": 0,
                        "vector_hits_post_doc_filter": 0,
                        "graph_relation_count": 0,
                        "min_kg_conf_used": min_kg_conf_query_param(),
                        "person_entity_hit_count": len(person_rows),
                        "person_entity_short_circuit": True,
                    },
                }
        except Exception as e:  # noqa: BLE001
            logger.debug("person entity pre-check skipped: %s", e)

    # selection / summary 主路径已降级：主路径统一为 raw chunks -> LLM

    nodes_with_scores: List[Any] = []
    retrieve_k = min(30, top_k * 3 if doc_filter else top_k)
    retrieve_k = max(retrieve_k, top_k)
    doc_scope_applied = False
    try:
        if doc_filter:
            nodes_with_scores = _retrieve_doc_scoped(
                vector_engine=vector_engine,
                query=retrieval_query,
                similarity_top_k=retrieve_k,
                doc_filter=doc_filter,
            )
            doc_scope_applied = True
        else:
            retriever = vector_engine.get_retriever(similarity_top_k=retrieve_k)
            nodes_with_scores = retriever.retrieve(retrieval_query)
    except Exception as e:  # noqa: BLE001
        logger.warning("document insight retrieve failed: %s", e)
        if doc_filter:
            try:
                retriever = vector_engine.get_retriever(similarity_top_k=retrieve_k)
                nodes_with_scores = retriever.retrieve(retrieval_query)
            except Exception as e2:  # noqa: BLE001
                logger.warning("document insight fallback retrieve failed: %s", e2)
    hits_pre_doc_filter = 0
    try:
        retriever_debug = vector_engine.get_retriever(similarity_top_k=retrieve_k)
        hits_pre_doc_filter = len(retriever_debug.retrieve(retrieval_query) or [])
    except Exception as e:  # noqa: BLE001
        logger.debug("document insight debug pre-filter retrieve failed: %s", e)
        hits_pre_doc_filter = len(nodes_with_scores or [])
    if doc_filter and not doc_scope_applied:
        filtered: List[Any] = []
        for nws in nodes_with_scores or []:
            node = getattr(nws, "node", None)
            if node is None:
                continue
            md = getattr(node, "metadata", None) or {}
            fn = str(md.get("file_name") or md.get("source") or "").strip()
            if _doc_key_for_match(fn) == filter_key:
                filtered.append(nws)
        nodes_with_scores = filtered[:top_k]
        if not filtered and hits_pre_doc_filter:
            logger.info(
                "document insight doc_id filter dropped all hits (doc_id=%r match_key=%r, pre_count=%s)",
                doc_filter,
                filter_key,
                hits_pre_doc_filter,
            )
    else:
        nodes_with_scores = (nodes_with_scores or [])[:top_k]

    # doc-scoped: if retrieval returns too few hits, do a secondary pass from
    # global retrieval and filter by normalized file key, then keep top_k in doc order.
    if doc_filter and len(nodes_with_scores or []) < top_k:
        try:
            retriever_more = vector_engine.get_retriever(similarity_top_k=min(64, max(24, top_k * 8)))
            more_nodes = retriever_more.retrieve(retrieval_query)
            merged = list(nodes_with_scores or [])
            seen_ids: Set[str] = set()
            for nws in merged:
                node = getattr(nws, "node", None)
                nid = str(getattr(node, "id_", None) or getattr(node, "node_id", None) or "")
                if nid:
                    seen_ids.add(nid)
            for nws in more_nodes or []:
                node = getattr(nws, "node", None)
                if node is None:
                    continue
                md = getattr(node, "metadata", None) or {}
                fn = str(md.get("file_name") or md.get("source") or "").strip()
                if _doc_key_for_match(fn) != filter_key:
                    continue
                nid = str(getattr(node, "id_", None) or getattr(node, "node_id", None) or "")
                if nid and nid in seen_ids:
                    continue
                if nid:
                    seen_ids.add(nid)
                merged.append(nws)
            merged.sort(key=_chunk_order_key)
            nodes_with_scores = merged[:top_k]
        except Exception as e:  # noqa: BLE001
            logger.debug("doc-scoped secondary merge skipped: %s", e)

    hits_post_doc_filter = len(nodes_with_scores or [])

    supporting: List[Dict[str, Any]] = []
    source_blocks: List[str] = []
    char_budget = 0
    ref_idx = 0
    for nws in nodes_with_scores:
        node = getattr(nws, "node", None)
        if node is None:
            continue
        text = (getattr(node, "text", "") or "").strip()
        if not text:
            continue
        md = getattr(node, "metadata", None) or {}
        fn = md.get("file_name") or md.get("source") or ""
        cid = str(
            getattr(node, "id_", None)
            or getattr(node, "node_id", None)
            or hash(text[:200])
        )
        sc = _node_score(nws)
        snip = text.replace("\n", " ")
        if len(snip) > 1200:
            snip = snip[:1200].rstrip() + "…"
        next_idx = ref_idx + 1
        block = f"[{next_idx}] file: {fn or 'unknown'}\n{snip}"
        if char_budget + len(block) > MAX_SOURCE_CHARS:
            break
        ref_idx = next_idx
        char_budget += len(block)
        source_blocks.append(block)
        supporting.append(
            {
                "id": cid,
                "ref_index": ref_idx,
                "file_name": fn if fn else None,
                "chunk_text": text,
                "snippet": snip,
                "score": round(sc, 4),
            }
        )

    sources_joined = "\n\n".join(source_blocks)
    key_entities = _collect_key_entities(nodes_with_scores)

    key_relations: List[Dict[str, Any]] = []
    if include_graph_relations and key_entities:
        key_relations = _graph_relations_for_entities(
            graph_driver, key_entities[:15], limit=28
        )

    insufficient = len(supporting) == 0
    summary = ""
    if insufficient:
        if lang == "en":
            summary = (
                "No relevant document excerpts were retrieved; cannot provide a grounded answer."
            )
        elif lang == "ko":
            summary = "관련 문서 조각을 찾지 못해 근거 있는 답변을 드리기 어렵습니다."
        else:
            summary = "未能检索到相关文档片段，无法基于语料给出有据回答。"
    else:
        prompt = _build_agentic_answer_prompt(q, sources_joined, lang)
        try:
            summary = str(llm.complete(prompt)).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("document insight LLM failed: %s", e)
            summary = (
                "（摘要生成暂时失败，请稍后重试。）"
                if lang != "en"
                else "(Summary generation failed; please retry.)"
            )

    if not summary:
        insufficient = True
        summary = (
            "根据当前检索到的片段无法生成摘要。"
            if lang != "en"
            else "Could not generate a summary from the retrieved excerpts."
        )
    if doc_filter and not insufficient:
        upsert_doc_summary(doc_filter, summary)

    conflicts = detect_evidence_conflicts(supporting)
    support_groups: Optional[Dict[str, List[int]]] = (
        build_support_groups(supporting) if conflicts else None
    )
    structured_evidence = _extract_structured_evidence(supporting)

    return {
        "summary": summary,
        "source": "rag",
        "key_entities": key_entities[:30],
        "key_relations": key_relations,
        "supporting_chunks": supporting,
        "structured_evidence": structured_evidence,
        "insufficient_evidence": insufficient,
        "decision": {
            "conflicts": conflicts,
            "support_groups": support_groups,
        },
        "debug": {
            "summary_used": False,
            "summary_fallback_to_rag": summary_fallback_to_rag,
            "planner_need_retrieval": bool(planner.get("need_retrieval", True)),
            "planner_focus": focus or None,
            "planner_intent": planner.get("intent"),
            "pre_filter_hits": hits_pre_doc_filter,
            "post_filter_hits": hits_post_doc_filter,
            "final_used_chunks": len(supporting),
            "doc_scope_applied": bool(doc_filter and doc_scope_applied),
            "chunk_count": len(supporting),
            "doc_filter": doc_filter,
            "doc_match_key": filter_key or None,
            "vector_hits_pre_doc_filter": hits_pre_doc_filter,
            "vector_hits_post_doc_filter": hits_post_doc_filter,
            "graph_relation_count": len(key_relations),
            "min_kg_conf_used": min_kg_conf_query_param(),
        },
    }
