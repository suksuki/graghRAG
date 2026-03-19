from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.ingestion import SMEIngestor
from core.graph_engine import GraphEngine
from core.vector_store import VectorEngine

"""
Shared long-lived engine instances for the API layer.

Controllers和路由应通过这里访问引擎，而不是自己 new，
这样方便统一重载（例如在 /settings/update 后重建引擎）。
"""


@dataclass
class _Container:
    graph_engine: GraphEngine | None = None
    vector_engine: VectorEngine | None = None
    ingestor: SMEIngestor | None = None


_container = _Container()


def get_graph_engine() -> GraphEngine:
    if _container.graph_engine is None:
        _container.graph_engine = GraphEngine()
    return _container.graph_engine


def get_vector_engine() -> VectorEngine:
    if _container.vector_engine is None:
        _container.vector_engine = VectorEngine()
    return _container.vector_engine


def get_ingestor() -> SMEIngestor:
    if _container.ingestor is None:
        _container.ingestor = SMEIngestor(
            graph_engine=get_graph_engine(),
            vector_engine=get_vector_engine(),
        )
    return _container.ingestor


def reset_engines() -> None:
    _container.graph_engine = GraphEngine()
    _container.vector_engine = VectorEngine()
    _container.ingestor = SMEIngestor(
        graph_engine=_container.graph_engine,
        vector_engine=_container.vector_engine,
    )


class _Proxy:
    def __init__(self, getter):
        object.__setattr__(self, "_getter", getter)

    def _target(self) -> Any:
        return object.__getattribute__(self, "_getter")()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target(), name, value)

    def __repr__(self) -> str:
        return repr(self._target())


ingestor = _Proxy(get_ingestor)
graph_engine = _Proxy(get_graph_engine)
vector_engine = _Proxy(get_vector_engine)
