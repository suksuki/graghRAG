"""
v3 解释形态（观测 → 决策 v0）：基于埋点事件组合的摩擦类型与建议 UI 类型。

纯函数 evaluate_friction_v0 可单测；不落库逻辑见 insight_event_log / friction_controller。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from configs.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_CANDIDATE_JSONL = PROJECT_ROOT / "data" / "logs" / "friction_v3_candidates.jsonl"

# T4：显式提问关键词（简体）
_T4_KEYWORDS = ("哪个更对", "为什么", "哪个更可信")


def _payload(e: Dict[str, Any]) -> Dict[str, Any]:
    p = e.get("payload")
    if isinstance(p, dict):
        return p
    return {}


def evaluate_friction_v0(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    输入：与库中 insight_events 行语义一致的字典列表（至少含 event；可有 payload）。

    输出：friction_type、suggested_v3、triggers_fired、counts、signals（供 debug / 日志）。
    """
    switch = hover = click = 0
    view_sg_events = 0
    ref_counts_seen: List[int] = []
    max_dwell_conflict = 0
    t4_hit = False

    for e in events:
        name = (e.get("event") or "").strip()
        pl = _payload(e)
        if name == "switch_conflict_group":
            switch += 1
        elif name == "hover_tooltip":
            hover += 1
        elif name == "click_reference":
            click += 1
        elif name == "dwell_time":
            if pl.get("section") == "conflict":
                d = pl.get("duration_ms")
                if isinstance(d, (int, float)):
                    max_dwell_conflict = max(max_dwell_conflict, int(d))
        elif name == "view_support_group":
            view_sg_events += 1
            rc = pl.get("ref_count")
            if isinstance(rc, (int, float)):
                ref_counts_seen.append(int(rc))
        elif name == "user_question":
            text = str(pl.get("text") or "")
            if any(kw in text for kw in _T4_KEYWORDS):
                t4_hit = True

    tb = click >= 1 and switch >= 2
    t1 = switch >= 2 and click == 0
    t2 = hover >= 3 and click == 0
    t3 = max_dwell_conflict > 5000 and click == 0

    quantity_disparity = False
    if len(ref_counts_seen) >= 2:
        quantity_disparity = max(ref_counts_seen) - min(ref_counts_seen) >= 2
    tq = view_sg_events >= 2 and quantity_disparity and not (t1 or t2 or t3 or tb or t4_hit)

    triggers_fired: List[str] = []
    if t4_hit:
        triggers_fired.append("T4")
    if tb:
        triggers_fired.append("TB")
    if t1:
        triggers_fired.append("T1")
    if t2:
        triggers_fired.append("T2")
    if t3:
        triggers_fired.append("T3")
    if tq:
        triggers_fired.append("TQ")

    friction_type: Optional[str] = None
    suggested_v3: Optional[str] = None

    if t4_hit:
        friction_type, suggested_v3 = "T4", "A"
    elif tb:
        friction_type, suggested_v3 = "TB", "B"
    elif t1:
        friction_type, suggested_v3 = "T1", "A"
    elif t2:
        friction_type, suggested_v3 = "T2", "B"
    elif t3:
        friction_type, suggested_v3 = "T3", "A"
    elif tq:
        friction_type, suggested_v3 = "TQ", "A"

    counts: Dict[str, Any] = {
        "switch_conflict_group": switch,
        "hover_tooltip": hover,
        "click_reference": click,
        "view_support_group": view_sg_events,
        "max_dwell_conflict_ms": max_dwell_conflict,
    }
    signals: Dict[str, Any] = {
        "quantity_disparity": quantity_disparity,
        "ref_counts_seen": ref_counts_seen,
    }

    return {
        "friction_type": friction_type,
        "suggested_v3": suggested_v3,
        "triggers_fired": triggers_fired,
        "counts": counts,
        "signals": signals,
        "event_count": len(events),
    }


def append_friction_candidate_jsonl(row: Dict[str, Any]) -> None:
    """追加一条候选判定到 JSONL（PG 失败与否均可调用）。"""
    try:
        _CANDIDATE_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(_CANDIDATE_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning("friction v3 candidate jsonl write failed: %s", e)


def label_friction(friction_type: Optional[str]) -> str:
    """中文短标签（debug 面板）。"""
    if not friction_type:
        return "—"
    return {
        "T1": "冲突来回（T1）",
        "T2": "只 hover（T2）",
        "T3": "冲突区停滞（T3）",
        "T4": "显式提问（T4）",
        "TB": "有证据仍切换（TB）",
        "TQ": "数量/分组信号（TQ）",
    }.get(friction_type, friction_type)


def label_suggested(suggested: Optional[str]) -> str:
    if not suggested:
        return "—"
    return {
        "A": "Type A · 数量/结构",
        "B": "Type B · 来源类型",
        "C": "Type C · 时间维度",
        "D": "Type D · 语义 framing",
    }.get(suggested, suggested)
