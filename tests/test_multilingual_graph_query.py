from types import SimpleNamespace

from api.controllers import graph_controller as gc
from api.controllers import query_controller as qc
from api.schemas import QueryRequest
from core.lang_detect import detect_lang, resolve_query_language
from core.lang_guard import enforce_language
from pipelines.query_pipeline import QueryPipeline


class _FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


def test_detect_lang_and_resolve_query_language():
    assert detect_lang("星环是做什么的") == "zh"
    assert detect_lang("What does Transwarp do?") == "en"
    assert detect_lang("트랜스워프가 뭐예요?") == "ko"

    info = resolve_query_language("What does Transwarp do?", "zh")
    assert info["lang_ui"] == "zh"
    assert info["lang_detected"] == "en"
    assert info["lang_final"] == "en"
    assert info["suggest_switch"] is True


def test_enforce_language_rewrites_when_needed():
    llm = SimpleNamespace(complete=lambda prompt: "트랜스워프는 데이터 클라우드를 제공합니다.")

    rewritten = enforce_language("Transwarp 提供 Data Cloud。", "ko", llm=llm)

    assert rewritten == "트랜스워프는 데이터 클라우드를 제공합니다."


def test_precompute_key_is_scoped_by_language():
    zh_pipeline = QueryPipeline(lang="zh")
    en_pipeline = QueryPipeline(lang="en")

    zh_key = zh_pipeline._precompute_key("Transwarp", graph_version="v-test")
    en_key = en_pipeline._precompute_key("Transwarp", graph_version="v-test")

    assert zh_key == "graph:precompute:transwarp:zh:v-test"
    assert en_key == "graph:precompute:transwarp:en:v-test"
    assert zh_key != en_key


def test_query_cache_key_is_scoped_by_language():
    zh_pipeline = QueryPipeline(lang="zh")
    en_pipeline = QueryPipeline(lang="en")

    zh_key = zh_pipeline._query_cache_key("what is transwarp", graph_version="v-test")
    en_key = en_pipeline._query_cache_key("what is transwarp", graph_version="v-test")

    assert zh_key == "what is transwarp|zh|v-test"
    assert en_key == "what is transwarp|en|v-test"
    assert zh_key != en_key


def test_precompute_summary_and_answer_follow_english():
    pipeline = QueryPipeline(lang="en")
    triples = [
        {"source": "Transwarp", "relation": "PROVIDES", "target": "Data Cloud"},
        {"source": "Transwarp", "relation": "PROVIDES", "target": "TXData"},
        {"source": "Data Cloud", "relation": "APPLIES_TO", "target": "Finance"},
    ]

    summary = pipeline._build_graph_summary(triples, min_relations=0)
    answer = pipeline._build_precompute_answer({"summary": "", "relations": triples}, "Transwarp")

    assert summary == "Transwarp provides Data Cloud, TXData and is mainly applied in Finance."
    assert answer.startswith("Known graph relations:")
    assert "Transwarp -[PROVIDES]-> Data Cloud" in answer


def test_precompute_summary_and_answer_follow_korean():
    pipeline = QueryPipeline(lang="ko")
    triples = [
        {"source": "Transwarp", "relation": "PROVIDES", "target": "Data Cloud"},
        {"source": "Transwarp", "relation": "PROVIDES", "target": "TXData"},
        {"source": "Data Cloud", "relation": "APPLIES_TO", "target": "Finance"},
    ]

    summary = pipeline._build_graph_summary(triples, min_relations=0)
    answer = pipeline._build_precompute_answer({"summary": "", "relations": triples}, "Transwarp")

    assert summary == "Transwarp는 Data Cloud, TXData를 제공하며, 주로 Finance 분야에 적용됩니다."
    assert answer.startswith("확인된 그래프 관계:")
    assert "Transwarp -[PROVIDES]-> Data Cloud" in answer


def test_get_precompute_rewrites_stale_summary_to_target_language():
    pipeline = QueryPipeline(lang="ko")
    pipeline.answer_llm = SimpleNamespace(complete=lambda prompt: "트랜스워프는 Data Cloud를 제공합니다.")
    pipeline.query_cache = _FakeCache()
    pipeline.query_cache.set(
        pipeline._precompute_key("Transwarp", graph_version="v-test"),
        {"summary": "Transwarp 提供 Data Cloud。", "relations": []},
    )

    pre = pipeline._get_precompute("Transwarp", graph_version="v-test")

    assert pre is not None
    assert pre["summary"] == "트랜스워프는 Data Cloud를 제공합니다."


def test_suggested_questions_controller_follows_language(monkeypatch):
    monkeypatch.setattr(
        gc,
        "_run_cypher",
        lambda query, params=None: [{"a_name": "Transwarp", "b_name": "Data Cloud"}],
    )

    zh_questions = gc.suggested_questions_controller(limit=1, lang="zh")
    en_questions = gc.suggested_questions_controller(limit=1, lang="en")
    ko_questions = gc.suggested_questions_controller(limit=1, lang="ko")

    assert zh_questions["questions"] == ["Transwarp 和 Data Cloud 是什么关系？"]
    assert en_questions["questions"] == ["How is Transwarp related to Data Cloud?"]
    assert ko_questions["questions"] == ["Transwarp와 Data Cloud는 어떤 관계인가요?"]


def test_entity_suggestions_cache_is_scoped_by_language(monkeypatch):
    fake_cache = _FakeCache()

    monkeypatch.setattr(gc, "_graph_cache", fake_cache)
    monkeypatch.setattr(gc, "_resolve_entity_node_name", lambda entity: "Transwarp")
    monkeypatch.setattr(gc, "_resolve_canonical_entity", lambda entity: "Transwarp")
    monkeypatch.setattr(
        gc,
        "graph_engine",
        SimpleNamespace(llm=SimpleNamespace(complete=lambda prompt: "")),
    )

    def _fake_run_cypher(query, params=None):
        if "RETURN type(r) AS rel, b.name AS name" in query:
            return [{"rel": "PROVIDES", "name": "Data Cloud"}]
        if "RETURN b.name AS product, collect(DISTINCT c.name) AS domains" in query:
            return [{"product": "Data Cloud", "domains": ["Finance"]}]
        return []

    monkeypatch.setattr(gc, "_run_cypher", _fake_run_cypher)

    zh_payload = gc.entity_suggestions_controller("Transwarp", lang="zh")
    en_payload = gc.entity_suggestions_controller("Transwarp", lang="en")
    ko_payload = gc.entity_suggestions_controller("Transwarp", lang="ko")

    assert detect_lang(" ".join(zh_payload["questions"])) == "zh"
    assert detect_lang(" ".join(en_payload["questions"])) == "en"
    assert detect_lang(" ".join(ko_payload["questions"])) == "ko"
    assert len(fake_cache.store) == 3
    assert any("|zh|" in key for key in fake_cache.store)
    assert any("|en|" in key for key in fake_cache.store)
    assert any("|ko|" in key for key in fake_cache.store)


def test_entity_suggestions_rewrites_mismatched_language(monkeypatch):
    fake_cache = _FakeCache()
    responses = iter(
        [
            "埃奇恩艾尔系统有哪些核心产品？\n埃奇恩艾尔系统在哪些行业落地？",
            "에이치엔엘시스템의 핵심 제품은 무엇인가요?\n에이치엔엘시스템은 어떤 산업에 적용되나요?",
        ]
    )

    monkeypatch.setattr(gc, "_graph_cache", fake_cache)
    monkeypatch.setattr(gc, "_resolve_entity_node_name", lambda entity: "Transwarp")
    monkeypatch.setattr(gc, "_resolve_canonical_entity", lambda entity: "Transwarp")
    monkeypatch.setattr(
        gc,
        "graph_engine",
        SimpleNamespace(llm=SimpleNamespace(complete=lambda prompt: next(responses))),
    )

    def _fake_run_cypher(query, params=None):
        if "RETURN type(r) AS rel, b.name AS name" in query:
            return [{"rel": "PROVIDES", "name": "Vision Suite"}]
        if "RETURN b.name AS product, collect(DISTINCT c.name) AS domains" in query:
            return [{"product": "Vision Suite", "domains": ["Manufacturing"]}]
        return []

    monkeypatch.setattr(gc, "_run_cypher", _fake_run_cypher)

    payload = gc.entity_suggestions_controller("Transwarp", lang="ko")

    assert detect_lang(" ".join(payload["questions"])) == "ko"
    assert len(payload["questions"]) >= 2


def test_entity_suggestions_ignores_mismatched_cached_questions(monkeypatch):
    fake_cache = _FakeCache()
    fake_cache.set(
        "graph:suggestions:transwarp|ko|v1",
        {
            "entity": "Transwarp",
            "canonical": "Transwarp",
            "resolved": "Transwarp",
            "relations": [],
            "questions": ["这是一条错误缓存的中文问题？"],
        },
    )

    monkeypatch.setattr(gc, "_graph_cache", fake_cache)
    monkeypatch.setattr(gc, "_resolve_entity_node_name", lambda entity: "Transwarp")
    monkeypatch.setattr(gc, "_resolve_canonical_entity", lambda entity: "Transwarp")
    monkeypatch.setattr(
        gc,
        "graph_engine",
        SimpleNamespace(llm=SimpleNamespace(complete=lambda prompt: "")),
    )

    def _fake_run_cypher(query, params=None):
        if "RETURN type(r) AS rel, b.name AS name" in query:
            return [{"rel": "PROVIDES", "name": "Vision Suite"}]
        if "RETURN b.name AS product, collect(DISTINCT c.name) AS domains" in query:
            return [{"product": "Vision Suite", "domains": ["Manufacturing"]}]
        return []

    monkeypatch.setattr(gc, "_run_cypher", _fake_run_cypher)

    payload = gc.entity_suggestions_controller("Transwarp", lang="ko")

    assert payload["questions"] != ["这是一条错误缓存的中文问题？"]
    assert detect_lang(" ".join(payload["questions"])) == "ko"


def test_query_controller_prefers_input_language(monkeypatch):
    captured = {}

    class _FakePipeline:
        def __init__(self, lang="zh"):
            captured["lang"] = lang

        def run(self, query, mode="hybrid"):
            return {"answer": "ok", "sources": [], "graph_context": []}

    monkeypatch.setattr(qc, "QueryPipeline", _FakePipeline)

    result = qc.query_knowledge(QueryRequest(query="What is Transwarp?", mode="hybrid"), ui_lang="zh")

    assert captured["lang"] == "en"
    assert result["lang_ui"] == "zh"
    assert result["lang_detected"] == "en"
    assert result["lang_final"] == "en"
    assert result["suggest_switch"] is True
