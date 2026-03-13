import nest_asyncio
nest_asyncio.apply()

from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine
import logging

logging.basicConfig(level=logging.INFO)

def test_query():
    print("Initializing engines...")
    ge = GraphEngine()
    
    print("Getting query engine...")
    query_engine = ge.get_query_engine()
    
    query = "Antigravity 是谁？"
    print(f"Querying: {query}")
    response = query_engine.query(query)
    
    print("\n--- Response ---")
    print(response)
    print("----------------\n")

if __name__ == "__main__":
    test_query()
