## API 接口参考（GraphRAG 平台）

> 说明：所有接口默认为 `application/json`，文件上传接口使用 `multipart/form-data`。

---

## 1. 上传文档 `POST /upload`

- **Purpose**：上传一个或多个文档到原始数据目录，并触发异步摄取任务（Celery）。
- **Content-Type**：`multipart/form-data`

### 请求

- 字段：`files`（可以重复多次）
  - 类型：`UploadFile`
  - 支持格式：`.pdf`、`.docx`、`.pptx`、`.xlsx`、`.txt`、`.jpg`、`.png`、`.jpeg`、`.xdmp`

示例（curl）：

```bash
curl -X POST http://localhost:8000/upload \
  -F "files=@/path/to/file1.pdf" \
  -F "files=@/path/to/file2.txt"
```

### 响应

```json
{
  "status": "queued",
  "filename": "example.pdf",
  "files": ["example.pdf"]
}
```

---

## 2. 文档列表 `GET /documents`

- **Purpose**：列出当前原始数据目录中的所有文档。

### 请求

- 无参数。

### 响应

```json
[
  {
    "name": "report.pdf",
    "size": 123456,
    "uploaded_at": "2025-03-12 10:20",
    "uploader": "user_or_system"
  }
]
```

---

## 3. 图数据 `GET /graph/data`

- **Purpose**：获取一小部分图谱数据用于前端可视化（采样 100 条关系）。

### 请求

- 无参数。

### 响应

```json
{
  "nodes": [
    { "id": "1", "label": "Entity", "name": "Project Antigravity" }
  ],
  "links": [
    { "source": "1", "target": "2", "label": "RELATED_TO" }
  ]
}
```

### 相关接口

- **`GET /graph/overview`**：图谱总览（节点数、关系数、按类型统计、代表实体）。若 Neo4j 尚无节点则返回空统计，前端显示「暂无图谱统计数据」。
- **`GET /graph/suggested_questions`**：基于图中关系生成的推荐问题列表（如 "How is A related to B?"）。若图中无关系则返回空列表，前端显示「暂时没有推荐问题」。

---

## 4. 摄取状态 `GET /ingestion/status`

- **Purpose**：查询当前摄取进度与图节点、文件数等概况。

### 请求

- 无参数。

### 响应

```json
{
  "status": "processing",
  "health": "processing",
  "message": "Graph indexing: 5/20 chunks (70%)",
  "progress": 70,
  "graph_done": 5,
  "graph_total": 20,
  "files_in_batch": 3,
  "file_names": ["a.pdf", "b.txt", "c.docx"],
  "updated_at": 1730000000,
  "node_count": 128,
  "file_count": 10,
  "eligible_file_count": 4,
  "vector_chunk_count": 120
}
```

- **`health`**：`ok` | `processing` | `stalled` | `failed`。`stalled` 表示任务仍为 processing 但 Redis 心跳超过约 60s 未更新；`failed` 含 API 失败、硬超时、或「磁盘有可摄取文件但向量表行数为 0」（向量统计不可用时跳过后者）。
- **`eligible_file_count`**：扩展名在白名单内的磁盘文件数（与知识库列表一致）。
- **`vector_chunk_count`**：当前 PGVector 表行数；查询失败时为 `null`。

---

## 5. 删除文档 `DELETE /documents/{filename}`

- **Purpose**：删除原始文件，并从 Neo4j 图谱与向量库中移除相关记录。

### 路径参数

- `filename`：要删除的文件名（不含路径，内部会进行安全解析）。

### 响应

```json
{
  "status": "success",
  "message": "Successfully deleted example.pdf",
  "details": {
    "graph_nodes_removed": 12,
    "vectors_removed": 48
  }
}
```

删除失败时可能返回：

```json
{ "detail": "File not found" }
```

或 500 错误。

---

## 6. 查询接口 `POST /query`

- **Purpose**：向 GraphRAG 系统发起问答请求，内部通过 `QueryPipeline` 执行 GraphRAG v2 流程。

### 请求体 `QueryRequest`

```json
{
  "query": "What is the secret password for project Antigravity?",
  "mode": "vector"
}
```

- `query`：用户问题文本。
- `mode`（可选）：
  - `"vector"`：**快速模式（向量优先）**。只走向量检索，响应速度最快，适合大多数事实问答与内容查找。
  - `"graph"`：**图模式（关系更强）**。只走知识图谱检索，适合实体关系/路径等需要图结构的场景。
  - `"hybrid"`：**智能模式（自动选择）**。后端根据意图自动在向量/图之间选“快路径”或“图路径”：
    - 问候/关系问题 → 优先走图（`graph_only`）
    - 文档搜索/事实查找 → 优先走向量（`vector_only`）
  - 未传 `mode` 时：等价于“智能模式”，但后端仍会**优先选择向量检索**以保证默认性能。

### 响应体 `QueryResponse`

```json
{
  "answer": "The secret password for project Antigravity is ALPHA-1234.",
  "sources": [
    {
      "text": "The secret password for project Antigravity is ALPHA-1234.",
      "file": "antigravity_spec.txt"
    }
  ],
  "graph_context": []
}
```

---

## 6.1 流式查询 `POST /query/stream`

- **Purpose**：与 `POST /query` 逻辑一致，但以 NDJSON 流返回，便于首字即显与延迟指标展示。
- **Content-Type**：请求 `application/json`；响应 `application/x-ndjson`（每行一个 JSON 对象）。

### 请求体

同 `QueryRequest`：`{ "query": "...", "mode": "vector" | "graph" | "hybrid" }`。

### 响应流（NDJSON）

- **chunk 事件**：`{"type": "chunk", "text": "..."}`，仅包含最终回答文本（thinking 已过滤）。
- **done 事件**：`{"type": "done", "answer": "...", "sources": [...], "pipeline_latency_ms": {...}, "first_token_ms": 200, "total_ms": 1500}`。
  - `pipeline_latency_ms` 包含：`planner_ms`、`vector_retrieval_ms`、`graph_retrieval_ms`、`traversal_ms`、`llm_generation_ms`、`total_ms`、`first_token_ms`、`prompt_chars`、`prompt_tokens`（可选 `cache_hit`）。
- **error 事件**：`{"type": "error", "detail": "..."}`。

---

## 7. 获取系统配置 `GET /settings`

- **Purpose**：读取当前后端使用的模型和基础连接信息。

### 响应

```json
{
  "llm_model": "qwen2.5:7b",
  "extraction_model": "qwen2.5:7b",
  "embedding_model": "bge-m3:latest",
  "embedding_dim": 1024,
  "ollama_base_url": "http://localhost:11434",
  "neo4j_uri": "bolt://localhost:7687",
  "postgres_host": "localhost"
}
```

- 实际使用的模型由设置页或 `.env` 决定；`llm_model` 默认可为 `qwen2.5:7b`，首字延迟高时可改为 `qwen2.5:3b` 等。

---

## 8. 测试连接 `POST /settings/test`

- **Purpose**：测试 LLM 或 Neo4j 的连通性。

### 请求体 / 查询参数

两种方式都支持（为了兼容浏览器缓存行为）：

```json
{
  "type": "llm",
  "url": "http://localhost:11434"
}
```

或以查询参数方式：

`POST /settings/test?type=llm&url=http://localhost:11434`

- `type`：
  - `"llm"`：测试 Ollama 连接（调用 `/api/tags`）。
  - `"graph"`：测试 Neo4j 连接（执行 `RETURN 1`）。

### 响应

成功：

```json
{ "status": "success", "message": "Connected! Found 5 models." }
```

失败：

```json
{ "status": "error", "message": "Connection failed: <详细错误>" }
```

---

## 9. 更新配置 `POST /settings/update`

- **Purpose**：更新 LLM / Embedding / 抽取模型等配置，并持久化到 `.env`，随后重建引擎。

### 请求体（示例）

```json
{
  "llm_model": "qwen2.5:7b",
  "extraction_model": "qwen2.5:7b",
  "embedding_model": "bge-m3:latest",
  "ollama_base_url": "http://localhost:11434"
}
```

- 不必包含所有字段，缺省字段将沿用原值。可选：`.env` 中可设置 `LLM_NUM_CTX`（如 2048）、`LLM_NUM_PREDICT`（如 64）以控制上下文与生成长度，详见 `docs/OPTIMIZATION_LLM_LATENCY.md`。
- 若 `embedding_model` 或 `ollama_base_url` 发生变化，后端会尝试调用 Ollama `/api/embed` 自动探测新模型的向量维度并写入 `EMBEDDING_DIM`。

### 响应

成功：

```json
{
  "status": "success",
  "message": "Settings saved.",
  "embedding_dim": 1024
}
```

失败：

```json
{
  "status": "error",
  "message": "具体错误信息"
}
```

---

## 10. 知识库（文档中心）`GET /knowledge/*`

> **路径说明**：知识库相关接口统一挂在 **`/knowledge`** 下，**避免与 FastAPI 默认 Swagger UI（`GET /docs`）冲突**。前端经 Vite 代理调用时为 `GET /api/knowledge/...`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/knowledge/docs` | 文档列表：`documents[]`（`di_*` 摘要、实体、标签等） |
| GET | `/knowledge/docs/{doc_id}` | 单文档详情；`doc_id` 为 URL 编码后的文件名 |
| GET | `/knowledge/search` | 向量检索：`?q=&top_k=`；`q` 为空时返回空 `results` |
| GET | `/knowledge/entity/{name}` | 实体档案（图聚合 + 弱档案降级） |

- 可选请求头 **`x-lang`**：`zh` / `en` / `ko` 等，影响部分生成与改写逻辑。

---

## 11. 融合检索 `POST /api/v1/hybrid-search`

- **Purpose**：在**不替代**现有 `GET /knowledge/search` 的前提下，提供 **Vector-first、Graph-augmented** 的混合检索：先向量召回 chunk，再从 `di_entities` / 元数据 / 问句词块得到种子实体，在 Neo4j 上做一阶扩展。
- **Design principle**：**Vector-first, graph-augmented** —— 图是增强信号，不是主检索入口；与 `docs/DOCUMENT_INTELLIGENCE_POSITIONING.md` 一致。

### 请求体（JSON）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `query` | string | 必填 | 用户问题或关键词 |
| `top_k` | int | 5 | 向量召回条数（1–30） |
| `graph_expand_k` | int | 20 | 图扩展关系条数上限（1–100） |
| `min_kg_conf` | float | 取配置 `KG_MIN_EDGE_CONFIDENCE_FOR_QUERY` | 关系最小 `kg_confidence`（0–1） |
| `include_fallback` | bool | false | 为 true 时包含低置信 / lexical fallback 边（等价于图侧 `min` 放宽为 0） |

### 响应要点

- `results[]`：`type` 为 `chunk`（向量）或 `relation`（图三元组）。**不单独返回 `entity` 行**，实体信息体现在 `relation.triplet` 与 `debug.seed_entities`。
- 关系项 `score`：先 `min(1, score_base + score_relevance)`（`score_base` 来自 `kg_confidence` 与 fallback 降权；`score_relevance` 为问句词元与主/宾/关系类型匹配的小额加分，上限约 0.35）；若主/宾与**本轮 top_k 向量 chunk** 的 metadata 实体或正文无对齐，再乘以 **0.85**（保证图边尽量「贴着文档证据」）。`vector_anchored` 标明是否通过该锚点检查。
- `debug`：`vector_hits`、`graph_nodes`、`graph_edges`、`seed_entities`。

### 示例（curl）

```bash
curl -s -X POST http://localhost:8000/api/v1/hybrid-search \
  -H "Content-Type: application/json" \
  -d '{"query":"示例问题","top_k":5,"graph_expand_k":20,"include_fallback":false}'
```

---

## 12. 单请求文档洞察 `POST /api/v1/insights/document`

- **Purpose**：在 **DI-first** 前提下，用向量召回的 **supporting_chunks** 作为**唯一摘要证据边界**，可选附带图中与关键实体相关的关系（辅助信号，非摘要主证据）。
- **与** `POST /insights/corpus` **区别**：corpus 聚合多文档 `di_*`；本接口针对**单次查询**，以 chunk 正文为 grounding，适合「就着材料回答」类产品形态。

### 请求体（JSON）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `query` | string | 必填 | 问题或关注焦点 |
| `top_k` | int | 5 | 使用的向量片段条数（1–20） |
| `doc_id` | string | 可选 | 若提供，仅保留 `metadata.file_name` 等于该值的 chunk |
| `include_graph_relations` | bool | true | 是否查询 Neo4j 中与 `key_entities` 相关的关系（`kg_confidence` 过滤） |

### 响应

- `answer`：统一问答字段（主字段）；其内容与 `summary` 等价，用于多入口统一渲染。
- `summary`：兼容字段（与 `answer` 保持一致）；LLM 在**严格仅用 SOURCES** 的提示下生成；无片段时返回固定说明，不杜撰。有片段时提示模型在陈述后附加 **`[1]`、`[2]`** 等引用号，与下方 `ref_index` 对齐，便于前端高亮。
- `source`：仅允许 `rag`（基于文档内容分析）或 `facts`（基于文档结构解析）。
- `supporting_chunks`：`id`、`**ref_index**`（与摘要引用号一致）、`file_name`、`snippet`、`score`。
- `key_entities`：来自召回 chunk 的 metadata 实体。
- `key_relations`：`source` / `relation` / `target`，以及 **`kg_source`**、**`kg_confidence`**（与摄取侧一致，标明辅助信号质量）；**不得**当作可脱离片段独立采信的主证据。
- `insufficient_evidence`：未检索到可用片段时为 `true`。
- `debug`：含 `chunk_count`、`lang_final` 等。

### 示例（curl）

```bash
curl -s -X POST http://localhost:8000/api/v1/insights/document \
  -H "Content-Type: application/json" \
  -H "x-lang: zh" \
  -d '{"query":"本文档主要结论是什么","top_k":5}'
```

---

## 小结

以上接口构成了 GraphRAG 平台的主要 API 面，分别覆盖：

- 文档生命周期：上传 / 列表 / 删除。
- 图谱与摄取进度：图数据、摄取状态、图谱概览（`/graph/overview`）、推荐问题（`/graph/suggested_questions`）。
- 问答能力：基于 GraphRAG v2 的 `/query` 与流式 `/query/stream`。
- **知识库 UI**：`GET /knowledge/docs`、`/knowledge/search`、`/knowledge/entity/...`（与 Swagger `/docs` 分离）。
- **跨文档洞察**：`POST /insights/corpus`（聚合多文档 `di_*`）。
- **融合检索**：`POST /api/v1/hybrid-search`（向量主路径 + 图扩展，独立灰度）。
- **单请求洞察**：`POST /api/v1/insights/document`（片段锚定摘要 + 可选图关系辅助）。
- 系统配置：读取 / 测试连接 / 更新模型配置。

更多细节可参考：

- `docs/INGESTION_PIPELINE.md`
- `docs/QUERY_PIPELINE.md`
- `docs/DOCUMENT_INTELLIGENCE_POSITIONING.md`
- `docs/OPTIMIZATION_LLM_LATENCY.md`
- `docs/DEPLOYMENT.md`
- `docs/CHANGELOG.md`

