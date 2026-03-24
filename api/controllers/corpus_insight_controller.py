"""
跨文档知识库洞察：聚合各文档 di_* 元数据（不读全文），单次 LLM 生成总结与要点。
"""

from __future__ import annotations

import logging
import os
import time
from collections import Counter
from typing import Any, Dict, List, Tuple

from api.controllers.knowledge_hub_controller import _document_intelligence_from_vector
from api.deps import graph_engine
from api.utils import is_allowed_extension
from configs.config import settings
from core.document_intelligence import extract_llm_json_object
from core.lang_detect import normalize_lang

logger = logging.getLogger(__name__)

_CORPUS_TTL_SEC = 180.0
_corpus_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}


def _di_nonempty(di: Dict[str, Any]) -> bool:
    if (di.get("summary") or "").strip():
        return True
    for key in ("keywords", "topics", "entities", "key_points"):
        v = di.get(key)
        if isinstance(v, list) and len(v) > 0:
            return True
    return False


def _list_recent_files(limit: int) -> List[str]:
    base = settings.DATA_RAW_DIR
    if not os.path.isdir(base):
        return []
    scored: List[Tuple[float, str]] = []
    for fn in os.listdir(base):
        path = os.path.join(base, fn)
        if not os.path.isfile(path) or not is_allowed_extension(fn):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        scored.append((mtime, fn))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [fn for _, fn in scored[:limit]]


def _format_counter_lines(title: str, ctr: Counter, top_n: int) -> str:
    lines: List[str] = []
    for key, cnt in ctr.most_common(top_n):
        if key:
            lines.append(f"  - {key} ({cnt})")
    body = "\n".join(lines) if lines else "  (none)"
    return f"{title}\n{body}"


def corpus_insight_controller(top_k_docs: int = 20, lang: str | None = None) -> Dict[str, Any]:
    """
    从最近 top_k_docs 个文件中读取有 di_* 的文档，统计关键词/主题/实体，并调用 LLM 生成 summary + key_insights。
    """
    k = max(1, min(int(top_k_docs or 20), 50))
    lang_n = normalize_lang(lang or "zh", default="zh")
    cache_key = f"{k}:{lang_n}"
    now = time.time()
    if cache_key in _corpus_cache:
        exp, payload = _corpus_cache[cache_key]
        if now < exp:
            return dict(payload)

    files = _list_recent_files(k)
    snapshots: List[Tuple[str, Dict[str, Any]]] = []
    for fn in files:
        di = _document_intelligence_from_vector(fn)
        if _di_nonempty(di):
            snapshots.append((fn, di))

    kw_c: Counter = Counter()
    tp_c: Counter = Counter()
    en_c: Counter = Counter()
    doc_summaries: List[str] = []

    for fn, di in snapshots:
        for x in di.get("keywords") or []:
            xs = str(x).strip()
            if xs:
                kw_c[xs] += 1
        for x in di.get("topics") or []:
            xs = str(x).strip()
            if xs:
                tp_c[xs] += 1
        for x in di.get("entities") or []:
            xs = str(x).strip()
            if xs:
                en_c[xs] += 1
        s = (di.get("summary") or "").strip()
        if s:
            short = s[:220] + ("…" if len(s) > 220 else "")
            doc_summaries.append(f"- {fn}: {short}")

    top_keywords = [t for t, _ in kw_c.most_common(25)]
    top_topics = [t for t, _ in tp_c.most_common(15)]
    top_entities = [t for t, _ in en_c.most_common(20)]

    empty_out: Dict[str, Any] = {
        "summary": "",
        "top_topics": top_topics,
        "top_entities": top_entities,
        "key_insights": [],
        "closing_takeaway": "",
        "top_keywords": top_keywords,
        "docs_analyzed": len(snapshots),
    }

    if not snapshots:
        if lang_n == "en":
            empty_out["summary"] = (
                "Not enough document intelligence metadata yet. "
                "Run ingestion with Document Intelligence enabled."
            )
        elif lang_n == "ko":
            empty_out["summary"] = "분석할 문서 메타데이터가 부족합니다. 인제스트 후 다시 시도하세요."
        else:
            empty_out["summary"] = "暂无可聚合的文档理解数据。请先完成摄取（含 Document Intelligence）。"
        _corpus_cache[cache_key] = (now + _CORPUS_TTL_SEC, dict(empty_out))
        return empty_out

    stats_block = "\n".join(
        [
            f"Documents with metadata: {len(snapshots)} (from {len(files)} newest files scanned).",
            _format_counter_lines("Keyword frequency:", kw_c, 20),
            _format_counter_lines("Topic frequency:", tp_c, 15),
            _format_counter_lines("Entity frequency:", en_c, 20),
            "Per-document summaries:",
            "\n".join(doc_summaries[:25]) if doc_summaries else "  (none)",
        ]
    )
    if len(stats_block) > 10000:
        stats_block = stats_block[:10000] + "\n…"

    if lang_n == "en":
        prompt = (
            "You analyze an enterprise knowledge base using ONLY the aggregated metadata below "
            "(keywords, topics, entities, per-document summaries). Do not invent facts or numbers.\n\n"
            f"{stats_block}\n\n"
            "Return ONLY valid JSON with keys:\n"
            '- "summary": 2-4 sentences in an executive-briefing tone: lead with the main takeaway about '
            "what this corpus is for and who it serves, then scope/coverage; avoid generic \"This corpus contains…\" openers.\n"
            '- "key_insights": 3-7 decisive one-line takeaways (management-style conclusions), each under ~18 words; '
            "state patterns or implications, not labels.\n"
            '- "closing_takeaway": exactly ONE memorable closing sentence (max ~25 words) that distills the main theme '
            "for an executive reader; must be consistent with the stats above, no new claims.\n\n"
            "English only. No markdown fences."
        )
    elif lang_n == "ko":
        prompt = (
            "아래는 여러 문서에서 모은 메타데이터입니다. 사실을 새로 만들지 마세요.\n\n"
            f"{stats_block}\n\n"
            "JSON만 반환:\n"
            '- "summary": 경영진 브리핑 톤의 2~4문장: 지식베이스의 핵심 가치·대상·범위를 먼저 쓰고, '
            "진부한 \"이 자료는…\" 식 시작은 피할 것\n"
            '- "key_insights": 3~7개의 한 줄 결론형 문장(한 줄당 한글 약 35자 이내 권장); 패턴·시사점 중심\n'
            '- "closing_takeaway": 핵심 주제를 한 문장으로 압축한 마무리(한글 약 40자 이내 권장); 위 통계와 모순 없이, 새 주장 금지\n'
        )
    else:
        prompt = (
            "你正在根据「多份文档的结构化元数据聚合」生成知识库级洞察，下方统计来自各文档的 di_* 字段，"
            "不要编造事实或数字。\n\n"
            f"{stats_block}\n\n"
            "只输出合法 JSON，键为：\n"
            '- "summary": 2-4 句中文，采用「给管理层看的简报」语气：先写知识库的核心价值、主要服务对象与覆盖范围，'
            "再补充分布特点；少用「本知识库主要包含…」式空话开头。\n"
            '- "key_insights": 字符串数组，3-7 条，每条一句、结论优先（像汇报里的「判断要点」），'
            "每条不超过约 36 个汉字，写可行动的观察或模式，避免只罗列名词。\n"
            '- "closing_takeaway": 单独字符串，一句话收尾（约 40 个汉字内），帮助读者「记住结论」；须与上文统计一致，不得编造。\n'
            "不要 markdown 代码块。"
        )

    summary_text = ""
    closing_takeaway = ""
    key_insights: List[str] = []
    try:
        raw = str(graph_engine.llm.complete(prompt)).strip()
        parsed = extract_llm_json_object(raw)
        summary_text = str(parsed.get("summary") or "").strip()
        ct = str(parsed.get("closing_takeaway") or "").strip()
        if ct:
            closing_takeaway = ct[:220] + ("…" if len(ct) > 220 else "")
        ki = parsed.get("key_insights")
        if isinstance(ki, list):
            raw_lines = [str(x).strip() for x in ki if str(x).strip()][:10]
            key_insights = []
            for line in raw_lines:
                if len(line) > 120:
                    line = line[:117].rstrip() + "…"
                key_insights.append(line)
    except Exception as e:  # noqa: BLE001
        logger.warning("corpus insight LLM failed: %s", e)

    if not summary_text:
        if lang_n == "en":
            summary_text = (
                f"Across {len(snapshots)} documents, top keywords include: "
                f"{', '.join(top_keywords[:8]) or 'n/a'}."
            )
        elif lang_n == "ko":
            summary_text = (
                f"{len(snapshots)}개 문서 기준 상위 키워드: "
                f"{', '.join(top_keywords[:8]) or '없음'}"
            )
        else:
            summary_text = (
                f"基于 {len(snapshots)} 份含元数据的文档，高频关键词包括："
                f"{('、'.join(top_keywords[:8])) or '暂无'}。"
            )

    out: Dict[str, Any] = {
        "summary": summary_text[:4000],
        "top_topics": top_topics,
        "top_entities": top_entities,
        "key_insights": key_insights,
        "closing_takeaway": closing_takeaway,
        "top_keywords": top_keywords,
        "docs_analyzed": len(snapshots),
    }
    _corpus_cache[cache_key] = (now + _CORPUS_TTL_SEC, dict(out))
    return out
