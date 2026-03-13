---
name: graphrag-mvc
description: >
  Enforces an MVC-style module split for the graphrag-platform backend.
  Use this when adding or refactoring API endpoints to keep models under core/,
  controllers under api/controllers/, and HTTP views under api/routes/.
---

# GraphRAG Platform MVC Conventions

## Directory Layout

- **Models (M)**:
  - `core/graph_engine.py` — Neo4j property graph engine
  - `core/vector_store.py` — PGVector-based vector store
  - `core/ingestion.py` — ingestion pipeline (document loading, splitting, graph/vector writes)
  - Pydantic schemas live in `api/schemas.py`
- **Controllers (C)**:
  - `api/controllers/` — request orchestration and business logic
  - Example: `api/controllers/query_controller.py` implements the Graph+Vector hybrid query
- **Views / Routes (V)**:
  - `api/routes/` — FastAPI `APIRouter` modules, HTTP-only concerns
  - Example: `api/routes/query_routes.py` exposes `POST /query`
- **Shared dependencies**:
  - `api/deps.py` — long-lived engine instances (`ingestor`, `graph_engine`, `vector_engine`)
  - `api/main.py` — application bootstrap, middleware, and router inclusion only

## Controller / Route Responsibilities

- **Models (`core/*` + `api/schemas.py`)**
  - Encapsulate data access and domain behavior (Neo4j, Postgres, ingestion).
  - Must NOT import FastAPI, HTTPException, or routing primitives.

- **Controllers (`api/controllers/*`)**
  - Coordinate calls to models and assemble domain-level responses.
  - Contain no HTTP-specific status codes or request/response objects.
  - May import `api.deps` to access shared engines.
  - Should return plain Python data structures or domain objects that match schemas.

- **Routes (`api/routes/*`)**
  - Define FastAPI routes and `APIRouter` instances.
  - Handle HTTP concerns only: parsing `Request`/`Response`, raising `HTTPException`, and wiring dependencies.
  - Call into controllers for actual business logic.

- **Main (`api/main.py`)**
  - Creates `FastAPI(app)` and installs middlewares (CORS, etc.).
  - Includes routers from `api.routes.*`.
  - Exports `app` (and, for backward compatibility, re-exports engines from `api.deps` when needed).
  - Should NOT contain business logic or raw DB/LLM calls.

## How to Add a New Feature

When adding or refactoring an endpoint:

1. **Define schemas** in `api/schemas.py` (request / response models).
2. **Implement controller logic** in `api/controllers/<feature>_controller.py`:
   - Accept typed parameters or schema objects.
   - Call `core/*` models and `api.deps` engines as needed.
   - Return data that matches the response schema.
3. **Expose HTTP routes** in `api/routes/<feature>_routes.py`:
   - Create an `APIRouter`.
   - Declare path operations using the schemas and controller functions.
   - Convert domain errors into `HTTPException` with appropriate status codes.
4. **Include router** in `api/main.py`:
   - Import the router and call `app.include_router(router)` (preferably in a startup hook).

## Refactoring Existing Code

When refactoring legacy code that currently lives in `api/main.py`:

1. Move Pydantic models to `api/schemas.py`.
2. Move pure business logic (LLM calls, graph/vector orchestration) into `api/controllers/*`.
3. Replace inline FastAPI route functions with thin wrappers in `api/routes/*` that delegate to controllers.
4. Keep `api/main.py` as slim as possible: bootstrap + router inclusion + app metadata.

## Testing Notes

- Unit tests that exercise controllers should import from `api.controllers.*` and use mock engines when needed.
- API-level tests (`TestClient`) should import `app` from `api.main` and hit HTTP endpoints under `/`.
- Avoid importing controllers directly from route modules; routes depend on controllers, not vice versa.

