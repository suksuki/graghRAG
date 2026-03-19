## GraphRAG 平台架构总览

GraphRAG 平台围绕「**文档 → 知识图谱 + 向量库 → LLM 问答**」这一主线构建，整体可以分为以下层次：

- **API 层（FastAPI）**：`api/main.py` + `api/routes/*`
- **控制器层（Controllers）**：`api/controllers/*`
- **查询编排层（QueryPipeline）**：`pipelines/query_pipeline.py`（含流式 `run_stream()`，首字与延迟指标回传）
- **摄取管道（Ingestion Pipeline）**：`core/ingestion.py`
- **图引擎（GraphEngine / Neo4j）**：`core/graph_engine.py`
- **向量引擎（VectorEngine / pgvector）**：`core/vector_store.py`
- **LLM 能力（Ollama）**：LLM + Embedding + 抽取模型
- **异步任务（Celery + Redis）**：`workers/celery_worker.py` + `api/controllers/ingestion_controller.py`

---

## 架构关系（文本版架构图）

```text
                 ┌─────────────────────────────┐
                 │         前端（React）       │
                 │  - 上传文档 / 配置模型      │
                 │  - 查看图谱 / 进度 / 问答   │
                 └──────────────┬──────────────┘
                                │ HTTP (JSON)
                                ▼
                     ┌─────────────────────┐
                     │     FastAPI API    │  api/main.py
                     │  - /upload         │
                     │  - /documents      │
                     │  - /graph/data     │
                     │  - /ingestion/...  │
                     │  - /query          │
                     │  - /settings/...   │
                     └────────┬────────────┘
                              │ 调用 Controllers
                              ▼
               ┌───────────────────────────────────┐
               │          Controllers              │
               │  api/controllers/*.py             │
               │                                   │
               │  - ingestion_controller:          │
               │      * 处理上传/文档/进度/删除    │
               │      * 调用 Celery 任务或 Ingestor│
               │  - query_controller:              │
               │      * 处理 QueryRequest          │
               │      * 调用 QueryPipeline.run()   │
               │  - settings_controller:           │
               │      * 读写 .env / 测试连接       │
               └──────────────┬────────────────────┘
                              │
                              ▼
                 ┌────────────────────────────┐
                 │      QueryPipeline         │  pipelines/query_pipeline.py
                 │  - detect_query_intent     │
                 │  - choose_strategy         │
                 │  - vector_retrieval        │
                 │  - graph_retrieval         │
                 │  - rerank / compress_ctx   │
                 │  - llm_synthesis           │
                 └───────┬─────────┬──────────┘
                         │         │
          使用 pgvector   │         │  使用 Neo4j + 抽取 LLM
                         │         │
        ┌────────────────▼─┐   ┌───▼──────────────────┐
        │   VectorEngine   │   │     GraphEngine      │
        │ core/vector_...  │   │ core/graph_engine.py │
        │  - PostgreSQL    │   │  - Neo4j             │
        │  - pgvector      │   │  - PropertyGraphIndex│
        └────────┬─────────┘   └────────┬─────────────┘
                 │                      │
                 ▼                      ▼
        ┌─────────────────┐    ┌─────────────────────┐
        │ 向量表 data_*   │    │ Neo4j 图节点 / 关系 │
        └─────────────────┘    └─────────────────────┘


                 ┌────────────────────────────┐
                 │       Ingestion Pipeline   │  core/ingestion.py
                 │  - SMEIngestor.ingest_data │
                 │  - SentenceSplitter        │
                 │  - 写入 VectorEngine +     │
                 │    GraphEngine             │
                 └───────────┬────────────────┘
                             │
                             ▼
                ┌─────────────────────────────┐
                │ Celery Worker (Ollama/DB)  │ workers/celery_worker.py
                │  - ingest_document_task    │
                │  - 使用 SMEIngestor        │
                └───────────┬────────────────┘
                            │
                            ▼
                      ┌─────────────┐
                      │ Redis 队列  │
                      │ ingestion:* │
                      └─────────────┘
```

---

## FastAPI API 层

- 入口：`api/main.py`
- 职责：
  - 初始化 `FastAPI` 应用与 CORS 中间件。
  - 挂载路由模块：`api.routes.query_routes`、`api.routes.ingestion_routes`、`api.routes.settings_routes`。
  - 通过 `api.deps` 暴露长生命周期的 `graph_engine`、`vector_engine`、`ingestor` 供测试与控制器使用。

API 层本身**不包含业务逻辑**，只负责路由注册与基础健康检查（`GET /`）。

---

## Controllers（业务控制层）

位置：`api/controllers/*.py`

- `query_controller.py`
  - 核心函数：`query_knowledge(request: QueryRequest) -> Dict[str, Any]`
  - 功能：
    - 处理问候语快速路径（调用 `QueryPipeline().graph_engine.llm.complete` 生成简单回答）。
    - 对普通查询，构造 `QueryPipeline` 并调用 `run(query, mode)`。
    - 将异常转化为统一的错误响应结构（由路由包装成 HTTPException）。

- `ingestion_controller.py`
  - 封装文件上传、文档列表、图数据获取、摄取状态查询、文档删除等逻辑。
  - 使用 `sanitize_filename / resolve_path_under` 做安全校验。
  - 将上传的文件写入 `settings.DATA_RAW_DIR`，然后：
    - 向 Redis 写入状态 `ingestion:{filename} = queued`。
    - 通过 `ingest_document_task.delay(file_path)` 投递 Celery 任务。
  - 保留 `INGESTION_STATE` 以支持进度轮询（对前端进度条友好）。

- `settings_controller.py`
  - 提供系统配置读取与更新：
    - 读取当前 LLM / Embedding / 抽取模型配置。
    - 调用 Ollama / Neo4j 做连通性测试。
    - 更新 `.env` 并重新构建 `GraphEngine` / `VectorEngine` / `SMEIngestor`。

> 控制器层遵循 MVC 中「C」的含义：**不关心 HTTP 细节，只处理业务决策与调度。**

---

## QueryPipeline（查询编排）

位置：`pipelines/query_pipeline.py`

核心职责：**统一封装 GraphRAG v2 查询流程**：

- 查询理解：
  - `detect_query_intent(query)`：识别 `greeting` / `fact_lookup` / `relationship_query` / `document_search`。
  - `choose_strategy(intent, mode)`：在 `vector_only` / `graph_only` / `hybrid` 之间选择。

- 检索层：
  - `vector_retrieval(query)`：使用 `VectorEngine.get_query_engine().query(query)`。
  - `graph_retrieval(query)`：使用 `GraphEngine.get_query_engine().query(query)`。

- 排序与压缩：
  - `combine_context(vector_docs, graph_nodes)`：合并两路 `source_nodes`。
  - `rerank(...)`：当前实现为简单合并，未来可扩展为打分 / 多路召回重排。
  - `compress_context(results)`：每路保留前 5 条上下文，控制 prompt 长度。

- LLM 生成：
  - `llm_synthesis(query, context)`：优先使用图检索答案，缺失时回退到向量检索结果，并组装统一响应结构。

`run(query, mode)` 是对外唯一入口：

1. `_ensure_event_loop()`：保证当前线程有可用的 asyncio loop。
2. `intent = detect_query_intent(query)`
3. `strategy = choose_strategy(intent, mode)`
4. 对 `greeting` 直接用 `graph_engine.llm` 生成简短问候回答。
5. 按策略调用 `vector_retrieval` / `graph_retrieval`。
6. `ranked = rerank(vector_resp, graph_resp)`
7. `context = compress_context(ranked)`
8. `return llm_synthesis(query, context)`

这样，**控制器只关心调用 `pipeline.run()`，而不直接操作 LlamaIndex。**

---

## Ingestion Pipeline（摄取管道）

位置：`core/ingestion.py`，类 `SMEIngestor`。

流程：

1. 从 `settings.DATA_RAW_DIR` 扫描待处理文件。
2. 查询：
   - `GraphEngine.get_indexed_files()`：Neo4j 已索引文件。
   - `_get_vector_indexed_files(VectorEngine)`：pgvector 中已存在的文件名。
3. 只针对**新文件**构建待处理列表。
4. 使用 `SimpleDirectoryReader` 读取这些文件。
5. 使用 `SentenceSplitter` 按 `CHUNK_SIZE` / `CHUNK_OVERLAP` 分块得到 `nodes`。
6. 新文件的节点写入 `VectorEngine.add_documents(nodes)`。
7. 新文件的节点按批调用 `GraphEngine.create_index(nodes_batch)` 写入 Neo4j，并在每批结束后更新进度。

摄取管道是**同步逻辑**，但在实际 API 中通常由 Celery 任务驱动（后台运行）。

---

## GraphEngine（Neo4j）

位置：`core/graph_engine.py`

- 使用 `Neo4jPropertyGraphStore` 与 Neo4j 通信。
- 使用两个 LLM：
  - `llm`：主对话/查询模型（`LLM_MODEL`），初始化时传入 `context_window`、`num_ctx`、`keep_alive`、`thinking=False`、`num_predict`、`temperature` 以控制延迟与输出。
  - `extraction_llm`：实体关系抽取模型（`EXTRACTION_MODEL`），体积更小、速度更快。
- 支持：
  - 增量索引（根据 `file_name` 跳过已处理文件）。
  - `create_index(nodes, num_workers, max_paths_per_chunk)`：对每个文本块调用 LLM 提取路径，写入 Neo4j。
  - `delete_document(filename)`：删除对应文件的所有图节点。
  - `get_query_engine()`：构造 `PropertyGraphIndex` 并附加 `VectorContextRetriever`，用于图 + 局部向量混合检索。

---

## VectorEngine（PostgreSQL + pgvector）

位置：`core/vector_store.py`

- 使用 `PGVectorStore` 存储嵌入：
  - 每个 Embedding 模型对应独立表：`data_sme_vs_<model_suffix>`。
  - 插入时使用 `VectorStoreIndex` 构建索引。
- 特性：
  - 自动检测 / 校验向量维度，维度不匹配时可删除旧表并重建。
  - 通过 SQL 删除指定文件的所有向量。
  - `get_query_engine()`：返回基于当前表的向量检索引擎。

---

## Ollama LLM

平台统一通过 Ollama 提供：

- **主模型**（`LLM_MODEL`）：回答用户问题、用于图查询引擎；可由设置页或 `.env` 覆盖，默认 `qwen2.5:7b`。
- **抽取模型**（`EXTRACTION_MODEL`）：构建知识图谱时使用，通常为更小模型（如 `qwen2.5:7b`）。
- **Embedding 模型**（`EMBEDDING_MODEL`）：生成向量存储到 pgvector。

**延迟与稳定性相关配置（主模型）**：

- **context_window / num_ctx**：显式设置（如 `LLM_NUM_CTX=2048`），避免 LlamaIndex 调用 `client.show(model)` 触发冷加载，并控制 prefill 规模。
- **keep_alive**：`"30m"`，减少模型卸载后的冷启动。
- **thinking**：`False`，关闭 Qwen 等模型的“思考”输出，首字更快、无干扰。
- **num_predict / temperature**：限制生成长度（如 64 token）、确定性输出。

所有模型的请求地址由 `OLLAMA_BASE_URL` 配置；超时由 `REQUEST_TIMEOUT` / `EXTRACTION_TIMEOUT` 控制。详见 `docs/OPTIMIZATION_LLM_LATENCY.md`。

---

## Celery Worker 与 Redis 队列

位置：

- Worker 定义：`workers/celery_worker.py`
- 调用方：`api/controllers/ingestion_controller.py`

关键点：

- Celery 应用：

```python
celery_app = Celery(
    "ingestion_worker",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)
```

- 任务：`ingest_document_task(file_path)`
  - 从 `file_path` 获取文件名。
  - 使用 `SMEIngestor.ingest_data(directory_path=...)` 执行增量摄取。
  - 使用 Redis key `ingestion:{filename}` 记录状态：`queued` / `processing` / `done` / `failed`。

- `ingestion_controller.handle_upload` 在保存文件后：
  - `redis.set("ingestion:{filename}", "queued")`
  - 调用 `ingest_document_task.delay(file_path)` 投递任务。

通过 Celery + Redis，摄取可以在独立进程中运行，避免阻塞 API 请求，并支持多任务排队。

---

## 文档与变更

- **近期设计/配置变更**（LLM 延迟、流式、prompt、图谱概览等）：见 `docs/CHANGELOG.md`。
- **首字与 LLM 延迟优化**：见 `docs/OPTIMIZATION_LLM_LATENCY.md`。
- **当前运行时设计（Graph-first / Graph-dominant / Precompute / 受控抽取）**：见 `docs/DESIGN_GRAPHRAG_RUNTIME_2026Q1.md`。
