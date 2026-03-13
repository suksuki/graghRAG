#!/bin/bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --loop asyncio
