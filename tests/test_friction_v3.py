"""core.friction_v3.evaluate_friction_v0 规则单测（不依赖 DB）。"""

from core.friction_v3 import evaluate_friction_v0


def _ev(name: str, **payload):
    return {"event": name, "payload": payload}


def test_t1_switch_no_click():
    evs = [
        _ev("switch_conflict_group", from_group="A", to_group="B"),
        _ev("switch_conflict_group", from_group="B", to_group="A"),
    ]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "T1"
    assert r["suggested_v3"] == "A"
    assert "T1" in r["triggers_fired"]


def test_t2_hover_no_click():
    evs = [
        _ev("hover_tooltip", ref_id="1"),
        _ev("hover_tooltip", ref_id="2"),
        _ev("hover_tooltip", ref_id="1"),
    ]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "T2"
    assert r["suggested_v3"] == "B"


def test_t3_dwell_conflict():
    evs = [_ev("dwell_time", section="conflict", duration_ms=6000)]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "T3"
    assert r["suggested_v3"] == "A"


def test_tb_click_and_switch():
    evs = [
        _ev("click_reference", ref_id="1", position="summary"),
        _ev("switch_conflict_group", from_group="A", to_group="B"),
        _ev("switch_conflict_group", from_group="B", to_group="A"),
    ]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "TB"
    assert r["suggested_v3"] == "B"


def test_t4_user_question_keyword():
    evs = [_ev("user_question", text="哪个更对？")]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "T4"
    assert r["suggested_v3"] == "A"


def test_priority_t4_over_t1():
    evs = [
        _ev("user_question", text="为什么不同"),
        _ev("switch_conflict_group"),
        _ev("switch_conflict_group"),
    ]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "T4"


def test_tq_quantity_signal():
    evs = [
        _ev("view_support_group", group_id="A", ref_count=3),
        _ev("view_support_group", group_id="B", ref_count=1),
    ]
    r = evaluate_friction_v0(evs)
    assert r["friction_type"] == "TQ"
    assert r["suggested_v3"] == "A"
    assert r["signals"]["quantity_disparity"] is True


def test_empty():
    r = evaluate_friction_v0([])
    assert r["friction_type"] is None
    assert r["suggested_v3"] is None
