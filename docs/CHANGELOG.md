# 变更记录（Changelog）

本文档记录 GraphRAG 平台的重要设计变更与功能更新，便于架构与运维对齐。

---

## 2026-03（单路径契约收敛：Document Insight 响应统一）

### 目标

将文档中心与知识库 doc-scoped 问答对齐为同一能力契约，避免多入口返回结构分叉。

### 变更

- `POST /api/v1/insights/document` 响应增加 `answer` 字段（主字段）。
- 保留 `summary` 作为兼容字段，并与 `answer` 保持等价。
- `source` 语义收敛为 `rag` / `facts`，不再保留 `summary` / `selection` 作为问答来源语义。
- 前端 `useDocumentInsight` 统一消费 `answer`（兼容回填 `summary`），确保多入口一致渲染。

### 测试与文档

- 更新 `tests/test_api.py`：新增 `answer` 存在与 `answer == summary` 断言，并校验 `source` 枚举。
- 更新 `docs/API_REFERENCE.md`、`docs/TESTING.md`、`docs/ARCHITECTURE.md`、`docs/ARCHITECTURE_AGENTIC_RETRIEVAL.md` 契约描述。

---

## 2026-03（文档智能产品层：知识库路径 + Hybrid + Grounded Insight）

### 目标

在 **DI-first** 边界下补齐可对外演示的产品 API：**知识库（文档中心）**、**融合检索**、**单请求证据约束洞察**；并消除与 FastAPI 默认 Swagger（`GET /docs`）的路径冲突。

### 1. API 与 MVC

- **知识库**：`api/routes/knowledge_hub_routes.py`，统一前缀 **`/knowledge`**：
  - `GET /knowledge/docs`、`GET /knowledge/docs/{doc_id}`、`GET /knowledge/search`、`GET /knowledge/entity/{name}`。
  - 前端经 Vite 代理使用 **`/api/knowledge/...`**（`apps/src/hooks/*.js`）。
- **融合检索**：`POST /api/v1/hybrid-search`（`core/hybrid_search_service.py` + `hybrid_search_controller`）；Vector-first、图扩展为辅助。
- **单文档洞察**：`POST /api/v1/insights/document`（`core/document_insight_service.py` + `document_insight_controller`）；摘要仅基于 `supporting_chunks`，**无片段不调 LLM**；`ref_index` 与 `[n]` 引用对齐；`key_relations` 可带 **`kg_source` / `kg_confidence`**。
- **语料洞察**：`POST /insights/corpus`（`corpus_insight_controller`），聚合多文档 `di_*`。

### 2. 摄取与图治理（文档对齐）

- **`GRAPH_MAX_NODES`**、图批超时等与 `core/ingestion.py` 一致描述已写入 `docs/INGESTION_PIPELINE.md`（替换过时的「强上限 5 / 5s」表述）。
- 关系边 **`kg_*`** 与 `core/kg_edge_filter.py`、查询阈值见摄取小结 **§5.3**。

### 3. 文档

- 更新：`docs/ARCHITECTURE.md`（检索分层、控制器枚举、`/knowledge` 约定）、`docs/API_REFERENCE.md`（新增 §10 知识库；Hybrid/Insight 顺延节号）、`docs/TESTING.md`、`docs/DOCUMENT_INTELLIGENCE_POSITIONING.md`、`docs/PRODUCT_ROADMAP_P0.md`。

### 4. 测试

- `tests/test_api.py`：补充 **`/knowledge/docs`**、**`/knowledge/search`**；加强 **`/api/v1/insights/document`** 对 **`ref_index`** 的断言。
- 全量：`pytest` — **43 passed**（见 `docs/TESTING.md` §4.6）。

---

## 2026-03（Graph Runtime 定型 + 测试补齐）

### 目标

完成 Query 与 UI 的数据契约对齐，稳定 Graph-first/Graph-dominant/Precompute 行为，并将 ingestion 图抽取收敛为“受控轻量模式”。

### 1. Query 侧关键变更

- 新增 canonical entity 统一入口，Graph 查询不再直接用原始 query：
  - 输出 `entity_raw`、`entity_canonical`、`entity_used_for_graph` 调试字段。
- `run_stream` done 事件中的 `graph` 统一标准化：
  - 固定包含 `used/relations/count/two_hop/summary`。
- Graph-first + 质量门控稳定化：
  - `relations >= 3` 或 `summary` 存在才走 graph 直答，否则自动回退 vector。
- Precompute 机制完善：
  - 版本化 key：`graph:precompute:{entity}:{graph_version}`
  - `precompute_hit` debug 输出
  - 空命中保护与 24h TTL。

### 2. Ingestion 侧关键变更

- 图抽取改为“受控 LLM 轻量模式”：
  - `num_workers=1`、`max_paths_per_chunk=2`
  - `num_ctx=1024`、`num_predict=32`
  - `batch_size=1`、`max_graph_nodes<=5`
  - 单 batch 超时 5s 直接跳过（不阻塞整批）
- 新增高价值 chunk 筛选（评分 + 去重 + top-k），降低无效抽取调用。
- 保持增量图索引（`IngestedFile` marker）避免重复重建。
- 状态可观测性增强：
  - worker 全局状态 `updated_at`
  - 失败写 `failed`，不再误写 `idle`
  - stalled 检测由 API 状态接口兜底。

### 3. Frontend/UI 关键变更

- `hasGraphData` 判定改为多信号（`graph.* + debug.graph_relations_count`）。
- done 事件中先标准化 `graph` 后写入 `msg.graph`，避免结构漂移导致 UI误判。
- suggestions 实体提取增加 fallback：`debug.entity_used_for_graph`。
- 增加 `console.log("GRAPH UI DATA:", msg.graph)` 便于现场排障。

### 4. 文档与测试

- 新增设计文档：
  - `docs/DESIGN_GRAPHRAG_RUNTIME_2026Q1.md`
- 更新文档：
  - `docs/ARCHITECTURE.md`
  - `docs/QUERY_PIPELINE.md`
  - `docs/INGESTION_PIPELINE.md`
  - `docs/TESTING.md`
- 新增自动化回归用例：
  - `tests/test_query_pipeline_contract.py`
  - 覆盖 stream done 事件 graph/debug 契约与 canonical entity 链路。
- 全量自动化测试结果：
  - `19 passed`（unit + integration + regression）

---

## 2026-03（LLM 延迟与体验优化）

### 目标

在不更换 9B 模型的前提下，将问答首字延迟从数十秒降至 1–3 秒，总耗时降至 2–3 秒，并去除 thinking 干扰与重复输出感。

### 1. Ollama 推理参数与上下文配置

- **根因**：Ollama 默认 `num_ctx` 极大（如 262144），导致 prefill 与 KV 分配压力过高；且 LlamaIndex 在未显式设置 `context_window` 时会调用 `client.show(model)`，可能触发冷加载，造成首字数十秒延迟。
- **改动**：
  - 在 `GraphEngine` / `VectorEngine` 中创建 Ollama 客户端时**显式传入**：
    - `context_window`、`additional_kwargs.num_ctx`（来自 `LLM_NUM_CTX`，默认 2048）；
    - `keep_alive="30m"`，减少模型频繁卸载后的冷启动；
    - `thinking=False`，关闭 Qwen 等模型的“思考”输出，避免首字被 thinking 占用；
    - `additional_kwargs.num_predict`（来自 `LLM_NUM_PREDICT`，默认 64）、`temperature=0`，控制生成长度与稳定性。
  - 配置项：`configs/config.py` 新增 `LLM_NUM_CTX`（可选）、`LLM_NUM_PREDICT`（默认 64）；`LLM_MODEL` 默认改为 `qwen2.5:7b`（可由设置页或 `.env` 覆盖）。

### 2. Prompt 与上下文裁剪

- **PromptBuilder**（`pipelines/prompt_builder.py`）：
  - 系统提示改为极简：「You are a fast enterprise QA system. Answer directly. No reasoning. No explanation. Max 2 sentences.」
  - 结尾由「Answer (1-3 sentences):」改为「Answer:」，减少模型内部 planning。
- **ContextBuilder**（`pipelines/context_builder.py`）：
  - 已存在限制：`MAX_CONTEXT_CHUNKS=3`、`MAX_CHARS_PER_CHUNK=150`、`MAX_TOTAL_CHARS=800`，单句截断，控制喂给 LLM 的上下文体积。

### 3. 流式输出与 thinking 过滤

- **后端**：`run_stream()` 中仅在有有效正文（`delta`）时 `yield {"type": "chunk", "text": delta}`；对仅含 `thinking_delta` 的 chunk 做防御性跳过。
- **前端**：处理 `chunk` 时增加 `!event.thinking` 条件，不展示 thinking 内容。

### 4. 延迟指标与 Prompt 长度展示

- **后端**：流式 `done` 事件中 `pipeline_latency_ms` 增加 `prompt_chars`、`prompt_tokens`（约 `chars//2`），便于排查 prefill 与首字关系。
- **前端**：在每条助手消息下方的耗时区域增加一行：「Prompt: X 字符 · ~Y token」。

### 5. 文档与配置说明

- 新增 **`docs/OPTIMIZATION_LLM_LATENCY.md`**：首字/LLM 延迟优化指南（num_ctx、context_window、冷启动、GPU、模型选择）。
- 架构、API、部署、README 等文档已同步更新：默认模型、新增环境变量、流式响应结构、图谱概览与推荐问题数据来源说明。

### 验证标准（优化后）

- 首字时间 &lt; 1.5s（视硬件与模型可为 0.2–1s）。
- 总耗时约 2–3s（num_predict=64、极简 prompt）。
- 无 thinking 输出；回答控制在约 2 句内。

---

## 流式查询接口（历史）

- 查询默认走 **`POST /query/stream`**，返回 NDJSON 流：`{"type": "chunk", "text": "..."}` 与 `{"type": "done", "answer", "sources", "pipeline_latency_ms", "first_token_ms", "total_ms"}`。
- `pipeline_latency_ms` 包含：`planner_ms`、`vector_retrieval_ms`、`graph_retrieval_ms`、`traversal_ms`、`llm_generation_ms`、`total_ms`、`first_token_ms`、`prompt_chars`、`prompt_tokens`（详见 `docs/API_REFERENCE.md`）。

---

## 图谱概览与推荐问题（说明）

- **Graph Overview**、**Suggested questions** 数据来自 Neo4j：`GET /api/graph/overview`、`GET /api/graph/suggested_questions`。
- 若图谱尚未构建（未跑图摄取或 Neo4j 无节点/关系），两处会显示「暂无图谱统计数据」「暂时没有推荐问题」，属预期行为；完成文档摄取并执行图索引后即有数据。
