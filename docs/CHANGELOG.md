# 变更记录（Changelog）

本文档记录 GraphRAG 平台的重要设计变更与功能更新，便于架构与运维对齐。

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
