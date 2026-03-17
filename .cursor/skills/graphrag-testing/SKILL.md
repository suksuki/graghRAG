---
name: graphrag-testing
description: >
  Guidelines for the automated testing strategy of the GraphRAG platform.
  Use this when adding or modifying tests under tests/.
---

# GraphRAG Testing Conventions

## Test Types

- **Unit tests**
  - Target: individual controllers, pure functions, small helpers.
  - Import from:
    - `api.controllers.*`
    - `core.*`
  - Use mocks/fakes for external systems (Neo4j, Postgres, Ollama) where appropriate.

- **API tests**
  - Use `TestClient` from `fastapi.testclient`.
  - Import `app` from `api.main`.
  - Hit real HTTP endpoints (e.g. `/query`, `/upload`, `/settings`).

- **Integration tests**
  - May talk to real services:
    - Neo4j
    - Postgres (pgvector)
    - Ollama
  - Exercise end-to-end flows such as:
    - Upload → Ingestion → Query.
    - Deletion → Graph/Vector cleanup.

## General Rules

- **pytest as the default runner**
  - All tests should be runnable via:
    ```bash
    pytest
    ```
  - Do not introduce alternative test runners without a strong reason.

- **File structure**
  - Place tests under `tests/`.
  - Group by feature or module (e.g. `test_ingestion.py`, `test_query_pipeline.py`).

- **Fixtures**
  - Use shared fixtures in `tests/conftest.py` to:
    - Provide a `client` (`TestClient` instance) for API tests.
    - Reset external state between tests (Neo4j, Postgres, data/raw directory).
  - Autouse fixtures may be used to ensure a clean environment for each test run.

## What to Assert

- **Unit tests**
  - Input → output behavior of controllers and helpers.
  - That controllers:
    - Call engines with correct parameters (mock assertions).
    - Translate domain errors into appropriate exceptions.

- **API tests**
  - HTTP status codes (200/400/500, etc.).
  - Response schema shape (keys present, types correct).
  - Backward compatibility of public endpoints.

- **Integration tests**
  - Strong end-to-end invariants, such as:
    - A unique injected fact is retrievable via `/query`.
    - Ingestion does not duplicate graph or vector entries across runs.
    - Deleting a document removes its graph nodes and vectors.

## Performance & Stability

- Long-running or flaky tests should:
  - Use smaller fixtures or mock data when possible.
  - Avoid unnecessary calls to large LLMs.
  - Clearly document any dependency on external services in the test docstring.

