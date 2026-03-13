import pytest
from fastapi.testclient import TestClient
from api.main import app
from configs.config import settings
import os
import time

@pytest.fixture
def client():
    return TestClient(app)

def test_full_ingestion_and_query_flow(client):
    """Regression test: Upload a specific fact, ingest it, and query it."""
    # 1. Prepare unique fact
    unique_id = int(time.time())
    fact_content = f"The secret password for project Antigravity is ALPHA-{unique_id}."
    file_name = f"test_fact_{unique_id}.txt"
    
    # 2. Upload via API
    files = [("files", (file_name, fact_content, "text/plain"))]
    response = client.post("/upload", files=files)
    assert response.status_code == 200
    assert file_name in response.json()["files"]
    
    # Verify file is on disk
    file_path = os.path.join(settings.DATA_RAW_DIR, file_name)
    assert os.path.exists(file_path)
    
    # 3. Manually trigger ingestion synchronously for the test
    # (Since background tasks are hard to track in a simple test)
    from api.main import ingestor
    ingestor.ingest_data()
    
    # 4. Query the fact
    query_payload = {
        "query": "What is the secret password for project Antigravity?",
        "mode": "hybrid"
    }
    
    # Give it a couple of retries if needed, though sync ingestion should be enough
    max_retries = 3
    for i in range(max_retries):
        response = client.post("/query", json=query_payload)
        assert response.status_code == 200
        answer = response.json()["answer"]
        
        if f"ALPHA-{unique_id}" in answer:
            break
        print(f"Retry {i+1}: Fact not found in answer yet. Waiting...")
        time.sleep(2)
    else:
        pytest.fail(f"Fact 'ALPHA-{unique_id}' was not found in the answer despite ingestion. Answer: {answer}")

    print("Regression test PASSED: System successfully ingested and retrieved new knowledge.")
