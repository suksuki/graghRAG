## 测试体系说明（GraphRAG Platform）

本篇文档介绍 GraphRAG 平台的自动化测试体系，包括单元测试、集成测试以及如何保持测试环境干净。

---

## 1. 测试类型概览

目录：`tests/`

- **单元测试（unit tests）**
  - 文件：`tests/test_utils.py`
  - 重点：
    - `api.utils` 中的安全函数（文件名清洗、路径解析、白名单等）。
    - 不依赖外部服务，运行速度快。

- **引擎初始化与集成（engine tests）**
  - 文件：`tests/test_engines.py`
  - 标记：`@pytest.mark.integration`
  - 重点：
    - `GraphEngine`、`VectorEngine`、`SMEIngestor` 的初始化。
    - 基于真实 Neo4j / PostgreSQL / Ollama 的基础集成。

- **API 测试（API tests）**
  - 文件：`tests/test_api.py`
  - 部分用例标记为 `integration`：
    - `test_ollama_direct_connection`
    - `test_api_settings_test_endpoint`
  - 重点：
    - FastAPI 路由层行为。
    - 设置接口（`/settings` / `/settings/test` / `/settings/update`）。

- **端到端回归测试（integration regression）**
  - 文件：`tests/test_integration.py`
  - 用例：`test_full_ingestion_and_query_flow`
  - 重点：
    - 覆盖完整流程：**上传 → 摄取 → 查询**。
    - 验证在真实 Neo4j / PostgreSQL / Ollama 环境下，GraphRAG 查询结果正确。

---

## 2. 清理环境的自动化 Fixture

位置：`tests/conftest.py`

```python
import os

import psycopg2
import pytest

from configs.config import settings
from api.deps import graph_engine, vector_engine


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration (needs Ollama/Neo4j/Postgres)")


@pytest.fixture(autouse=True)
def clean_test_environment():
    """
    在每个测试前清理图数据库、向量库以及原始文件目录，避免历史数据干扰回归测试。
    """
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

---

## 5. 注意事项

- 集成测试依赖外部服务，若任一服务（Ollama / Neo4j / PostgreSQL / Redis）未启动，测试将失败。
- 若你在本地频繁调试，建议：
  - 先只跑单元测试（`test_utils.py`）验证安全与配置逻辑。
  - 再在后端依赖全部就绪后，运行 `test_integration.py` 做完整回归。
- 清理 fixture 是**幂等的**，即使 Neo4j / Postgres 中某些表或节点不存在，也不会导致整个测试失败（只会在控制台打印告警）。

