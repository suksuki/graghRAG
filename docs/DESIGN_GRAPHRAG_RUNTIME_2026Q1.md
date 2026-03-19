# GraphRAG Runtime Design (2026Q1)

## Scope

This document captures the current production-oriented runtime design after the Graph-first/Graph-dominant/precompute and ingestion stability work.

It focuses on:

- Query path behavior (`Graph-first`, `Graph-dominant`, `Precompute`)
- Ingestion path behavior (incremental, controlled LLM extraction)
- Data contract between backend stream events and frontend rendering
- Observability and failure handling

---

## Query Runtime

### End-to-end path

```text
User Query
  -> QueryPlanner (intent/strategy/entities)
  -> canonical entity resolution (normalize_entity + fallback)
  -> graph retrieval first
  -> quality gate
      - pass: graph mode
      - fail: vector fallback
  -> precompute cache check (graph mode only)
      - hit: return precomputed answer (0 LLM)
      - miss: controlled LLM synthesis
  -> stream done event with graph/debug payload
```

### Graph-first + quality gate

- Graph is queried before vector in default smart path.
- Graph is considered usable if either:
  - `relations_count >= 3`, or
  - `summary` exists.
- If gate fails, vector retrieval runs as fallback.

### Graph-dominant answer mode

When `graph_used=true`:

- Prompt is graph-only (knowledge graph context, no vector chunks).
- Instructions enforce no external knowledge / no hallucination.
- `debug.answer_mode = "graph"`.

When `graph_used=false`:

- Existing vector RAG flow is used.
- `debug.answer_mode = "vector"`.

### Precompute

- Key: `graph:precompute:{entity}:{graph_version}`
- Payload:
  - `summary`
  - `relations`
  - `suggestions` (reserved field)
- Query path:
  - `graph_used=true` -> try precompute first
  - valid hit -> return directly, skip answer LLM
  - miss -> run normal synthesis
- Debug:
  - `debug.precompute_hit = true|false`

### Versioning and invalidation

- Version key: `graph:version`
- Ingestion success bumps version (`vN -> vN+1`).
- Query and precompute keys are versioned to avoid stale knowledge pollution.

---

## Ingestion Runtime

### Principles

- Incremental by default:
  - vector: skip files already in vector table
  - graph: skip files marked in Neo4j (`IngestedFile`)
- Upload path should not block API response.
- Worker status must be externally visible and fail fast on real errors.

### Controlled graph extraction

- Extraction remains LLM-based, but strongly constrained:
  - graph nodes cap: `<= 5`
  - batch size: `1`
  - extractor workers: `1`
  - `max_paths_per_chunk: 2`
  - extraction llm: `num_ctx=1024`, `num_predict=32`
  - per-batch hard timeout: `5s`, timeout batch is skipped
- Node selection before extraction:
  - dedupe by normalized text prefix
  - score by information density
  - keep top-k high-value nodes

### Failure and stall handling

- Worker writes global status with `updated_at`.
- Failed ingestion writes status as `failed` (not `idle`).
- API status endpoint detects stale processing and returns failed status with message.

---

## Stream Event Contract

`run_stream` done event must include:

- `graph` object with stable shape:
  - `used`
  - `relations` (array)
  - `count` (int)
  - `two_hop` (array)
  - `summary` (string)
- `debug` object:
  - `graph_used`
  - `graph_relations_count`
  - `answer_mode`
  - `precompute_hit`
  - `entity_raw`
  - `entity_canonical`
  - `entity_used_for_graph`

Backend normalizes graph payload before emitting done event to keep UI logic deterministic.

---

## Frontend Rendering Contract

Frontend `hasGraphData` must rely on:

- `msg.graph.relations.length > 0`, or
- `msg.graph.summary.length > 0`, or
- `msg.graph.two_hop.length > 0`, or
- `msg.debug.graph_relations_count > 0` (defensive fallback)

Suggestions entity source:

- primary: `msg.graph.relations[0].source`
- fallback: `msg.debug.entity_used_for_graph`

---

## Operational Targets

Recommended runtime targets:

- Ingestion:
  - `graph_nodes_count ~= 5`
  - total ingestion time `< 3.5s` for medium single-document cases
- Query:
  - graph-precompute hit path: sub-second
  - graph miss fallback: stable vector path, no silent failures

---

## Known Trade-offs

- Smaller extraction window improves latency and stability, may reduce tail-relation coverage.
- Top-k high-value selection prioritizes quality over breadth.
- Precompute favors speed; freshness depends on version bump and cache lifecycle.

