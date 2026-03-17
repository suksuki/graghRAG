---
name: graphrag-graph
description: >
  Rules for interacting with the Neo4j knowledge graph, including Cypher queries,
  graph traversal, and subgraph extraction. Use this when touching GraphEngine,
  GraphTraversalEngine, or any Graph Explorer APIs.
---

# GraphRAG Graph Store Conventions

## Scope

- `core/graph_engine.py`
- `core/graph_traversal.py`
- `api/controllers/graph_controller.py`
- `api/routes/graph_routes.py`

## Access Rules

- **Single entrypoint for graph store**
  - All graph access must go through `GraphEngine.graph_store` or `GraphTraversalEngine`.
  - Do NOT open arbitrary Neo4j drivers elsewhere in the codebase.

- **Cypher execution**
  - Use `GraphEngine.graph_store._driver.session()` (wrapped in helper functions) for raw Cypher when LlamaIndex
    abstractions are not sufficient.
  - Encapsulate Cypher strings in:
    - `GraphEngine` methods for core operations (indexing, delete-by-file, building query engines).
    - `GraphTraversalEngine` for multi-hop traversal.
    - `graph_controller` for simple visualization queries.

## Traversal Rules

- **GraphTraversalEngine**
  - Is the **only** module allowed to perform generic multi-hop traversals:
    - E.g. `MATCH p=(a {name:$name})-[*1..$max_hops]-(b) RETURN p`.
  - Must return normalized subgraphs:
    ```json
    {
      "nodes": [
        { "id": ..., "labels": [...], "properties": {...} }
      ],
      "edges": [
        { "source": ..., "target": ..., "type": "...", "properties": {...} }
      ]
    }
    ```
  - Must not mutate the graph (no `CREATE`/`MERGE`/`DELETE` in traversal methods).

## Graph Explorer API Rules

- All public graph APIs under `/graph/*` must:
  - Return `{nodes, edges}` as described above.
  - Deduplicate nodes by `id`.
  - Preserve edge directions (`source` → `target`) and `type`.

- Typical endpoints:
  - `/graph/nodes` — lightweight sample of nodes.
  - `/graph/relations` — sampled relations with neighbor nodes.
  - `/graph/subgraph?entity=...` — 1-hop neighborhood around a named entity.
  - `/graph/path?a=...&b=...` — shortest path between two named entities.
  - `/graph/node_documents?entity=...` — document nodes linked to a given entity.

## Safety & Performance

- Limit traversal depth (`max_hops`) to small integers (1–4) unless you have explicit justification.
- Always apply `LIMIT` on traversal queries to avoid unbounded result sets.
- When adding new Cypher, prefer:
  - Parameterized queries (`$name`, `$limit`) instead of string interpolation.
  - Narrow MATCH patterns over global `MATCH (n)-[r]->(m)` scans when possible.

