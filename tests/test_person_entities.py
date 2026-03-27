from core.document_insight_service import run_document_insight
from core.person_entity_store import _extract_json_array


def test_extract_person_entities_json_array():
    raw = """
```json
[
  {"person":"李经理","title":"产品负责人","projects":["AI训练平台"]}
]
```
"""
    rows = _extract_json_array(raw)
    assert isinstance(rows, list)
    assert rows[0]["person"] == "李经理"
    assert rows[0]["title"] == "产品负责人"


def test_document_insight_person_short_circuit(monkeypatch):
    import core.person_entity_store as pes

    monkeypatch.setattr(
        pes,
        "fetch_person_entities",
        lambda file_name, query_text, limit=8: [
            {
                "person": "李经理",
                "title": "产品负责人",
                "projects": ["AI训练平台"],
                "source_doc": file_name,
            }
        ],
    )

    class Dummy:
        pass

    out = run_document_insight(
        vector_engine=Dummy(),
        graph_driver=Dummy(),
        llm=Dummy(),
        query="李经理负责什么？",
        top_k=5,
        doc_id="demo.pdf",
        include_graph_relations=True,
        lang="zh",
    )
    assert out["insufficient_evidence"] is False
    assert out["source"] == "facts"
    assert out["debug"]["person_entity_short_circuit"] is True
    assert out["debug"]["person_entity_hit_count"] == 1
    assert "李经理" in out["summary"]
    assert out["supporting_chunks"][0]["file_name"] == "demo.pdf"
