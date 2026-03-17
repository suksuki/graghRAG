# GraphRAG Platform

面向中小企业的 **Graph RAG 知识库平台**：支持文档上传、图谱与向量双路检索、多模态文档解析，以及基于 LLM 的问答与图可视化。

## System Overview（系统概览）

GraphRAG Platform 是一个面向中小企业的 **图谱 + 向量 + LLM** 知识检索平台，主要能力包括：

- 文档上传与解析（支持多种 Office / PDF / 图片 / XDMP 等格式）。
- 基于 pgvector 的语义检索。
- 基于 Neo4j 的知识图谱构建与关系查询。
- 通过 **QueryPipeline（GraphRAG v2）** 对查询进行意图识别、策略选择、重排与上下文压缩。
- 通过 Celery + Redis 异步执行摄取任务，避免阻塞 API。

更多架构细节见 `docs/ARCHITECTURE.md`。

## 技术栈

| 组件     | 技术 |
|----------|------|
| 后端     | Python 3.10、FastAPI、LlamaIndex |
| 图存储   | Neo4j |
| 向量存储 | PostgreSQL + pgvector |
| LLM/Embedding | Ollama（本地或远程） |
| 前端     | React 19、Vite 7、react-force-graph-2d、i18n |

## Architecture（架构概览）

高层组件：

- **API 层（FastAPI）**：`api/main.py` + `api/routes/*`，负责 HTTP 路由与 CORS。
- **Controllers**：`api/controllers/*`，封装业务逻辑（查询、摄取、配置）。
- **QueryPipeline**：`pipelines/query_pipeline.py`，实现 GraphRAG v2 查询编排。
- **Ingestion Pipeline**：`core/ingestion.py` + `workers/celery_worker.py`，负责从原始文件到向量库与图谱的摄取。
- **GraphEngine**：`core/graph_engine.py`，管理 Neo4j 图存储与图查询。
- **VectorEngine**：`core/vector_store.py`，管理 PostgreSQL + pgvector。
- **异步任务与队列**：Celery + Redis 作为摄取任务队列与状态存储。

详细说明与文本版架构图见：

- `docs/ARCHITECTURE.md`
- `docs/INGESTION_PIPELINE.md`
- `docs/QUERY_PIPELINE.md`

## 本地运行

### 1. 环境要求

- Python 3.10+
- Node.js 18+（前端）
- 已运行的 **Ollama**（提供 LLM 与 Embedding 模型）
- 可选：Neo4j、PostgreSQL+pgvector（若不使用 Docker 则需本地安装）

### 2. 后端（API 服务）

```bash
# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 配置：复制并编辑 .env（或通过环境变量设置）
cp .env.example .env
# 必改：OLLAMA_BASE_URL、NEO4J_*、POSTGRES_*

# 启动 API（默认 http://0.0.0.0:8000）
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 前端（可选）

```bash
cd apps
npm install
npm run dev
```

浏览器访问前端开发服务器（如 `http://localhost:3000`），前端会将 `/api` 代理到后端 `http://localhost:8000`。

### 4. 使用 Docker Compose 启动后端与数据库

不安装本地 Neo4j/PostgreSQL 时，可用 Compose 启动 API + Neo4j + Postgres：

```bash
# 需先有 .env，且 OLLAMA_BASE_URL 指向宿主机 Ollama（如 http://host.docker.internal:11434）
docker compose up -d

# API 地址: http://localhost:8000
# Neo4j 浏览器: http://localhost:7474
```

前端仍在本机执行 `cd apps && npm run dev`，代理到 `http://localhost:8000`。

## How to Run（运行步骤总览）

1. **准备依赖服务**：
   - 启动 Neo4j、PostgreSQL（带 pgvector）、Redis、Ollama。
   - 或使用 `docker-compose.yml` 启动 Neo4j + Postgres，并单独启动 Redis / Ollama。
2. **安装依赖**：
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
   - （前端）`cd apps && npm install`
3. **配置环境变量**：
   - `cp .env.example .env` 并根据实际环境修改。
4. **启动后端 API**：
   - `uvicorn api.main:app --host 0.0.0.0 --port 8000`
5. **启动 Celery Worker**：
   - `celery -A workers.celery_worker.celery_app worker -l info`
6. **启动前端（可选）**：
   - `npm run dev`（在 `apps` 目录下）。

更详细的部署说明（包括典型启动顺序与常见问题）见：`docs/DEPLOYMENT.md`。

## 环境变量说明

| 变量 | 说明 | 默认 |
|------|------|------|
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://192.168.0.10:11434` |
| `LLM_MODEL` | 对话/查询用模型（可由设置页覆盖） | `qwen2.5:7b` |
| `LLM_NUM_CTX` | Ollama 上下文长度上限（首字/prefill 优化） | `1024`（代码默认 2048） |
| `LLM_NUM_PREDICT` | 单次生成最大 token 数 | `64` |
| `EXTRACTION_MODEL` | 图谱实体抽取用模型 | `qwen2.5:7b` |
| `EXTRACTION_TIMEOUT` | 单次抽取请求超时（秒），避免图索引“卡住” | `120` |
| `EMBEDDING_MODEL` | 向量化模型 | `bge-m3:latest` |
| `NEO4J_URI` | Neo4j Bolt 地址 | `bolt://localhost:7687` |
| `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j 认证 | - |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | PostgreSQL 连接 | - |
| `DATA_RAW_DIR` | 上传文档存放目录 | 项目根目录下 `data/raw` |
| `GRAPHRAG_ENV_FILE` | 可选，指定 .env 路径 | 项目根目录下 `.env` |

首字/LLM 延迟优化说明见：`docs/OPTIMIZATION_LLM_LATENCY.md`。

## 端口说明

| 服务   | 默认端口 |
|--------|----------|
| 后端 API | 8000 |
| 前端 dev | 3000（Vite） |
| Neo4j HTTP | 7474 |
| Neo4j Bolt | 7687 |
| PostgreSQL | 5432 |

## Testing（测试）

### 快速命令

```bash
# 全部测试（依赖真实 Ollama / Neo4j / Postgres / Redis）
pytest -v

# 仅单元测试
pytest -v tests/test_utils.py
```

或使用 Makefile（若可用）：

```bash
make test
make test-unit
make test-integration
```

### 测试内容

- **单元测试**：验证安全工具函数、路径解析、配置逻辑等。
- **引擎与 API 测试**：验证 GraphEngine / VectorEngine / API 路由的基本行为。
- **端到端回归测试**：`tests/test_integration.py::test_full_ingestion_and_query_flow`，覆盖「上传 → 摄取 → 查询」完整链路。

测试环境清理与更多细节见：`docs/TESTING.md`。

## 解析进度说明

- 解析状态会按阶段更新（扫描 → 加载 → 分块 → 向量 → 图索引），图索引阶段会按批显示「图索引进度: 已处理 x/y 块」和百分比。
- **代码或配置更新后需重启 API 服务**，新的进度逻辑和 `GRAPH_MAX_NODES` 等配置才会生效；否则界面可能仍显示旧文案或 78 块全量索引。

## 图索引加速（可选）

在 `.env` 中可调：

- **`GRAPH_MAX_NODES=30`**（默认）：单次摄取最多只对前 30 个文本块做图索引，其余只进向量库。例如 78 块文档只触发 30 次 LLM 调用，耗时明显缩短。设为 `0` 表示不限制。
- **`CHUNK_SIZE=1536`**：分块变大，块数变少，图索引 LLM 调用次数减少。
- **`EXTRACTION_NUM_WORKERS=4`**：图抽取并发数，显存允许可适当调大。

## 为什么图索引比向量化慢、容易“卡住”？

- **向量化**：对所有文本块做一次批量 embedding，再写入 PostgreSQL，通常很快。
- **图索引**：对**每个文本块**都会调用一次 **EXTRACTION_MODEL**（LLM）做实体关系抽取，再写入 Neo4j。块越多，LLM 调用次数越多，耗时会明显长于向量化，属于正常现象。
- 若 Ollama 首次加载模型或单次推理较慢，图索引阶段会长时间无进度，看起来像“卡住”。可：
  - 使用更小的抽取模型（如 `qwen2.5:1.5b`）加快单次调用；
  - 在 `.env` 中设置 `EXTRACTION_TIMEOUT=120`，单块超时后会报错而非一直挂起；
  - 查看后端日志中的 `Graph extraction starting: ... expect ~N calls` 以确认进度。

## Documentation Links（文档索引）

- **架构说明**：`docs/ARCHITECTURE.md`
- **API 参考**：`docs/API_REFERENCE.md`
- **变更记录**：`docs/CHANGELOG.md`
- **摄取流水线**：`docs/INGESTION_PIPELINE.md`
- **查询流水线（GraphRAG v2）**：`docs/QUERY_PIPELINE.md`
- **首字/LLM 延迟优化**：`docs/OPTIMIZATION_LLM_LATENCY.md`
- **部署指南**：`docs/DEPLOYMENT.md`
- **测试体系**：`docs/TESTING.md`

## 项目结构

```
├── api/           # FastAPI 路由与安全校验
├── configs/       # 配置与 .env 路径
├── core/          # 图引擎、向量存储、摄取管道
├── apps/          # 前端（React + Vite）
├── tests/         # 测试
├── requirements.txt
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 安全与限制

- **上传**：仅允许扩展名白名单（如 .pdf、.docx、.txt 等），单文件最大 50MB，单次最多 20 个文件；文件名会做安全规范化，禁止路径穿越。
- **删除**：仅允许删除 `DATA_RAW_DIR` 下的文件，且通过安全文件名解析，防止 `../` 等路径穿越。
- **配置**：`.env` 路径可通过 `GRAPHRAG_ENV_FILE` 覆盖，便于容器与多环境部署；设置页“保存”仅更新已知配置键，不覆盖整文件。

## License

ISC
