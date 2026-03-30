import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from configs.config import settings


def _mock_document_insight_payload():
    return {
        "answer": "Architecture overview summary.",
        "summary": "Architecture overview summary.",
        "source": "rag",
        "key_entities": ["GraphRAG"],
        "key_relations": [
            {"source": "GraphRAG", "relation": "uses", "target": "PGVector"}
        ],
        "supporting_chunks": [
            {
                "ref_index": 1,
                "file_name": "architecture.md",
                "snippet": "GraphRAG uses PGVector for chunk retrieval.",
            }
        ],
        "structured_evidence": [
            {
                "role": "Architecture",
                "persons": ["Platform team"],
                "ref_indices": [1],
                "file_names": ["architecture.md"],
            }
        ],
        "insufficient_evidence": False,
        "decision": {"conflicts": [], "support_groups": None},
        "debug": {
            "pre_filter_hits": 1,
            "post_filter_hits": 1,
            "final_used_chunks": 1,
            "doc_scope_applied": False,
        },
    }


def _mock_hybrid_search_payload():
    return {
        "query": "integration test hybrid",
        "results": [
            {
                "type": "chunk",
                "text": "Hybrid search returns vector-backed text evidence.",
                "score": 0.92,
            }
        ],
        "debug": {
            "vector_hits": 1,
            "graph_edges": 0,
            "graph_nodes": 0,
        },
    }


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


@pytest.fixture
def contract_client():
    from api.routes.document_insight_routes import router as document_insight_router
    from api.routes.hybrid_search_routes import router as hybrid_search_router

    contract_app = FastAPI()
    contract_app.include_router(document_insight_router)
    contract_app.include_router(hybrid_search_router)
    return TestClient(contract_app)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ollama_direct_connection():
    """Diagnostic test to probe the Ollama server directly from python."""
    target_url = settings.OLLAMA_BASE_URL.rstrip('/')
    print(f"\nProbing Ollama at: {target_url}/api/tags")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{target_url}/api/tags", timeout=10.0)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            assert response.status_code == 200
        except httpx.ConnectTimeout:
            pytest.fail("Connection Timeout: Could not reach 192.168.0.10 within 10s. Check firewall/network.")
        except httpx.ConnectError as e:
            pytest.fail(f"Connection Error: {str(e)}. Is the Ollama service running and bound to 0.0.0.0?")
        except Exception as e:
            pytest.fail(f"Unexpected Error: {type(e).__name__} - {str(e)}")

def test_api_settings_endpoint(client):
    """Test the settings retrieval endpoint."""
    response = client.get("/settings")
    assert response.status_code == 200
    data = response.json()
    assert "ollama_base_url" in data
    assert "llm_model" in data

def test_api_ping(client):
    """Simple ping to root."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"


def test_document_insight_endpoint(contract_client, monkeypatch):
    """POST /api/v1/insights/document 走 route + response_model 契约。"""
    monkeypatch.setattr(
        "api.routes.document_insight_routes._get_document_insight_controller",
        lambda: (lambda body, ui_lang=None: _mock_document_insight_payload()),
    )
    response = contract_client.post(
        "/api/v1/insights/document",
        json={"query": "architecture overview", "top_k": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "summary" in data
    assert "key_entities" in data
    assert "key_relations" in data
    assert "supporting_chunks" in data
    assert "structured_evidence" in data
    assert "insufficient_evidence" in data
    assert data["answer"] == data["summary"]
    assert data.get("source") in ("rag", "facts", None)
    assert "debug" in data
    assert isinstance(data["debug"], dict)
    assert "pre_filter_hits" in data["debug"]
    assert "post_filter_hits" in data["debug"]
    assert "final_used_chunks" in data["debug"]
    assert "doc_scope_applied" in data["debug"]
    assert "decision" in data
    assert isinstance(data["decision"], dict)
    assert "conflicts" in data["decision"]
    assert isinstance(data["decision"]["conflicts"], list)
    assert "support_groups" in data["decision"]
    sg = data["decision"]["support_groups"]
    assert sg is None or isinstance(sg, dict)
    assert isinstance(data["supporting_chunks"], list)
    assert isinstance(data["structured_evidence"], list)
    for ch in data["supporting_chunks"]:
        assert "ref_index" in ch
        assert isinstance(ch["ref_index"], int)
    for row in data["structured_evidence"]:
        assert "role" in row
        assert "persons" in row
        assert "ref_indices" in row
        assert "file_names" in row
    for rel in data["key_relations"]:
        assert rel.get("source")
        assert rel.get("relation")
        assert rel.get("target")


def test_hybrid_search_endpoint(contract_client, monkeypatch):
    """POST /api/v1/hybrid-search 走 route + response_model 契约。"""
    monkeypatch.setattr(
        "api.routes.hybrid_search_routes._get_hybrid_search_controller",
        lambda: (lambda body: _mock_hybrid_search_payload()),
    )
    response = contract_client.post(
        "/api/v1/hybrid-search",
        json={
            "query": "integration test hybrid",
            "top_k": 3,
            "graph_expand_k": 10,
            "include_fallback": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("query") == "integration test hybrid"
    assert "results" in data
    assert "debug" in data
    assert "vector_hits" in data["debug"]
    assert "graph_edges" in data["debug"]


def test_knowledge_hub_docs_list(client):
    """GET /knowledge/docs 返回文档列表容器（可为空）；避免与 FastAPI /docs Swagger 冲突。"""
    response = client.get("/knowledge/docs")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert isinstance(data["documents"], list)


def test_insight_log_endpoint(client):
    """POST /log 认知摩擦埋点：204，无 body。"""
    r = client.post(
        "/log",
        json={
            "event": "click_reference",
            "ts": 1700000000000,
            "session_id": "s_test_session",
            "doc_id": "doc_a",
            "insight_id": "q1",
            "payload": {"ref_id": "1", "position": "summary"},
        },
    )
    assert r.status_code == 204
    assert r.content == b""


def test_friction_eval_endpoint(client):
    """POST /telemetry/friction-eval：结构正确（可无历史事件）。"""
    r = client.post(
        "/telemetry/friction-eval",
        json={"session_id": "s_friction_smoke", "log_candidate": False},
    )
    assert r.status_code == 200
    data = r.json()
    assert "friction_type" in data
    assert "suggested_v3" in data
    assert "triggers_fired" in data
    assert "counts" in data
    assert "signals" in data
    assert data.get("event_count") is not None


def test_knowledge_hub_search(client):
    """GET /knowledge/search 空查询与带查询均可 200。"""
    r0 = client.get("/knowledge/search")
    assert r0.status_code == 200
    d0 = r0.json()
    assert "results" in d0
    assert isinstance(d0["results"], list)
    r1 = client.get("/knowledge/search?q=smoke+test&top_k=3")
    assert r1.status_code == 200
    d1 = r1.json()
    assert "query" in d1
    assert "results" in d1
    assert isinstance(d1["results"], list)


def test_corpus_insight_endpoint(client):
    """POST /insights/corpus 返回结构正确（无元数据时也可 200）。"""
    response = client.post("/insights/corpus", json={"top_k_docs": 5})
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "top_topics" in data
    assert "top_entities" in data
    assert "key_insights" in data
    assert "closing_takeaway" in data
    assert "top_keywords" in data
    assert "docs_analyzed" in data
    assert isinstance(data["key_insights"], list)

@pytest.mark.integration
def test_api_settings_test_endpoint(client):
    """Integration: /settings/test 需要真实 Ollama。"""
    payload = {
        "type": "llm",
        "url": settings.OLLAMA_BASE_URL
    }
    response = client.post("/settings/test", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Found" in data["message"]
