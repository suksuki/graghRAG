## 部署指南（GraphRAG Platform）

本指南介绍如何在本地或服务器上部署 GraphRAG 平台，包括所需服务、环境配置以及启动命令。

---

## 1. 依赖服务概览

GraphRAG 平台依赖以下组件：

- **Neo4j**：存储知识图谱（实体与关系）。
- **PostgreSQL + pgvector**：存储向量嵌入。
- **Ollama**：提供 LLM、Embedding 和抽取模型。
- **Redis**：作为 Celery 的任务队列与结果后端。
- **FastAPI 应用**：后端 API（本项目）。
- **Celery Worker**：执行文档摄取等异步任务。
- （可选）**前端（React + Vite）**：交互界面。

---

## 2. 环境准备

### 2.1 安装依赖

#### Python & Node

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nodejs npm
```

#### 数据库与 Redis（若不使用 Docker）

```bash
# Neo4j、PostgreSQL、Redis 安装方式略（可使用官方安装包或 Docker）
```

推荐在开发/测试环境中使用 **Docker Compose** 统一管理 Neo4j + Postgres + Redis，详见本仓库 `docker-compose.yml`。

---

## 3. Python 依赖安装

在项目根目录（`/opt/graphrag-platform`）：

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

> `requirements.txt` 中已包含：FastAPI、LlamaIndex 系列、Neo4j 驱动、psycopg2-binary、httpx、nest-asyncio、celery、redis 等。

---

## 4. 配置 .env

复制示例文件：

```bash
cp .env.example .env
```

至少需检查并设置以下字段：

- **Ollama**
  - `OLLAMA_BASE_URL=http://localhost:11434`
  - `LLM_MODEL=qwen3.5:35b`（示例，可按需替换）
  - `EXTRACTION_MODEL=qwen2.5:7b`
  - `EMBEDDING_MODEL=bge-m3:latest`

- **Neo4j**
  - `NEO4J_URI=bolt://localhost:7687`
  - `NEO4J_USER=neo4j`
  - `NEO4J_PASSWORD=your_password`

- **PostgreSQL**
  - `POSTGRES_HOST=localhost`
  - `POSTGRES_PORT=5432`
  - `POSTGRES_USER=postgres`
  - `POSTGRES_PASSWORD=your_password`
  - `POSTGRES_DB=graphrag`

- **Redis（Celery）**
  - Celery 默认使用：`redis://localhost:6379/0`

- **数据目录**
  - `DATA_RAW_DIR=/opt/graphrag-platform/data/raw`（默认即可）。

> 修改 `.env` 后，需重启 API / Worker 进程以生效。

---

## 5. 启动依赖服务

### 5.1 使用 Docker Compose（推荐）

根目录下已提供 `docker-compose.yml`，包含：

- `api` 服务（可选，若你只想用容器跑后端）。
- `neo4j` 服务。
- `postgres` 服务。

使用前：

- 确保 `.env` 中的 `OLLAMA_BASE_URL` 可从容器内访问（例如 `http://host.docker.internal:11434`）。

启动命令：

```bash
docker compose up -d
```

服务端口：

- API：`http://localhost:8000`
- Neo4j 浏览器：`http://localhost:7474`
- PostgreSQL：`localhost:5432`

### 5.2 手工启动服务

若使用本机服务：

1. 启动 Neo4j（确保 Bolt = `7687`，HTTP = `7474`）。
2. 启动 PostgreSQL，并创建数据库 `graphrag`，安装 pgvector 扩展。
3. 启动 Redis：

```bash
redis-server
```

4. 启动 Ollama 并拉取所需模型：

```bash
ollama serve &
ollama pull qwen3.5:35b
ollama pull qwen2.5:7b
ollama pull bge-m3:latest
```

---

## 6. 启动 FastAPI 后端

在项目根目录：

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

> 生产环境建议使用 `gunicorn` + `uvicorn.workers.UvicornWorker` 或通过 Docker 部署。

---

## 7. 启动 Celery Worker

在同一虚拟环境中，另开一个终端：

```bash
cd /opt/graphrag-platform
source .venv/bin/activate

celery -A workers.celery_worker.celery_app worker -l info
```

- 该 worker 将监听 Redis broker，并执行 `ingest_document_task`。
- 日志中可看到摄取进度与错误。

---

## 8. 启动前端（可选）

进入前端目录：

```bash
cd /opt/graphrag-platform/apps
npm install
npm run dev
```

默认访问：

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000`

Vite dev server 会将 `/api` 请求代理到后端。

---

## 9. 典型启动顺序（本机 / 开发机）

1. 启动 Ollama：

   ```bash
   ollama serve &
   ```

2. 启动 Neo4j / PostgreSQL / Redis（可用 Docker Compose，一条命令搞定）：

   ```bash
   docker compose up -d neo4j postgres
   redis-server &
   ```

3. 启动 FastAPI：

   ```bash
   source .venv/bin/activate
   uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. 启动 Celery Worker：

   ```bash
   source .venv/bin/activate
   celery -A workers.celery_worker.celery_app worker -l info
   ```

5. （可选）启动前端：

   ```bash
   cd apps
   npm install
   npm run dev
   ```

---

## 10. 健康检查与测试

- 访问 API 根路径：

  ```bash
  curl http://localhost:8000/
  ```

  返回类似：

  ```json
  {
    "project": "GraphRAG Platform",
    "status": "online",
    "engines": {
      "graph": "Neo4j",
      "vector": "PGVector",
      "llm": "<当前 LLM_MODEL>"
    }
  }
  ```

- 访问前端（如启用）：`http://localhost:3000`
- 使用 `pytest -v` 跑回归测试（详细见 `docs/TESTING.md`）。

---

## 11. 常见问题（部署相关）

- **Q：API 启动正常，但查询超时或报连接错误？**
  - 检查 Ollama / Neo4j / PostgreSQL / Redis 是否全部运行。
  - 确认 `.env` 中的地址与端口是否正确。

- **Q：Celery Worker 日志中大量 “Connection refused” to Redis？**
  - Redis 未启动或端口错误。
  - 修正 `broker` / `backend` 地址或重新启动 Redis。

- **Q：图索引非常慢，看起来“卡住”？**
  - 参考 `README.md` 与 `docs/INGESTION_PIPELINE.md` 中的「图索引加速」与 `GRAPH_MAX_NODES` 配置说明。

