"""
Document Intelligence — 将文档正文压缩为结构化元数据（摘要 / 关键词 / 主题 / 实体 / 要点 / 类型）。
结果写入向量 chunk 的 metadata（di_* 前缀），供 GET /docs 聚合展示。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from core.lang_detect import normalize_lang

logger = logging.getLogger(__name__)

# 进程内缓存：file_name + content_sha256 → 避免同一次摄取或重复请求打多次 LLM
_intel_cache: Dict[str, Dict[str, Any]] = {}

# 与 ingestion / API 共用的 metadata 键名
DI_SUMMARY = "di_summary"
DI_KEYWORDS = "di_keywords"
DI_TOPICS = "di_topics"
DI_ENTITIES = "di_entities"
DI_KEY_POINTS = "di_key_points"
DI_DOC_TYPE = "di_doc_type"

_DOC_TYPE_ALLOWED = frozenset({"policy", "product", "report", "manual", "other"})


def normalize_doc_type(raw: Optional[str]) -> str:
    """
    将 LLM 可能返回的自由文本（如 financial report、政策文件）映射到固定枚举。
    """
    if not isinstance(raw, str) or not raw.strip():
        return "other"
    s = raw.strip().lower()
    if s in _DOC_TYPE_ALLOWED:
        return s
    # 英文关键词
    if "policy" in s or "regulation" in s or "合规" in raw or "政策" in raw:
        return "policy"
    if "manual" in s or "handbook" in s or "手册" in raw or "指南" in raw:
        return "manual"
    if "report" in s or "报告" in raw or "白皮书" in raw:
        return "report"
    if "product" in s or "产品" in raw:
        return "product"
    return "other"


def extract_llm_json_object(raw: str) -> Dict[str, Any]:
    """解析 LLM 返回的 JSON（容忍 markdown 代码围栏与前后噪声）。"""
    return _extract_json_object(raw)


def empty_intelligence() -> Dict[str, Any]:
    return {
        "summary": "",
        "keywords": [],
        "topics": [],
        "entities": [],
        "key_points": [],
        "doc_type": "other",
    }


def _cache_key(file_name: str, content_sha256: str) -> str:
    return f"{file_name}\0{content_sha256}"


def _truncate_text(text: str, max_chars: int = 12000) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _extract_json_object(raw: str) -> Dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def _trim_short_line(val: str, max_chars: int = 22) -> str:
    """要点单行展示：控制长度便于扫读（中文约 20 字内）。"""
    s = (val or "").strip()
    if len(s) <= max_chars:
        return s
    if max_chars < 2:
        return s[:max_chars]
    return s[: max_chars - 1].rstrip() + "…"


def _normalize_intel(data: Dict[str, Any]) -> Dict[str, Any]:
    out = empty_intelligence()
    summ = data.get("summary")
    if isinstance(summ, str) and summ.strip():
        out["summary"] = summ.strip()[:4000]

    def _as_str_list(key: str, max_n: int) -> List[str]:
        v = data.get(key)
        if not isinstance(v, list):
            return []
        xs: List[str] = []
        for x in v:
            if isinstance(x, (str, int, float)) and str(x).strip():
                xs.append(str(x).strip()[:200])
            if len(xs) >= max_n:
                break
        return xs

    out["keywords"] = _as_str_list("keywords", 12)[:10]
    out["topics"] = _as_str_list("topics", 8)[:5]
    out["entities"] = _as_str_list("entities", 24)[:20]
    out["key_points"] = [_trim_short_line(x, 22) for x in _as_str_list("key_points", 8)[:5]]

    dt = data.get("doc_type")
    out["doc_type"] = normalize_doc_type(dt) if dt is not None else "other"
    return out


def extract_document_intelligence(
    text: str,
    lang: str | None,
    llm: Any,
    *,
    file_name: str = "",
    content_sha256: str = "",
) -> Dict[str, Any]:
    """
    使用 LLM 抽取结构化信息。可选 file_name + content_sha256 命中进程内缓存。
    """
    if not (text or "").strip():
        return empty_intelligence()

    lang_n = normalize_lang(lang or "zh", default="zh")
    if file_name and content_sha256:
        ck = _cache_key(file_name, content_sha256)
        if ck in _intel_cache:
            return dict(_intel_cache[ck])

    truncated = _truncate_text(text, 12000)

    if lang_n == "en":
        prompt = (
            "Extract structured information from the document text below.\n\n"
            "Return ONLY a valid JSON object with these keys:\n"
            '- "summary": 2-4 sentences with a conclusion-first tone: lead with the main takeaway and who it is for, '
            "then context; avoid generic openers like \"This document describes…\"\n"
            '- "keywords": array of 5-10 short keywords\n'
            '- "topics": array of 2-5 high-level topics\n'
            '- "entities": company/product/organization names mentioned\n'
            '- "key_points": 3-5 items, each at most ~12 words, factual and scannable\n'
            '- "doc_type": one of: policy, product, report, manual, other\n\n'
            "Rules: Do not invent facts. Keep the same language as the input text. "
            "No markdown, no code fences — JSON only.\n\n"
            f"Text:\n{truncated}\n"
        )
    elif lang_n == "ko":
        prompt = (
            "아래 문서에서 구조화된 정보를 추출하세요.\n\n"
            "다음 키만 가진 유효한 JSON 객체만 반환하세요:\n"
            '- "summary": 비즈니스 요약 2~4문장. 결론·핵심을 먼저 쓰고 독자/활용 맥락을 덧붙임. '
            "\"이 문서는…를 설명합니다\" 같은 진부한 시작은 피할 것\n"
            '- "keywords": 짧은 키워드 5~10개 배열\n'
            '- "topics": 상위 주제 2~5개 배열\n'
            '- "entities": 회사/제품/조직 이름\n'
            '- "key_points": 핵심 사실 3~5개, 각 줄은 짧게(한글 약 20자 이내 권장)\n'
            '- "doc_type": policy, product, report, manual, other 중 하나\n\n'
            "규칙: 환각 금지. 입력과 같은 언어. 마크다운/코드펜스 없이 JSON만.\n\n"
            f"본문:\n{truncated}\n"
        )
    else:
        prompt = (
            "从下列文档正文中抽取结构化信息。\n\n"
            "只输出一个合法 JSON 对象，包含键：\n"
            '- "summary": 2-4 句中文，结论优先：先写文档重点与结论，再写适用对象或价值；'
            "少用「本文件主要介绍…」这类空泛开头\n"
            '- "keywords": 5-10 个关键词（字符串数组）\n'
            '- "topics": 2-5 个高层主题（字符串数组）\n'
            '- "entities": 公司/产品/组织等实体名称（字符串数组）\n'
            '- "key_points": 3-5 条，每条不超过约 20 个汉字，偏结论与可执行信息（字符串数组）\n'
            '- "doc_type": 从 policy, product, report, manual, other 中选一个\n\n'
            "规则：不要编造事实；语言与正文一致；不要输出 markdown 或代码块，仅 JSON。\n\n"
            f"正文：\n{truncated}\n"
        )

    try:
        raw = str(llm.complete(prompt)).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("document_intelligence LLM failed: %s", e)
        return empty_intelligence()

    parsed = _extract_json_object(raw)
    out = _normalize_intel(parsed)
    if file_name and content_sha256:
        _intel_cache[_cache_key(file_name, content_sha256)] = dict(out)
    return out


def apply_intelligence_to_file_nodes(nodes: List[Any], file_name: str, intel: Dict[str, Any]) -> None:
    """将抽取结果写入同一文件下所有 chunk 的 metadata（JSON 数组用字符串保存）。"""
    fn = (file_name or "").strip()
    if not fn:
        return
    payload = _normalize_intel(intel)
    di_kw = json.dumps(payload["keywords"], ensure_ascii=False)
    di_tp = json.dumps(payload["topics"], ensure_ascii=False)
    di_ent = json.dumps(payload["entities"], ensure_ascii=False)
    di_kp = json.dumps(payload["key_points"], ensure_ascii=False)
    for node in nodes:
        md = getattr(node, "metadata", None) or {}
        if str(md.get("file_name") or "") != fn:
            continue
        md[DI_SUMMARY] = payload["summary"]
        md[DI_KEYWORDS] = di_kw
        md[DI_TOPICS] = di_tp
        md[DI_ENTITIES] = di_ent
        md[DI_KEY_POINTS] = di_kp
        md[DI_DOC_TYPE] = payload["doc_type"]
        try:
            node.metadata = md
        except Exception:  # noqa: BLE001
            pass


def chunks_text_for_intelligence(nodes: List[Any], file_name: str, max_chunks: int = 3) -> str:
    """取同一文件前若干个 chunk 拼接成抽取用正文。"""
    fn = (file_name or "").strip()
    parts: List[str] = []
    for node in nodes:
        md = getattr(node, "metadata", None) or {}
        if str(md.get("file_name") or "") != fn:
            continue
        t = (getattr(node, "text", None) or "").strip()
        if t:
            parts.append(t)
        if len(parts) >= max_chunks:
            break
    return _truncate_text("\n\n".join(parts), 12000)
