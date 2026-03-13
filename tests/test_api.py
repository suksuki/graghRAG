import pytest
from fastapi.testclient import TestClient
from api.main import app
from configs.config import settings
import httpx
import logging

@pytest.fixture
def client():
    return TestClient(app)


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
