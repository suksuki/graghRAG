from core.ingestion import SMEIngestor
from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine

"""
Shared long-lived engine instances for the API layer.

Controllers和路由应通过这里访问引擎，而不是自己 new，
这样方便统一重载（例如在 /settings/update 后重建引擎）。
"""

ingestor = SMEIngestor()
graph_engine = GraphEngine()
vector_engine = VectorEngine()

