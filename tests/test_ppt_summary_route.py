from types import SimpleNamespace

import core.document_insight_service as dis


class _DummyLLM:
    def __init__(self, outputs):
        self._outputs = list(outputs)

    def complete(self, _prompt):
        if not self._outputs:
            return ""
        return self._outputs.pop(0)


class _CaptureRetriever:
    def __init__(self, nodes):
        self.nodes = nodes
        self.last_query = None

    def retrieve(self, query):
        self.last_query = query
        return self.nodes


class _DummyVector:
    def __init__(self, nodes):
        self._retriever = _CaptureRetriever(nodes)
        self.vector_store = object()
        self.embed_model = object()

    def get_retriever(self, similarity_top_k=5):
        _ = similarity_top_k
        return self._retriever


def _make_nodes(file_name="demo.pptx"):
    node = SimpleNamespace(
        text="该文档描述首次合同、变更合同与月度支付流程。",
        metadata={"file_name": file_name, "entities": ["合同流程"]},
        id_="c1",
    )
    return [SimpleNamespace(node=node, score=0.9)]


def test_agentic_rag_path_returns_rag_source(monkeypatch):
    monkeypatch.setattr(dis, "_retrieve_doc_scoped", lambda **kwargs: _make_nodes(kwargs["doc_filter"]))
    llm = _DummyLLM(
        [
            '{"need_retrieval": true, "focus": "流程", "intent": "summary"}',
            "该文档流程包括首次合同、合同变更和月度支付三个阶段。",
        ]
    )
    out = dis.run_document_insight(
        vector_engine=_DummyVector(_make_nodes()),
        graph_driver=SimpleNamespace(),
        llm=llm,
        query="请总结该文档流程",
        top_k=5,
        doc_id="demo.pptx",
        include_graph_relations=False,
        lang="zh",
    )
    assert out["source"] == "rag"
    assert out["source"] in {"rag", "facts"}
    assert out["debug"]["planner_focus"] == "流程"
    assert len(out["supporting_chunks"]) == 1


def test_agentic_retrieval_uses_query_plus_focus(monkeypatch):
    monkeypatch.setattr(dis, "_retrieve_doc_scoped", lambda **kwargs: _make_nodes(kwargs["doc_filter"]))
    llm = _DummyLLM(
        [
            '{"need_retrieval": true, "focus": "团队职责", "intent": "reasoning"}',
            "文档未明确市场团队，但包含营业相关职责。",
        ]
    )
    out = dis.run_document_insight(
        vector_engine=_DummyVector(_make_nodes()),
        graph_driver=SimpleNamespace(),
        llm=llm,
        query="是否存在市场团队？",
        top_k=5,
        doc_id="demo.pptx",
        include_graph_relations=False,
        lang="zh",
    )
    assert out["source"] == "rag"
    assert out["source"] in {"rag", "facts"}
    assert out["debug"]["planner_focus"] == "团队职责"
    assert out["debug"]["planner_intent"] == "reasoning"


def test_planner_parse_failure_falls_back_defaults(monkeypatch):
    monkeypatch.setattr(dis, "_retrieve_doc_scoped", lambda **kwargs: _make_nodes(kwargs["doc_filter"]))
    llm = _DummyLLM(
        [
            "not-json",
            "未提及该信息。",
        ]
    )
    out = dis.run_document_insight(
        vector_engine=_DummyVector(_make_nodes()),
        graph_driver=SimpleNamespace(),
        llm=llm,
        query="电子合同由谁管理？",
        top_k=5,
        doc_id="demo.pptx",
        include_graph_relations=False,
        lang="zh",
    )
    assert out["source"] == "rag"
    assert out["source"] in {"rag", "facts"}
    assert out["debug"]["planner_need_retrieval"] is True
