# Graph RAG 平台 — Code Review 报告

## 一、项目概述

面向中小企业的 **多模态知识管理 + Graph RAG** 平台：文档上传后经分块、向量化与图谱抽取，支持基于图/向量/混合模式的检索与 LLM 问答，前端提供对话、图可视化、文档管理与系统设置。

| 维度 | 说明 |
|------|------|
| **后端** | Python 3.10、FastAPI、LlamaIndex、Neo4j、PostgreSQL/pgvector、Ollama |
| **前端** | React 19、Vite 7、react-force-graph-2d、i18n（zh/en/ko） |
| **核心模块** | `api/main.py`（HTTP）、`core/graph_engine.py`（图）、`core/vector_store.py`（向量）、`core/ingestion.py`（摄取） |

---

## 二、架构与数据流

```
上传文件 → DATA_RAW_DIR → SMEIngestor.ingest_data()
    → 分块 (SentenceSplitter)
    → 增量写 PG 向量表 (按 embedding 模型分表)
    → 增量写 Neo4j 图 (SimpleLLMPathExtractor，小模型抽取)
查询: POST /query (mode: hybrid | graph | vector)
    → 图检索 (VectorContextRetriever) 或 向量检索
    → 低置信/异常时 hybrid 回退到向量
    → LLM 生成答案 + sources
```

**设计亮点：**

- **双模型分工**：对话/查询用主模型（如 35B），图谱实体关系抽取用专用小模型（如 7B），兼顾效果与速度。
- **增量索引**：Neo4j 与向量库各自判断已索引文件，只处理新文件，避免重复计算。
- **按 embedding 模型分表**：`vector_store` 以模型名生成表名（如 `sme_vs_bge_m3_latest`），换模型不破坏旧数据。
- **问候语快速路径**：简单打招呼不触发重检索，直接 LLM 简短回复，降低延迟。

---

## 三、发现的问题与风险

### 1. 安全

| 问题 | 位置 | 说明 |
|------|------|------|
| **路径穿越** | `api/main.py` 删除/上传 | `filename` 未校验，`../` 可能写到或删除 `DATA_RAW_DIR` 外文件。建议：规范化为 basename 或白名单字符。 |
| **上传无限制** | `POST /upload` | 无文件大小、类型、数量限制，易被滥用或打满磁盘。 |
| **配置写死路径** | `api/main.py` L327、`configs/config.py` | `env_file = "/opt/graphrag-platform/.env"` 写死，容器/多环境部署会失败。建议用 `Path(__file__).resolve().parent.parent / ".env"` 或环境变量。 |

### 2. 依赖与可复现性

- **无 `requirements.txt` / `pyproject.toml`**：依赖仅存在于 `.venv`，新环境需人工推断；无版本锁定，存在依赖漂移风险。
- 建议：至少提供 `requirements.txt`（可由 `pip freeze` 生成并修剪），或使用 `pyproject.toml` + `uv`/`poetry` 管理。

### 3. 部署与运维

- **无 Docker / docker-compose**：Neo4j、Postgres、Ollama、API、前端的启停与网络未在仓库中定义，生产部署依赖外部文档或手工操作。
- **摄取状态仅内存**：`INGESTION_STATE` + `threading.Lock` 存于进程内，多实例无法协调，重启后状态丢失；若有“正在摄取”的持久化需求，需 Redis 或 DB 存储。

### 4. 配置与多环境

- **`/settings/update` 直接写 .env**：整文件重写，若 .env 中有未在 API 中声明的变量会被覆盖；且路径写死，不利于容器与多实例。
- 建议：用环境变量或配置中心驱动；若保留写文件，路径应从项目根推导，并只更新已知键而非整文件覆盖。

### 5. 代码与可维护性

- **全局可变状态**：`INGESTION_STATE`、`ingestion_lock` 以及 `graph_engine`/`vector_engine`/`ingestor` 在 `update_settings` 中全局替换，可读性与单测难度增加；可考虑依赖注入或显式“应用级单例”封装。
- **`/graph/data` 直接访问 `graph_engine.graph_store._driver`**：依赖 LlamaIndex 内部实现，升级可能断裂；若有稳定 API 应优先使用。
- **SQL 与表名**：`vector_store.py` 中 `_drop_table(full_table_name)` 使用 f-string 拼表名（表名来自配置，非用户输入），目前风险较低，但若未来表名来源扩展，需严防注入；`ingestion.py` 中 `metadata_ ->> 'file_name'` 与表名来自 `vector_engine.full_table_name`，同属“配置驱动”，建议保持并集中校验。

### 6. 测试

- **依赖真实服务**：`test_api.py`、`test_integration.py` 依赖真实 Ollama/Neo4j/Postgres，无 mock 或 testcontainers，CI 或离线环境易失败。
- **集成测试与后台任务**：`test_integration.py` 通过直接调用 `ingestor.ingest_data()` 规避后台任务，若以后改为仅后台触发，需用轮询或事件等待。

### 7. 文档

- 项目根目录无 README：新成员上手、本地启动、环境变量、端口与依赖说明缺失，建议补充最小可运行说明（含 Docker 若后续提供）。

---

## 四、改进建议（优先级）

### 高优先级

1. **安全**：上传与删除接口对 `filename` 做规范化与校验（禁止 `..`、限制字符集或扩展名白名单）；为上传增加文件大小与数量限制。
2. **依赖**：增加 `requirements.txt` 或 `pyproject.toml`，并锁定关键版本（LlamaIndex、FastAPI、Neo4j driver、psycopg2 等）。
3. **配置路径**：`.env` 路径改为基于项目根或环境变量（如 `GRAPHrag_ENV_FILE`），避免写死 `/opt/...`。

### 中优先级

4. **部署**：提供 `Dockerfile` 与 `docker-compose.yml`（API + 前端；Neo4j/Postgres/Ollama 可用 compose 或文档说明连接已有服务）。
5. **README**：说明项目定位、本地运行步骤、主要环境变量、端口（如 API 8000、前端 5173）。
6. **设置持久化**：若保留写 .env，改为“只更新已知键”或备份原文件，避免覆盖未在 API 中声明的变量。

### 低优先级

7. **摄取状态**：若有多实例或重启后需展示“正在摄取”，引入 Redis 或 DB 存储状态与锁。
8. **测试**：为 API 与引擎层增加 mock 测试，保证 CI 不依赖真实 Ollama/Neo4j/Postgres；集成测试可保留为可选或标记为 `integration`。

---

## 五、总结

- **架构清晰**：图 + 向量双引擎、增量摄取、双模型分工、混合检索与回退策略设计合理，适合作为 SME 知识库与 Graph RAG 的起点。
- **主要短板**：依赖与部署未标准化、配置路径与安全校验不足、无项目级文档；建议优先补齐安全与依赖，再补充部署与 README，以便于协作与上线。

如需对某一块做更细的修改方案（例如具体补丁或 PR 清单），可以指定模块（如仅 API、仅 ingestion 或仅部署）。
