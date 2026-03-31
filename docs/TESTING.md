## 测试体系说明（GraphRAG Platform）

本篇文档介绍 GraphRAG 平台的自动化测试体系，包括单元测试、集成测试以及如何保持测试环境干净。

---

## 1. 测试类型概览

目录：`tests/`

| 文件 | 类型 | 说明 |
|------|------|------|
| `test_utils.py` | 单元 | `sanitize_filename`、`resolve_path_under`、扩展名白名单等；无外部依赖 |
| `test_document_loader.py` | 单元 | `core/document_loader`：按扩展名分发、HTML 剥离、`.doc` 转换与回退 |
| `test_multilingual_graph_query.py` | 单元 | 多语言检测、precompute key、建议问题、query_controller 语言偏好等 |
| `test_query_pipeline_contract.py` | 契约 | 流式 `done` 中 `graph` / `debug` 字段形状与 canonical entity 链路 |
| `test_ppt_summary_route.py` | 单元 / 契约 | 文档洞察 RAG path、planner fallback、`structured_evidence` provenance |
| `test_person_entities.py` | 单元 | facts short-circuit 与人员结构抽取 |
| `test_engines.py` | 集成（`integration`） | `GraphEngine` / `VectorEngine` / `SMEIngestor` 初始化与图查询引擎 |
| `test_api.py` | API + 少量集成 | `TestClient` 走真实 HTTP；含 Ollama 直连与 `/settings/test` |
| `test_integration.py` | 端到端 | `test_full_ingestion_and_query_flow`：上传 → 摄取 → `/query` |

### `test_api.py` 契约要点（产品化接口）

- `GET /`：健康检查。
- `GET /settings`：配置字段存在。
- `POST /api/v1/insights/document`：`answer`（且 `answer == summary` 兼容）、`source ∈ {rag,facts}`、`supporting_chunks`（有条目时含 **`ref_index`**）、`structured_evidence`（若存在需带 `role/persons/ref_indices/file_names` provenance）、`decision`、`key_relations`、`insufficient_evidence`。
- `POST /api/v1/hybrid-search`：`results`、`debug.vector_hits`、`debug.graph_edges`。
- `GET /knowledge/docs`、`GET /knowledge/search`：知识库列表与搜索（**不得**使用根路径 `GET /docs`，与 Swagger 冲突）。
- `POST /insights/corpus`：语料洞察响应字段完整。
- 集成：`test_ollama_direct_connection`、`test_api_settings_test_endpoint`（需可用 Ollama）。

---

## 2. 清理环境的自动化 Fixture

位置：`tests/conftest.py`

```python
import os

import psycopg2
import pytest

from configs.config import settings


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration (needs Ollama/Neo4j/Postgres)")


@pytest.fixture(autouse=True)
def clean_test_environment(request):
    """
    在每个测试前清理图数据库、向量库以及原始文件目录，避免历史数据干扰回归测试。
    """
    if request.node.get_closest_marker("integration") is None:
        yield
        return

    from api.deps import graph_engine, vector_engine

    # A. 清理 Neo4j 图
    try:
        with graph_engine.graph_store._driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
    except Exception as e:  # noqa: BLE001
        print(f"[conftest] Failed to clear Neo4j: {e}")

    # B. 清理向量表（pgvector）
    try:
        table = vector_engine.full_table_name
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"[conftest] Failed to clear PGVector table: {e}")

    # C. 清理原始文件目录
    try:
        if os.path.isdir(settings.DATA_RAW_DIR):
            for fname in os.listdir(settings.DATA_RAW_DIR):
                fpath = os.path.join(settings.DATA_RAW_DIR, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
    except Exception as e:  # noqa: BLE001
        print(f"[conftest] Failed to clear raw data dir: {e}")

    yield
```

**作用：**

- 每个测试用例前自动执行，确保：
  - Neo4j 中不残留上一次测试的节点。
  - pgvector 表中不残留旧向量。
  - `DATA_RAW_DIR` 中只有当前测试写入的文件。
- 保证 `test_full_ingestion_and_query_flow` 每次运行时，查询结果中只包含**本轮上传的唯一密码**，而不会混入历史 ALPHA-XXXX。

---

## 3. 端到端集成测试流程

用例：`tests/test_integration.py::test_full_ingestion_and_query_flow`

伪代码逻辑：

```python
def test_full_ingestion_and_query_flow(client):
    # 1. 构造唯一事实
    unique_id = int(time.time())
    fact_content = f"The secret password for project Antigravity is ALPHA-{unique_id}."
    file_name = f"test_fact_{unique_id}.txt"

    # 2. 上传
    files = [("files", (file_name, fact_content, "text/plain"))]
    response = client.post("/upload", files=files)
    assert response.status_code == 200
    assert file_name in response.json()["files"]

    # 3. 确认文件已落盘
    file_path = os.path.join(settings.DATA_RAW_DIR, file_name)
    assert os.path.exists(file_path)

    # 4. 手动触发同步摄取（测试环境用）
    from api.main import ingestor
    ingestor.ingest_data()

    # 5. 通过 /query 查询这条事实
    query_payload = {
        "query": "What is the secret password for project Antigravity?",
        "mode": "hybrid",
    }

    max_retries = 3
    for i in range(max_retries):
        response = client.post("/query", json=query_payload)
        assert response.status_code == 200
        answer = response.json()["answer"]

        if f"ALPHA-{unique_id}" in answer:
            break
        time.sleep(2)
    else:
        pytest.fail("如果 3 次仍未命中，则视为回归失败。")
```

要点：

- 使用 `unique_id` 确保每次测试的密码唯一。
- 使用 `client.post("/upload")` 和 `client.post("/query")` 走真实 API。
- 用 `ingestor.ingest_data()` 在测试中**同步**完成摄取流程，避免等待 Celery 状态。
- 允许最多重试 3 次，以避免首次图索引或 embedding 略有延迟。

---

## 4. 运行测试

### 4.1 全部测试

需要：Ollama / Neo4j / PostgreSQL / Redis 全部可用。

```bash
cd /opt/graphrag-platform
source .venv/bin/activate

pytest -v
```

推荐（显示最完整摘要）：

```bash
pytest -v -ra
```

或使用 Makefile（如果存在）：

```bash
make test
```

### 4.2 仅单元测试

```bash
pytest -v tests/test_utils.py
```

或排除 integration 标记（前提是集成用例都标了 `@pytest.mark.integration`）：

```bash
pytest -v -m "not integration"
```

### 4.3 仅集成 / 回归测试

```bash
pytest -v tests/test_engines.py tests/test_api.py tests/test_integration.py
```

### 4.4 分层执行（单元 → 集成 → 回归）

```bash
# 单元
pytest -v tests/test_utils.py

# API/引擎集成
pytest -v tests/test_api.py tests/test_engines.py

# 端到端回归
pytest -v tests/test_integration.py
```

### 4.5 快速发布验收 / 自动化入口

```bash
# Makefile 封装
make test-unit
make test-contract
make test-smoke
make test-load
make test-ui
make release-check
```

说明：

- `make test-contract`：跑快速契约 / 回归测试，不要求完整外部栈。
- `make test-smoke`：命中 `/`、`/settings`、`/knowledge/search`、`/api/v1/hybrid-search`、`/api/v1/insights/document`。
- `make test-load`：并发压测核心 API，输出按 endpoint 聚合的失败数、P50、P95、max latency。
- `make test-ui`：运行 Playwright 的结构化证据 UI 套件（需前端 dev server 已启动）。
- `make release-check`：适合版本收尾，串联 `unit + contract + smoke`。

### 4.6 关键断言（当前版本）

建议在新增回归用例时覆盖以下契约：

- `run_stream` done 事件必须包含：
  - `graph.used/relations/count/two_hop/summary`
  - `debug.graph_used/graph_relations_count/answer_mode/precompute_hit`
- canonical entity 流程：
  - `debug.entity_raw`
  - `debug.entity_canonical`
  - `debug.entity_used_for_graph`
- **Insight**：`supporting_chunks[].ref_index` 与摘要中 `[n]` 引用一一对应（由 `document_insight_service` 与 schema 保证；API 测试在有条目时校验 `ref_index`）。
- **知识库路径**：仅断言 `/knowledge/*`，避免与 OpenAPI UI 的 `/docs` 混淆。

### 4.7 最近一次全量结果（仓库内）

```bash
PYTHONPATH=. python3 -m pytest -v -ra
# 预期：以本地命令输出为准；用例数量会随仓库演进变化
```

---

## 5. CI 自动化

仓库已新增 GitHub Actions 工作流：`.github/workflows/tests.yml`。

- **默认（push / pull_request）**：
  - 执行 `unit + contract tests`（Hosted runner）
  - 命令：
    - `pytest -v tests/test_utils.py`
    - `pytest -v tests/test_document_loader.py tests/test_evidence_conflicts.py tests/test_friction_v3.py tests/test_multilingual_graph_query.py tests/test_person_entities.py tests/test_ppt_summary_route.py tests/test_query_pipeline_contract.py`
- **手动触发全量（workflow_dispatch）**：
  - 勾选 `run_full_stack=true`
  - 执行 `full-stack-tests`（Self-hosted runner）
  - 命令：`pytest -v -ra`

补充：

- 本地版本收尾建议额外执行：
  - `make test-contract`
  - `make test-smoke`
  - `make test-load`
  - `make test-ui`

说明：

- 全量测试依赖 Neo4j / PostgreSQL / Redis / Ollama 等服务，默认不在 GitHub Hosted 环境提供。
- 因此将完整集成与回归测试放在 self-hosted runner 手动触发，避免 PR 流水线被外部依赖阻塞。

---

## 6. 注意事项

- 集成测试依赖外部服务，若任一服务（Ollama / Neo4j / PostgreSQL / Redis）未启动，测试将失败。
- 若你在本地频繁调试，建议：
  - 先只跑单元测试（`test_utils.py`）验证安全与配置逻辑。
  - 再在后端依赖全部就绪后，运行 `test_integration.py` 做完整回归。
- 清理 fixture 是**幂等的**，即使 Neo4j / Postgres 中某些表或节点不存在，也不会导致整个测试失败（只会在控制台打印告警）。
