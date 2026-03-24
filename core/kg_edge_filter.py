"""
图查询侧：按关系上的 kg_confidence 压低 lexical fallback 边对 UI / 检索的干扰。
缺失 kg_confidence 视为 LLM 边（coalesce 为 1.0）。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from configs.config import settings


def min_kg_conf_query_param() -> float:
    v = getattr(settings, "KG_MIN_EDGE_CONFIDENCE_FOR_QUERY", 0.5)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.5


def params_with_min_kg_conf(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = dict(params or {})
    out["min_kg_conf"] = min_kg_conf_query_param()
    return out


def normalize_kg_rel_properties_for_api(
    props: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """
    API 出参归一：无 kg_* 的历史边视为 legacy + 1.0，与查询侧 coalesce 语义一致，
    便于前端/统计不再手写 coalesce。
    """
    out = dict(props or {})
    src = out.get("kg_source")
    if src is None or (isinstance(src, str) and not src.strip()):
        out["kg_source"] = "legacy"
    try:
        if out.get("kg_confidence") is None:
            out["kg_confidence"] = 1.0
        else:
            out["kg_confidence"] = float(out["kg_confidence"])
    except (TypeError, ValueError):
        out["kg_confidence"] = 1.0
    return out


def relation_passes_min_confidence(
    rel_props: Optional[Mapping[str, Any]],
    min_confidence: Optional[float] = None,
) -> bool:
    """Python 侧过滤（遍历路径中的 relationship）。"""
    m = min_confidence if min_confidence is not None else min_kg_conf_query_param()
    if m <= 0:
        return True
    props = rel_props or {}
    c = props.get("kg_confidence")
    if c is None:
        return True
    try:
        return float(c) >= m
    except (TypeError, ValueError):
        return True
