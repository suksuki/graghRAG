import pytest

from pipelines.query_pipeline import QueryPipeline


def _first_done_event(pipeline: QueryPipeline, query: str, mode: str = "hybrid"):
    for evt in pipeline.run_stream(query, mode=mode):
        if isinstance(evt, dict) and evt.get("type") == "done":
            return evt
    return None


@pytest.mark.integration
def test_stream_done_contains_graph_and_debug_contract(monkeypatch):
    qp = QueryPipeline()

    monkeypatch.setattr(
        qp.planner,
        "plan",
        lambda q: {"intent": "fact_lookup", "strategy": "vector_only", "entities": ["星环公司"]},
    )

    fake_triples = [
        {"source": "Transwarp", "relation": "PROVIDES", "target": "Data Cloud"},
        {"source": "Data Cloud", "relation": "APPLIES_TO", "target": "Finance"},
        {"source": "Transwarp", "relation": "PROVIDES", "target": "TXData"},
    ]
    fake_relations = [
        "Transwarp -[PROVIDES]- Data Cloud",
        "Data Cloud -[APPLIES_TO]- Finance",
        "Transwarp -[PROVIDES]- TXData",
    ]

    monkeypatch.setattr(
        qp,
        "graph_retrieve_from_entities",
        lambda entities: {"relations": fake_relations, "triples": fake_triples},
    )
    monkeypatch.setattr(
        qp,
        "_get_precompute",
        lambda entity, graph_version=None: {"summary": "Transwarp 提供 Data Cloud。", "relations": fake_triples},
    )

    done = _first_done_event(qp, "星环公司", mode="hybrid")
    assert done is not None

    graph = done.get("graph") or {}
    debug = done.get("debug") or {}

    for k in ("used", "relations", "count", "two_hop", "summary"):
        assert k in graph

    for k in (
        "graph_used",
        "graph_relations_count",
        "answer_mode",
        "precompute_hit",
        "entity_raw",
        "entity_canonical",
        "entity_used_for_graph",
    ):
        assert k in debug

    assert debug["entity_raw"] == "星环公司"
    assert debug["entity_canonical"] == "transwarp"
    assert debug["entity_used_for_graph"] == "transwarp"
    assert debug["graph_relations_count"] >= 3
    assert debug["answer_mode"] == "graph"
