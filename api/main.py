import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from configs.config import settings
from api.deps import ingestor, graph_engine, vector_engine  # re-export for tests
from api.routes.query_routes import router as query_router
from api.routes.settings_routes import router as settings_router
from api.routes.ingestion_routes import router as ingestion_router
from api.routes.graph_routes import router as graph_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="GraphRAG Platform for SMEs - Multi-modal Knowledge Management",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router)
app.include_router(settings_router)
app.include_router(ingestion_router)
app.include_router(graph_router)


@app.get("/")
async def root():
    return {
        "project": settings.PROJECT_NAME,
        "status": "online",
        "engines": {
            "graph": "Neo4j",
            "vector": "PGVector",
            "llm": settings.LLM_MODEL,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
