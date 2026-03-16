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

---

## 4. 摄取状态 `GET /ingestion/status`

- **Purpose**：查询当前摄取进度与图节点、文件数等概况。

### 请求

- 无参数。

### 响应

```json
{
  "status": "processing",        // 或 "idle"
  "message": "Graph indexing: 5/20 chunks (70%)",
  "progress": 70,                // 0-100
  "graph_done": 5,
  "graph_total": 20,
  "files_in_batch": 3,
  "file_names": ["a.pdf", "b.txt", "c.docx"],
  "node_count": 128,             // Neo4j 节点数
  "file_count": 10               // 原始目录中文件数
}
```

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

## 7. 获取系统配置 `GET /settings`

- **Purpose**：读取当前后端使用的模型和基础连接信息。

### 响应

```json
{
  "llm_model": "qwen3.5:35b",
  "extraction_model": "qwen2.5:7b",
  "embedding_model": "bge-m3:latest",
  "embedding_dim": 1024,
  "ollama_base_url": "http://localhost:11434",
  "neo4j_uri": "bolt://localhost:7687",
  "postgres_host": "localhost"
}
```

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
  "llm_model": "qwen3.5:35b",
  "extraction_model": "qwen2.5:7b",
  "embedding_model": "bge-m3:latest",
  "ollama_base_url": "http://localhost:11434"
}
```

- 不必包含所有字段，缺省字段将沿用原值。
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

## 小结

以上接口构成了 GraphRAG 平台的主要 API 面，分别覆盖：

- 文档生命周期：上传 / 列表 / 删除。
- 图谱与摄取进度：图数据、摄取状态。
- 问答能力：基于 GraphRAG v2 的 `/query`。
- 系统配置：读取 / 测试连接 / 更新模型配置。

更多细节可参考：

- `docs/INGESTION_PIPELINE.md`
- `docs/QUERY_PIPELINE.md`
- `docs/DEPLOYMENT.md`

