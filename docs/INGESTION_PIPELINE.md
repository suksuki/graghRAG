## 文档摄取流水线（Ingestion Pipeline）

本篇文档说明 GraphRAG 平台中，从**文件上传到写入图谱和向量库**的完整流程，以及相关模块。

---

## 总体流程（自上而下）

```text
客户端（前端/脚本）
    │
    │ POST /upload (multipart/form-data)
    ▼
FastAPI 路由：api/routes/ingestion_routes.py
    │
    ▼
Controller：api/controllers/ingestion_controller.py::handle_upload
    │
    ├─ 保存文件到 DATA_RAW_DIR
    └─ Celery 任务：ingest_document_task.delay(file_path)
                     （workers/celery_worker.py）
                           │
                           ▼
                 Celery Worker 进程
                           │
                           ▼
                SMEIngestor.ingest_data(...)
                （core/ingestion.py）
                           │
                           ├─ 句子/段落分块：SentenceSplitter
                           ├─ 向量写入：VectorEngine.add_documents(...)
                           └─ 图索引：GraphEngine.create_index(...)
```

---

## 1. 文件上传阶段

### 1.1 路由：`POST /upload`

位置：`api/routes/ingestion_routes.py`

```python
@router.post("/upload")
def upload_route(files: List[UploadFile] = File(...)):
    try:
        # 控制器内部会将任务推送到 Celery，并返回排队结果
        return handle_upload(files)
    ...
```

- 接收字段 `files`（可多个）。
- 将业务委托给 `handle_upload`。

### 1.2 控制器：`handle_upload`

位置：`api/controllers/ingestion_controller.py`

关键逻辑：

- 校验：
  - 单次上传数量不超过 `MAX_FILES_PER_UPLOAD`。
  - 通过 `sanitize_filename` 过滤非法文件名、防止路径穿越。
  - 检查扩展名是否在白名单 `ALLOWED_EXTENSIONS` 内。
  - 单文件大小不超过 `MAX_FILE_SIZE_BYTES`。
- 存储：
  - 将文件流写入到 `settings.DATA_RAW_DIR`。
  - 记录成功写入的文件名列表 `saved_files`。
- 调度：
  - 对每个 `fname`：
    - 写入 Redis 状态：`ingestion:{fname} = "queued"`。
    - 调用 `ingest_document_task.delay(file_path)` 投递 Celery 任务。

返回值示例：

```json
{
  "status": "queued",
  "filename": "file1.pdf",
  "files": ["file1.pdf", "file2.txt"]
}
```

---

## 2. Celery Worker 与 Redis 状态

位置：`workers/celery_worker.py`

```python
celery_app = Celery(
    "ingestion_worker",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

redis_client = redis.Redis.from_url("redis://localhost:6379/0")
```

### 2.1 状态键

- Key 形式：`ingestion:{filename}`
- Value 取值：
  - `queued`：已排队，将被 worker 处理。
  - `processing`：worker 正在处理该文件批次。
  - `done`：摄取成功。
  - `failed`：摄取失败。

### 2.2 任务：`ingest_document_task(file_path)`

- 将 `ingestion:{filename}` 置为 `processing`。
- 构建 `SMEIngestor()`（见下一节）。
- 调用 `ingestor.ingest_data(directory_path=...)`，以目录为单位执行增量摄取。
- 成功时将状态改为 `done`，异常时改为 `failed`。

> 注意：`ingest_data` 本身支持**增量逻辑**，即多次运行不会重复写入同一文件的数据。

---

## 3. SMEIngestor（核心摄取引擎）

位置：`core/ingestion.py`

核心类：`SMEIngestor`

### 3.1 初始化

```python
class SMEIngestor:
    def __init__(self):
        self.graph_engine = GraphEngine()
        self.vector_engine = VectorEngine()
        self.splitter = SentenceSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
```

- 每个实例维护自己的：
  - `GraphEngine`：负责写 Neo4j。
  - `VectorEngine`：负责写 pgvector。
  - `SentenceSplitter`：负责将文档拆分成 chunk。

### 3.2 增量策略

在 `ingest_data` 开头：

1. 查询 Neo4j 中**已索引的文件**：

```python
graph_indexed = self.graph_engine.get_indexed_files()
```

2. 查询 pgvector 中**已存在的文件名**：

```python
vector_indexed = _get_vector_indexed_files(self.vector_engine)
```

3. 扫描目录中所有文件 `all_files`，根据上述集合计算出：
   - `new_for_vector`：需要写向量的新文件。
   - `new_for_graph`：需要建图的新文件。

如果两者都为空，则直接返回，不做任何操作。

### 3.3 文档读取与分块

- 使用 `SimpleDirectoryReader` 读取 `files_to_load` 对应的文件。
- 使用 `SentenceSplitter` 将 `documents` 拆分成 `all_nodes`：
  - 支持配置块大小与重叠度。
  - 每个 node 保留 `file_name` 等 metadata，用于后续过滤。

---

## 4. 向量写入（VectorEngine）

位置：`core/vector_store.py` + `core/ingestion.py` 中的调用。

### 4.1 VectorEngine 简要

- 使用 `PGVectorStore` 将向量存入 PostgreSQL。
- 每个 embedding 模型对应一张物理表：`data_sme_vs_<model_suffix>`。
- 支持：
  - 通过元数据中的 `file_name` 删除某个文件的全部向量。
  - 通过 `VectorStoreIndex` 构建索引并暴露查询引擎。

### 4.2 写入流程

在 `ingest_data` 中：

1. 从 `all_nodes` 中筛选出 `vector_nodes`（只保留 `file_name` 在 `new_for_vector` 集合中的节点）。
2. 若有新节点：
   - 打日志说明待插入数量。
   - 调用 `VectorEngine.add_documents(vector_nodes)` 将节点批量写入 pgvector。
3. 若没有新节点：
   - 跳过向量阶段，只更新进度信息。

---

## 5. 图索引构建（GraphEngine）

位置：`core/graph_engine.py` + `core/ingestion.py` 中的调用。

### 5.1 GraphEngine 简要

- 维护两个 LLM：
  - `llm`：主模型，用于图查询等。
  - `extraction_llm`：专用于实体/关系抽取的小模型。
- 使用 `Neo4jPropertyGraphStore` 维护图。
- `get_indexed_files()` 用于增量跳过已处理文件。
- `create_index(nodes, num_workers, max_paths_per_chunk)` 用于抽取图结构。

### 5.2 写入流程

在 `ingest_data` 中：

1. 从 `all_nodes` 中筛选出 `graph_nodes`（`file_name` 在 `new_for_graph` 集合中）。
2. 按 `GRAPH_MAX_NODES`（可在 `.env` 中配置）裁剪最大处理节点数量，以控制单次图索引耗时。
3. 根据 `num_graph` 计算批大小 `batch_size`，分批调用：

```python
self.graph_engine.create_index(batch)
```

4. 每处理完一批，更新进度：
   - `graph_done` / `graph_total`
   - `progress` 百分比（55% ~ 95% 区间）。

5. 所有批次完成后，将总体进度置为 100%，并返回文档与节点数量。

---

## 6. 摄取状态与前端展示

虽然 Celery 任务与 `SMEIngestor` 异步运行，但前端可以通过：

- `GET /ingestion/status`

获取当前进度，包括：

- `status`：`idle` / `processing`
- `message`：阶段性描述（扫描 / 向量 / 图索引进度等）。
- `graph_done` / `graph_total`：图索引块进度。
- `files_in_batch` / `file_names`：当前轮处理的文件列表。
- `node_count`：Neo4j 节点数。
- `file_count`：原始目录中文档数。

---

## 7. 小结

摄取流水线通过以下模块协作完成：

- **Ingestion Routes + Controller**：处理 HTTP 请求、写文件、调度 Celery。
- **Celery Worker + Redis**：异步执行增量摄取任务，并记录状态。
- **SMEIngestor**：负责从磁盘读取文档、分块、增量写入向量与图谱。
- **VectorEngine / GraphEngine**：封装对 PostgreSQL + pgvector 与 Neo4j 的写入与查询。

整体设计保证：

- 能够多次运行而不会重复索引同一文件。
- 摄取进度对用户可见（前端进度条）。
- 后端可以通过修改 `.env` 调整分块大小、图索引上限与并发度，以在**速度与成本**之间平衡。

