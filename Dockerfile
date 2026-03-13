# GraphRAG Platform - API 服务
FROM python:3.10-slim

WORKDIR /app

# 系统依赖（部分 LlamaIndex 读文件需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY configs/ ./configs/
COPY core/ ./core/

# 数据目录（挂载卷）
ENV DATA_RAW_DIR=/app/data/raw
RUN mkdir -p /app/data/raw /app/data/processed

# 可选：通过环境变量指定 .env 路径，不指定则使用 /app/.env
ENV GRAPHRAG_ENV_FILE=/app/.env

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
