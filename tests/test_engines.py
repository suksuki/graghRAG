import pytest
from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine
from core.ingestion import SMEIngestor
import os


@pytest.mark.integration
def test_graph_engine_initialization():
    """Test that GraphEngine can be initialized without errors."""
    engine = GraphEngine()
    assert engine.llm is not None
    assert engine.graph_store is not None

@pytest.mark.integration
def test_vector_engine_initialization():
    """Test that VectorEngine can be initialized."""
    engine = VectorEngine()
    assert engine.vector_store is not None

@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingestor_initialization():
    """Test that SMEIngestor can be initialized."""
    ingestor = SMEIngestor()
    assert ingestor.graph_engine is not None
    assert ingestor.vector_engine is not None

@pytest.mark.integration
def test_graph_query_engine():
    """Test that graph query engine can be generated."""
    engine = GraphEngine()
    query_engine = engine.get_query_engine()
    assert query_engine is not None
