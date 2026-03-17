## 查询流水线（GraphRAG v2）

本篇文档说明 `QueryPipeline` 的设计与工作流程，即平台如何将用户问题转化为**图检索 + 向量检索 + LLM 生成**的组合查询。

---

## 1. 模块位置

- 文件：`pipelines/query_pipeline.py`
- 核心类：`QueryPipeline`
- 依赖：
  - `api.deps.graph_engine`（`GraphEngine` 实例）
  - `api.deps.vector_engine`（`VectorEngine` 实例）

Controllers 层只需调用：

```python
pipeline = QueryPipeline()
result = pipeline.run(query_text, mode=request.mode)
```

---

## 2. 高层流程（文本图）

```text
用户 Query
   │
   ▼
QueryPipeline.run(query, mode)
   │
   ├─ detect_query_intent(query)  → 意图：greeting / fact_lookup / relationship_query / document_search
   ├─ choose_strategy(intent, mode) → strategy: vector_only / graph_only / hybrid
   │
   ├─ 若 intent = greeting:
   │      └─ 直接用 GraphEngine.llm.complete 生成简短问候回答
   │
   ├─ 若 strategy 包含 vector:
   │      └─ vector_resp = vector_retrieval(query)
   │            （VectorEngine.get_query_engine().query）
   │
   ├─ 若 strategy 包含 graph:
   │      └─ graph_resp = graph_retrieval(query)
   │            （GraphEngine.get_query_engine().query）
   │
   ├─ ranked = rerank(vector_resp, graph_resp)
   ├─ context = compress_context(ranked)
   └─ answer = llm_synthesis(query, context)
          └─ 返回统一结构：{ answer, sources, graph_context }
```

---

## 3. 意图识别：`detect_query_intent(query)`

```python
def detect_query_intent(self, query: str) -> str:
    q = query.strip().lower()
    if not q:
        return "greeting"

    greetings = ["hi", "hello", "hey", "早上好", "下午好", "晚上好", "你好", "您好", "在吗"]
    if any(tok in q for tok in greetings):
        return "greeting"

    rel_keywords = ["关系", "related to", "relationship", "关联", "how are", "connection between"]
    if any(k in q for k in rel_keywords):
        return "relationship_query"

    doc_keywords = ["哪篇文档", "which document", "which file", "文档中", "文件中"]
    if any(k in q for k in doc_keywords):
        return "document_search"

    return "fact_lookup"
```

- `greeting`：问候语或空字符串。
- `relationship_query`：包含“关系 / relationship / connection between”等词。
- `document_search`：询问**哪篇文档 / 哪个文件**包含某信息。
- `fact_lookup`：默认类型，用于一般事实问答。

---

## 4. 检索策略选择：`choose_strategy(intent, mode)`

```python
def choose_strategy(self, intent: str, mode: str | None = None) -> str:
    """
    选择检索策略：
      - 若用户显式指定 vector/graph，则严格遵守；
      - 若用户指定 hybrid 或未指定，则根据意图自动选择，优先走「快路径」：
          * greeting            -> graph_only（简单问候，用主模型快速回一句）
          * relationship_query  -> graph_only（确实需要图）
          * document_search     -> vector_only（只查哪篇文档，向量足够）
          * fact_lookup         -> vector_only（默认事实问答优先走向量）
    """
    # 显式模式优先（vector / graph）
    if mode in ("vector", "graph"):
        return {
            "vector": "vector_only",
            "graph": "graph_only",
        }[mode]

    # hybrid 或 None 视为自动模式，根据意图选择
    if intent == "greeting":
        return "graph_only"
    if intent == "relationship_query":
        return "graph_only"
    if intent in ("document_search", "fact_lookup"):
        return "vector_only"

    # 兜底：未知意图仍走向量优先
    return "vector_only"
```

### 三种检索模式（后端策略）

- **`vector_only`**：
  - 仅调用向量检索（`VectorEngine`）。
  - 适合文档搜索 / 语义查找场景。

- **`graph_only`**：
  - 仅调用图查询（`GraphEngine`）。
  - 适合实体关系分析、路径/关系查询、图解释等。

- **`hybrid`**：
  - 同时调用图检索与向量检索。
  - 当前实现中由 `rerank` 和 `llm_synthesis` 决定答案优先级（图优先，向量为后备）。

---

### 前端查询模式与后端 `mode` 对应关系

在知识库 UI 中，用户可以在输入框上方选择「查询模式」，其与后端 `mode` 字段的对应关系如下：

- **快速模式（向量优先）**：
  - 前端：`queryMode = "vector"`
  - 请求体：`{ "query": "...", "mode": "vector" }`
  - 后端：`choose_strategy` 固定走 `vector_only`。
  - 适合：大多数**普通问答 / 事实查找 / 内容检索**场景，响应速度最快。

- **智能模式（自动选择）**：
  - 前端：`queryMode = "hybrid"`
  - 请求体：`{ "query": "...", "mode": "hybrid" }`
  - 后端：视作“自动模式”，根据 `detect_query_intent` 的结果选择：
    - `greeting` / `relationship_query` → `graph_only`
    - `document_search` / `fact_lookup` → `vector_only`
  - 适合：不想手动选模式，交给系统根据意图决定「快路径 or 图路径」。

- **图模式（关系更强）**：
  - 前端：`queryMode = "graph"`
  - 请求体：`{ "query": "...", "mode": "graph" }`
  - 后端：`choose_strategy` 固定走 `graph_only`。
  - 适合：**实体关系分析、谁和谁有关系、图谱解释**等显式需要图结构的场景。

> 注意：若前端不传 `mode` 字段，后端等价于收到 `mode=None`，会走「自动模式」，但仍根据意图**优先选择向量检索**，以保证默认体验较快。

---

## 5. 检索层：`vector_retrieval` / `graph_retrieval`

```python
def vector_retrieval(self, query: str):
    qe = self.vector_engine.get_query_engine()
    return qe.query(query)

def graph_retrieval(self, query: str):
    qe = self.graph_engine.get_query_engine()
    return qe.query(query)
```

- 两者都是对 LlamaIndex 查询引擎的简单封装。
- 返回对象通常带有：
  - `response`（可打印为字符串）。
  - `source_nodes`（用于构造答案来源）。

---

## 6. 重排与上下文合并

### 6.1 `combine_context(vector_docs, graph_nodes)`

```python
def combine_context(self, vector_docs: Any, graph_nodes: Any) -> Dict[str, Any]:
    return {
        "vector": getattr(vector_docs, "source_nodes", []) if vector_docs is not None else [],
        "graph": getattr(graph_nodes, "source_nodes", []) if graph_nodes is not None else [],
    }
```

- 从两个检索结果中提取 `source_nodes`，分别放入 `vector` 和 `graph`。

### 6.2 `rerank(vector_docs, graph_nodes)`

```python
def rerank(self, vector_docs: Any, graph_nodes: Any) -> Dict[str, Any]:
    """
    目前简单地把图与向量的 source_nodes 合并。
    后续可以在这里加入基于得分或多路召回的重排逻辑。
    """
    context = self.combine_context(vector_docs, graph_nodes)
    context["vector_response"] = vector_docs
    context["graph_response"] = graph_nodes
    return context
```

- 当前实现并未做复杂排序，仅合并：
  - `vector` / `graph` 两路上下文。
  - 保留原始 response 对象供后续使用。
- 将来可以在这里实现：
  - 基于相似度分数的排序。
  - 多路召回 + 统一得分重排。

### 6.3 `compress_context(results)`

```python
def compress_context(self, results: Dict[str, Any]) -> Dict[str, Any]:
    """
    对上下文做轻量压缩：目前只做截断，保留前若干条，以防上下文过长。
    """
    max_per_channel = 5
    vector_nodes = results.get("vector", []) or []
    graph_nodes = results.get("graph", []) or []
    results["vector"] = vector_nodes[:max_per_channel]
    results["graph"] = graph_nodes[:max_per_channel]
    return results
```

- 限制每路最多保留 5 条上下文，避免 prompt 过长。
- 在使用大型模型时，可以进一步下调或增加更智能的压缩策略（例如基于摘要的压缩）。

---

## 7. 答案生成：`llm_synthesis`

```python
def llm_synthesis(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
    # 默认优先使用图谱答案，不足时回退向量答案
    graph_resp = context.get("graph_response")
    vector_resp = context.get("vector_response")

    if graph_resp is not None and str(graph_resp).strip():
        answer = str(graph_resp)
        source_nodes = context.get("graph", [])
    elif vector_resp is not None:
        answer = str(vector_resp)
        source_nodes = context.get("vector", [])
    else:
        answer = ""
        source_nodes = []

    return {
        "answer": answer,
        "sources": [
            {"text": node.text[:500], "file": node.metadata.get("file_name", "Unknown")}
            for node in (source_nodes or [])
        ],
        "graph_context": [],
    }
```

策略：

1. 若图检索有非空回答 → 直接使用图的回答。
2. 否则若向量检索有回答 → 使用向量结果。
3. 否则返回空字符串。

`sources` 字段使用截断后的 `node.text` 与 `file_name` 构造，可直接在前端展示为「引用片段」。

> 当前实现中，最终回答本身依赖 LlamaIndex 返回的字符串（其内部已经调用 LLM 完成综合），**QueryPipeline 并未再次调用额外的 LLM 进行后处理**。如需二次综合，可在此处追加一个统一的 synthesis LLM 调用。

---

## 8. Orchestration：`run(query, mode)`

```python
def run(self, query: str, mode: str = "hybrid") -> Dict[str, Any]:
    """
    GraphRAG v2 查询编排流程：
      1. 意图识别
      2. 选择检索策略
      3. 多路检索
      4. 重排与上下文压缩
      5. LLM 生成最终答案
    """
    _ensure_event_loop()

    logger.info("QueryPipeline running with mode=%s, query=%s", mode, query)

    intent = self.detect_query_intent(query)
    strategy = self.choose_strategy(intent, mode)
    logger.info("Detected intent=%s, strategy=%s", intent, strategy)

    # 纯问候意图可在上层处理，这里仍保留兜底路径
    if intent == "greeting":
        resp = self.graph_engine.llm.complete(
            f"用户向你打招呼说：'{query}'。请作为一个专业的知识库助手礼貌且简短地回复。"
        )
        return {"answer": str(resp), "sources": [], "graph_context": []}

    vector_resp = None
    graph_resp = None

    if strategy in ("vector_only", "hybrid"):
        vector_resp = self.vector_retrieval(query)

    if strategy in ("graph_only", "hybrid"):
        try:
            graph_resp = self.graph_retrieval(query)
        except Exception as e:  # noqa: BLE001
            logger.error("Graph retrieval failed: %s", e)
            if strategy == "graph_only":
                raise

    ranked = self.rerank(vector_resp, graph_resp)
    context = self.compress_context(ranked)
    return self.llm_synthesis(query, context)
```

要点：

- 使用 `_ensure_event_loop()` 确保在 pytest / 异步环境下不会因 event loop 关闭导致错误。
- 允许通过 `mode` 强制使用某种检索策略。
- 将错误日志记录在 pipeline 层，但将异常抛给上层，由 API 路由转换为 HTTP 错误。

---

## 9. 与 Controller 的分工

- **Controller（`query_controller.py`）**：
  - 校验与预处理请求。
  - 处理「问候语快速路径」。
  - 调用 `QueryPipeline.run` 得到标准结构的 dict。
  - 将异常转为 HTTP 层可理解的错误。

- **QueryPipeline**：
  - 全权负责**检索、重排、上下文压缩与最终答案生成策略**。
  - 面向 GraphEngine / VectorEngine 抽象接口，而不暴露 LlamaIndex 细节给上层。

这种分层容易在未来扩展：

- 增加新的意图类型（如 `multi_hop_reasoning`）。
- 引入 BM25 / 关键字检索作为额外检索通道。
- 替换或增强重排策略，而不影响 API 与控制器代码。

---

## 10. 流式查询：`run_stream(query, mode)`

对外入口：`POST /query/stream`，返回 NDJSON 流。

- **事件类型**：
  - `{"type": "chunk", "text": "..."}`：每收到 LLM 一段正文即推送，仅包含最终回答文本（thinking 已在后端过滤）。
  - `{"type": "done", "answer", "sources", "pipeline_latency_ms", "first_token_ms", "total_ms"}`：结束事件，包含完整答案、来源及延迟指标。

- **延迟指标**（`pipeline_latency_ms`）：
  - `planner_ms`、`vector_retrieval_ms`、`graph_retrieval_ms`、`traversal_ms`、`llm_generation_ms`、`total_ms`、`first_token_ms`；
  - `prompt_chars`、`prompt_tokens`（约 `chars//2`），用于排查 prefill 与首字延迟。

- **上下文与 Prompt 限制**（与延迟优化一致）：
  - **ContextBuilder**：`MAX_CONTEXT_CHUNKS=3`、`MAX_CHARS_PER_CHUNK=150`、`MAX_TOTAL_CHARS=800`，单句截断。
  - **PromptBuilder**：极简系统提示（Answer directly. No reasoning. Max 2 sentences.），结尾为「Answer:」。
  - Ollama 主模型：`num_ctx`、`num_predict`（如 64）、`temperature=0`、`thinking=False`，由 `core/graph_engine.py` 与 `core/vector_store.py` 在初始化时传入。

