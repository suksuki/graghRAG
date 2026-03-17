---
name: graphrag-query
description: >
  Rules and conventions for the GraphRAG query architecture, including QueryPlanner,
  QueryPipeline, GraphTraversalEngine, and ContextBuilder. Use this when changing how
  queries are understood, planned, or executed.
---

# GraphRAG Query Architecture

## High-level Flow

All query logic should follow this conceptual pipeline:

```text
User Query
  ↓
QueryPlanner
  ↓
Strategy (llm_only / vector / graph / hybrid / graph_traversal)
  ↓
Retrieval (VectorEngine / GraphEngine)
  ↓
GraphTraversalEngine (multi-hop context)
  ↓
ContextBuilder (merge all contexts)
  ↓
LLM synthesis (final answer + sources)
```

## Module Responsibilities

- **QueryPlanner (`pipelines/query_planner.py`)**
  - Performs *only* query understanding:
    - Intent detection (greeting, fact_lookup, relationship_query, document_search, graph_reasoning).
    - Strategy mapping (llm_only, vector, graph, hybrid, graph_traversal).
    - Light-weight entity extraction (quoted strings, capitalized tokens/phrases).
  - **MUST NOT**:
    - Call databases, LLMs, or any retrieval engines.
    - Depend on FastAPI, controllers, or routes.

- **QueryPipeline (`pipelines/query_pipeline.py`)**
  - Orchestrates the full query execution:
    - Logs incoming query and mode.
    - Calls `QueryPlanner.plan(query)` to obtain `{intent, strategy, entities}`.
    - Maps planner strategy to concrete execution plan:
      - `llm_only` → direct LLM reply (no retrieval).
      - `vector` / `graph` / `hybrid` → call VectorEngine / GraphEngine query engines.
      - `graph_traversal` → trigger `GraphTraversalEngine` while still using existing graph/vector engines.
    - Applies rerank + context compression.
    - Calls `llm_synthesis` to build final `{answer, sources, graph_context}`.
  - **Must keep backward compatibility** with existing `mode` argument:
    - `mode="vector"` forces vector-only retrieval.
    - `mode="graph"` forces graph-only retrieval.
    - `mode="hybrid"` or `None` uses planner strategy.

- **GraphTraversalEngine (`core/graph_traversal.py`)**
  - Encapsulates multi-hop traversal logic:
    - Uses Neo4j Cypher only.
    - Returns normalized `{nodes, edges}` subgraphs.
  - **MUST NOT**:
    - Call LLMs directly.
    - Perform vector retrieval or mutate the graph.

- **ContextBuilder (future evolution)**
  - Responsible for merging:
    - Vector retrieval nodes.
    - Graph retrieval nodes.
    - Graph traversal subgraphs.
  - Produces a single context object for `llm_synthesis` to consume.

## Core Rules

- **Planner isolation**
  - `QueryPlanner` is *understanding-only*. If you need data access, do it in `QueryPipeline` or deeper layers.

- **Execution boundaries**
  - `QueryPipeline` is the only place that calls:
    - `VectorEngine.get_query_engine().query(...)`
    - `GraphEngine.get_query_engine().query(...)`
    - `GraphTraversalEngine.traverse(...)`

- **Strategy handling**
  - When adding new strategies, update:
    - `QueryPlanner._map_intent_to_strategy`.
    - The mapping logic in `QueryPipeline.run` that converts planner strategies into execution branches.

- **Logging**
  - Always log at least:
    - Incoming query + mode.
    - Planner output (intent, strategy, entities).
    - Final chosen execution strategy.
    - Traversal context size when `graph_traversal` is used.

