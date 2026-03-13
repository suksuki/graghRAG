from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class QueryRequest(BaseModel):
    """查询请求体."""

    query: str
    mode: str = "hybrid"  # hybrid, graph, vector


class QueryResponse(BaseModel):
    """查询响应体."""

    answer: str
    sources: List[Dict[str, Any]]
    graph_context: Optional[List[str]] = None


class TestRequest(BaseModel):
    """连接测试请求体."""

    type: Optional[str] = None
    url: Optional[str] = None

