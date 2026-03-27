"""Decision v1/v2：冲突检测 + 支持结构分组（无模型）。"""

from core.document_insight_service import build_support_groups, detect_evidence_conflicts


def test_detect_conflicts_zh_growth_vs_decline():
    supporting = [
        {"ref_index": 1, "snippet": "本季度销售额增长明显"},
        {"ref_index": 2, "snippet": "利润下降需关注"},
    ]
    c = detect_evidence_conflicts(supporting)
    assert len(c) == 1
    assert c[0]["type"] == "contradiction"
    assert set(c[0]["refs"]) == {1, 2}


def test_detect_conflicts_en_increase_decrease():
    supporting = [
        {"ref_index": 1, "snippet": "We expect costs to increase next year."},
        {"ref_index": 2, "snippet": "Overall margins could decrease rapidly."},
    ]
    c = detect_evidence_conflicts(supporting)
    assert len(c) == 1
    assert set(c[0]["refs"]) == {1, 2}


def test_detect_conflicts_empty_or_single():
    assert detect_evidence_conflicts([]) == []
    assert detect_evidence_conflicts([{"ref_index": 1, "snippet": "only one"}]) == []


def test_detect_conflicts_dedupes_pair():
    supporting = [
        {"ref_index": 1, "snippet": "增长"},
        {"ref_index": 2, "snippet": "下降"},
    ]
    c = detect_evidence_conflicts(supporting)
    assert len(c) == 1


def test_build_support_groups_buckets():
    supporting = [
        {"ref_index": 1, "snippet": "本季度销售额增长明显"},
        {"ref_index": 2, "snippet": "利润下降需关注"},
        {"ref_index": 3, "snippet": "无关键词锚点"},
    ]
    g = build_support_groups(supporting)
    assert g["increase"] == [1]
    assert g["decrease"] == [2]
    assert g["other"] == [3]
