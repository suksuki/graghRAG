#!/usr/bin/env python3
"""
清空本地「图 + 向量 + 原始上传 + 摄取/图相关 Redis 键」，便于手动验收。

不执行 FLUSHDB，避免误伤同库 Celery broker 的其他键。
用法（项目根目录）:
  PYTHONPATH=. python3 scripts/reset_local_data.py
  PYTHONPATH=. python3 scripts/reset_local_data.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
import redis  # noqa: E402

from api.deps import graph_engine, vector_engine  # noqa: E402
from configs.config import settings  # noqa: E402


REDIS_PREFIXES = (
    "ingestion:",
    "graph:precompute:",
    "graph:retrieve:",
    "graph:suggestions:",
    "hub:insight:",
)


def _clear_neo4j(*, dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] Neo4j: MATCH (n) DETACH DELETE n")
        return
    with graph_engine.graph_store._driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("Neo4j: 已清空全部节点与关系。")


def _clear_pgvector(*, dry_run: bool) -> None:
    table = vector_engine.full_table_name
    if dry_run:
        print(f"[dry-run] PostgreSQL: DELETE FROM {table}")
        return
    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    print(f"PostgreSQL: 已清空向量表 {table}。")


def _clear_raw_dir(*, dry_run: bool) -> None:
    base = settings.DATA_RAW_DIR
    if not os.path.isdir(base):
        print(f"原始目录不存在，跳过: {base}")
        return
    names = [f for f in os.listdir(base) if os.path.isfile(os.path.join(base, f))]
    if dry_run:
        print(f"[dry-run] 将删除 {len(names)} 个文件于 {base}")
        return
    for fname in names:
        os.remove(os.path.join(base, fname))
    print(f"已清空原始目录 {base}（删除 {len(names)} 个文件）。")


def _clear_processed_dir(*, dry_run: bool) -> None:
    base = settings.DATA_PROCESSED_DIR
    if not os.path.isdir(base):
        return
    names = [f for f in os.listdir(base) if os.path.isfile(os.path.join(base, f))]
    if dry_run:
        print(f"[dry-run] 将删除 {len(names)} 个文件于 {base}")
        return
    for fname in names:
        os.remove(os.path.join(base, fname))
    if names:
        print(f"已清空 processed 目录 {base}（删除 {len(names)} 个文件）。")


def _clear_redis_keys(*, dry_run: bool) -> int:
    deleted = 0
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
    except Exception as e:  # noqa: BLE001
        print(f"Redis: 跳过（无法连接: {e}）")
        return 0
    for prefix in REDIS_PREFIXES:
        pattern = f"{prefix}*"
        keys = list(r.scan_iter(match=pattern, count=500))
        if dry_run:
            print(f"[dry-run] Redis SCAN {pattern!r} → {len(keys)} keys")
            continue
        if keys:
            r.delete(*keys)
        deleted += len(keys)
    if not dry_run:
        print(f"Redis: 已删除 {deleted} 个键（前缀: {', '.join(REDIS_PREFIXES)}）。")
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset local GraphRAG storage for manual testing.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的操作，不写库",
    )
    args = parser.parse_args()

    print("=== GraphRAG 本地数据重置 ===")
    if args.dry_run:
        print("（dry-run 模式）\n")

    _clear_neo4j(dry_run=args.dry_run)
    _clear_pgvector(dry_run=args.dry_run)
    _clear_raw_dir(dry_run=args.dry_run)
    _clear_processed_dir(dry_run=args.dry_run)
    _clear_redis_keys(dry_run=args.dry_run)

    print("\n说明: 问答全量缓存键格式为「查询|语言|图版本」，未按模式批量删除；")
    print("若仍命中旧回答，可重启 API 进程或等待 TTL（默认约 1h），或在独占 Redis DB 时自行 FLUSHDB。")
    print("完成。可启动 API 后重新上传文档做手动测试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
