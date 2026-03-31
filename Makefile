.PHONY: test test-unit test-contract test-integration test-ui test-smoke test-load release-check clean

test:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v tests/

# 仅运行不依赖 Ollama/Neo4j/Postgres 的单元测试（CI 友好）
test-unit:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v tests/test_utils.py

# 运行快速契约 / 回归测试（不依赖完整外部栈）
test-contract:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v \
		tests/test_utils.py \
		tests/test_document_loader.py \
		tests/test_evidence_conflicts.py \
		tests/test_friction_v3.py \
		tests/test_multilingual_graph_query.py \
		tests/test_person_entities.py \
		tests/test_ppt_summary_route.py \
		tests/test_query_pipeline_contract.py

# 运行需真实服务的集成测试
test-integration:
	PYTHONPATH=$(PWD) .venv/bin/pytest -v -m integration tests/
	PYTHONPATH=$(PWD) .venv/bin/pytest -v tests/test_integration.py

test-ui:
	cd scripts && PATH="$$HOME/.nvm/versions/node/v22.22.1/bin:$$PATH" npm run ui:insight-suite

test-smoke:
	PYTHONPATH=$(PWD) .venv/bin/python scripts/release_smoke.py

test-load:
	PYTHONPATH=$(PWD) .venv/bin/python scripts/load_test_api.py

release-check:
	$(MAKE) test-unit
	$(MAKE) test-contract
	$(MAKE) test-smoke

clean:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
