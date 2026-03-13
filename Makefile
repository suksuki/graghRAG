.PHONY: test test-unit test-integration clean

test:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v tests/

# 仅运行不依赖 Ollama/Neo4j/Postgres 的单元测试（CI 友好）
test-unit:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v tests/test_utils.py

# 运行需真实服务的集成测试
test-integration:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v -m integration tests/
	PYTHONPATH=$(PWD) .venv/bin/pytest -v tests/test_integration.py

clean:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
