#!/bin/bash
set -e

cd /opt/graphrag-platform
export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "[restart_all] Stopping uvicorn..."
pkill -f "uvicorn api.main:app" || true

echo "[restart_all] Stopping celery worker..."
pkill -f "celery.*ingestion_worker" || true

echo "[restart_all] Starting uvicorn..."
nohup .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --loop asyncio > api_runtime.log 2>&1 &

echo "[restart_all] Starting celery worker..."
nohup .venv/bin/celery -A workers.celery_worker.celery_app worker -l info > celery_worker.log 2>&1 &

echo "[restart_all] Done."

