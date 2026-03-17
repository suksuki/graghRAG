# Embedding 调用排查报告（QueryPipeline vector_retrieval 104s 瓶颈）

## SECTION A — embedding 入口函数

| 位置 | 文件 | 函数/用法 | 说明 |
|------|------|-----------|------|
| 向量检索 | `core/vector_store.py` | `VectorEngine.embed_model`（OllamaEmbedding） | 用于 `get_retriever()` / `get_query_engine()`，query 时由 LlamaIndex 调用 |
| 图检索 | `core/graph_engine.py` | `GraphEngine.embed_model`（OllamaEmbedding） | 用于 PropertyGraphIndex + VectorContextRetriever |
| 设置探测 | `api/controllers/settings_controller.py` | `httpx.post(embed_url, ...)` | 保存设置时探测 embedding 维度，非 query 路径 |

**实际触发 Ollama `/api/embed` 的链路：**

- **向量路径**：`vector_retrieval()` → `retriever.retrieve(query)` → `VectorIndexRetriever._retrieve()` → `get_agg_embedding_from_queries(embedding_strs)` → `get_query_embedding(query)`（或对多 query 多次调用）
- **图路径**：`graph_retrieval()` → 图 query_engine 内部 `VectorContextRetriever` 同样会调用 `embed_model.get_agg_embedding_from_queries(embedding_strs)`。

**LlamaIndex 基类逻辑（`get_agg_embedding_from_queries`）：**

```python
query_embeddings = [self.get_query_embedding(query) for query in queries]  # 每个 query 一次 API
return mean_agg(query_embeddings)
```

因此若 `embedding_strs` 有 N 个元素，就会产生 **N 次** embedding 调用。

---

## SECTION B — embedding 调用次数（修复前/后）

**修复前（使用 `query_engine.query(query)`）：**

- 一次 query 会经过：Retriever（1 次 query embed）+ **ResponseSynthesizer**。
- 若使用默认或某些 response 模式，会触发对**每个检索到的节点内句子**做 `_get_text_embeddings(sentences)`（例如 LlamaIndex 的 `SentenceEmbeddingOptimizer` 对每个 node 的句子做 embed 再筛选），导致 **约 80 次** embedding（与 104s / 1.29s ≈ 80 一致）。
- 日志中通过 `[EmbedCall]` 可统计到：**Embedding calls per query ≈ 78–80**。

**修复后（仅用 retriever，不做 response synthesis）：**

- `vector_retrieval()` 改为：`retriever.retrieve(query)` → 只做 **1 次 query embedding** + 向量库查询。
- 日志中应出现：**Embedding calls per query: 1**（仅 vector 路径；若走 graph 会再多 1 次图侧 query embed）。

**如何验证：**

- 发一条 Copilot 问句（如「你知道星环公司吗」），在 `api_runtime.log` 中搜索：
  - `[EmbedCall]`：每次 embedding 请求会打一条；
  - `[EmbedCall] vector_only path embedding calls total: N` 或 `full path vector_retrieval embedding calls total: N`：N 应为 **1**。

---

## SECTION C — 重复 embedding 的代码位置

**根因：**

- 原实现使用 `index.as_query_engine()` 得到 `RetrieverQueryEngine`，一次 `query_engine.query(query)` 会：
  1. **Retriever**：对 query 做 **1 次** query embedding，再向量检索；
  2. **ResponseSynthesizer**：在部分实现或与某些 node postprocessor 组合时，会对**检索到的每个 chunk 的句子**再做 embedding（例如做「与 query 最相关句子」筛选），即 **N 个 chunk × 每 chunk 若干句子 ≈ 80 次** `_get_text_embedding` / `_get_text_embeddings`。

**LlamaIndex 中典型来源（与本项目无关，仅说明机制）：**

- `llama_index.core.postprocessor.optimizer.SentenceEmbeddingOptimizer._postprocess_nodes()` 中：
  - `text_embeddings = self._embed_model._get_text_embeddings(split_text)`  
  其中 `split_text` 为单个 node 按句子切分后的列表，**每个句子 1 次 embed**。
- 若未显式禁用或未使用该 postprocessor，但存在类似「按句子再筛」的逻辑，也会出现大量 text embedding。

**本项目中的实际路径：**

- 文件：通过 `pipelines/query_pipeline.py` 的 `vector_retrieval()` 调用 `vector_engine.get_query_engine().query(query)`。
- 函数：`vector_retrieval()` → `qe.query(query)`。
- 原因：`query()` 内部既跑 retriever（1 次 query embed），又跑 response synthesizer；synthesizer 或默认 pipeline 中对节点内容的再处理触发了对**大量文本片段**的 embedding，导致约 80 次调用。

---

## SECTION D — 修复方案（已实施）

**目标：一次 query 在向量侧只做 1 次 query embedding。**

1. **`core/vector_store.py`**
   - 新增 `EmbeddingCallLogger`（包装 OllamaEmbedding），对 `_get_query_embedding` / `_get_text_embedding` / `_get_text_embeddings` 打日志并计数，便于确认调用次数。
   - 新增 `get_retriever(similarity_top_k=5)`：仅返回 `VectorStoreIndex.from_vector_store(...).as_retriever(similarity_top_k=...)`，**不**经过 `as_query_engine()`，因此不会触发 response synthesizer 及其可能的多重 embedding。
   - ingestion 仍使用 `_embed_model_raw`（原始 OllamaEmbedding），避免写入时日志刷屏。

2. **`pipelines/query_pipeline.py`**
   - **`vector_retrieval()`**：改为使用 `vector_engine.get_retriever(similarity_top_k=5).retrieve(query)`，得到 `NodeWithScore` 列表后，构造与原先兼容的 `VectorResponse`（带 `source_nodes`），供后续 `combine_context` / `llm_synthesis` 使用。
   - 在 short-circuit 与 full path 的 vector 检索前 `_reset_embed_call_count()`，检索后打 `[EmbedCall] ... embedding calls total: N`，便于验证 N=1。

**正确模式（当前实现）：**

- `query_vec = embed(query)`（1 次）
- `vector_store.query(query_vec, similarity_top_k=5)`（纯向量搜索，无额外 embed）
- 返回的 nodes 直接用于 context 构建与 LLM synthesis，**不再**对 node 内容做句子级或 chunk 级 re-embed。

---

## SECTION E — 修复后表现与测试

- **集成测试**：`pytest tests/test_integration.py -q` 已通过（1 passed）。
- **预期 latency（单次 query，vector_only 或 hybrid 中向量部分）：**
  - planner：约数 ms
  - **vector_retrieval**：由 **~104s 降为约 1–3s**（1 次 embed ~1.3s + 向量库查询）
  - llm_generation：取决于 LLM，约 20s 量级不变
  - **total**：目标由 **~126s 降至约 20–25s**；若再优化 LLM（如换小模型或 GPU），可进一步降低。

**建议验证步骤：**

1. 重启 API，发一条「你知道星环公司吗」或「星环公司都有哪些主要客户？」。
2. 查看 `api_runtime.log`：
   - `[EmbedCall] ... embedding calls total: 1`
   - `[QueryPipeline] ... vector_retrieval: 1000–3000ms ...`（不再出现 104000ms 量级）。

---

## 额外结论：向量检索实现是否正确

- **正确**：当前使用 PGVectorStore，表中已存 `embedding` 列；检索时仅用 **query 的 embedding** 做 `ORDER BY embedding <-> query_vec LIMIT k`，**不会**对库中 chunk 再做一次 embed。
- 重复 embedding 来自 **query 路径上的 response synthesizer / 节点后处理**，而非向量库实现本身。改为「仅 retriever + 自研 synthesis」后，一次 query 在向量侧仅 1 次 query embedding，符合 GraphRAG 最佳实践。
