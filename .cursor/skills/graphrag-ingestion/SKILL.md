---
name: graphrag-ingestion
description: >
  Rules for the document ingestion pipeline, including loading, chunking, and
  writing into the vector store and Neo4j graph. Use this when touching
  core/ingestion.py, core/vector_store.py, or core/graph_engine.py.
---

# GraphRAG Ingestion Pipeline

## End-to-end Flow

```text
Raw Document
  ↓
Loader (SimpleDirectoryReader)
  ↓
Chunking (SentenceSplitter / node builders)
  ↓
Nodes (LlamaIndex Node objects)
  ↓
VectorEngine (pgvector)
  ↓
GraphEngine (Neo4j + extraction LLM)
```

## Module Responsibilities

- **`core/ingestion.py`**
  - Orchestrates the full ingestion flow:
    - Scan `settings.DATA_RAW_DIR` for files.
    - Determine which files are already indexed in graph/vector stores.
    - Load new documents and split into nodes.
    - Write nodes to `VectorEngine` and `GraphEngine`.
  - **Must be idempotent**:
    - Re-running ingestion should not duplicate graph nodes or vectors for already-indexed files.
    - Uses helpers like `GraphEngine.get_indexed_files()` and vector-store checks.
  - Must not contain any FastAPI routing or HTTP-specific logic.

- **`core/vector_store.py` (VectorEngine)**
  - Encapsulates all PGVector operations:
    - Table creation / migration.
    - Insert / delete / query for embeddings.
  - Should expose high-level methods:
    - `add_documents(nodes)`
    - `delete_document(filename)`
    - `get_query_engine()`
  - Must not import FastAPI or controller modules.

- **`core/graph_engine.py` (GraphEngine)**
  - Encapsulates:
    - Neo4j store (`Neo4jPropertyGraphStore`).
    - Extraction LLM for building graph indices.
    - Query LLM + embedding model for graph querying.
  - Responsible for:
    - `create_index(nodes, ...)` — building/expanding the property graph.
    - `delete_document(filename)` — removing all nodes for a given file.
    - `get_query_engine()` — constructing a graph-aware query engine.

## Idempotency & Independence

- **Idempotency**
  - Before writing, ingestion MUST check which files are already indexed in:
    - Neo4j (via `GraphEngine.get_indexed_files()`).
    - Vector store (via an equivalent vector-store helper).
  - Only process *new* files in each run.

- **Independent writes**
  - Vector writes and graph writes should be logically independent:
    - A failure in graph indexing must not corrupt or roll back vector inserts.
    - Ingestion can log and surface partial failures, but should aim to keep each subsystem consistent.

## Separation from API Layer

- No ingestion code should depend on:
  - FastAPI (`fastapi.*`).
  - `api.routes.*`.
  - HTTP-specific models (Request, Response, HTTPException).

- API controllers (e.g. `ingestion_controller`) are responsible for:
  - File upload handling and path sanitization.
  - Triggering ingestion (directly or via Celery tasks).
  - Reporting ingestion status and progress.

