import os

import psycopg2
import pytest

from configs.config import settings
from api.deps import graph_engine, vector_engine


# 标记需真实 Ollama/Neo4j/Postgres 的测试，CI 可仅运行单元测试: pytest -m "not integration"
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
