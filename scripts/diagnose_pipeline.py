#!/usr/bin/env python3
"""
一键诊断：文件 → 向量 → DI(di_*) → Entity 图谱。
用法（项目根目录）:
  python3 scripts/diagnose_pipeline.py
  python3 scripts/diagnose_pipeline.py --json
（脚本会自动把项目根加入 sys.path，一般无需再设 PYTHONPATH。）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import httpx
except ImportError:
    httpx = None

import psycopg2

from configs.config import settings
from core.graph_engine import GraphEngine
from core.vector_store import _get_table_name
from api.utils import is_allowed_extension


def _eligible_file_count() -> int:
    base = settings.DATA_RAW_DIR
    if not base or not __import__("os").path.isdir(base):
        return 0
    import os

    n = 0
    for fn in os.listdir(base):
        path = os.path.join(base, fn)
        if os.path.isfile(path) and is_allowed_extension(fn):
            n += 1
    return n


def _vector_table_name() -> str:
    return f"data_{_get_table_name()}"


def _pg_vector_stats() -> Dict[str, Any]:
    table = _vector_table_name()
    out: Dict[str, Any] = {"table": table, "row_count": None, "error": None, "di_sample": None}
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        cur = conn.cursor()
        cur.execute(
            """
            SELECT EXISTS (
              SELECT FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = %s
            )
            """,
            (table,),
        )
        exists = cur.fetchone()[0]
        if not exists:
            out["error"] = f"表 public.{table} 不存在（检查 EMBEDDING_MODEL 与是否已摄取）"
            conn.close()
            return out
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        out["row_count"] = int(cur.fetchone()[0])
        # 抽样 di_*：metadata / metadata_ 列名因 LlamaIndex 版本而异
        for col in ("metadata_", "metadata"):
            try:
                cur.execute(
                    f"""
                    SELECT {col}::text FROM {table}
                    WHERE ({col}::text ILIKE %s OR {col}::text ILIKE %s)
                    LIMIT 3
                    """,
                    ("%di_summary%", "%di_keywords%"),
                )
                rows = cur.fetchall()
                if rows:
                    out["di_sample"] = {"column": col, "rows_found": len(rows)}
                    break
            except Exception as e:  # noqa: BLE001
                out["di_sample"] = {"column": col, "error": str(e)}
        conn.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _neo4j_stats() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "total_nodes": None,
        "entity_count": None,
        "ingested_file_markers": None,
        "error": None,
    }
    try:
        eng = GraphEngine()
        with eng.graph_store._driver.session() as session:
            out["total_nodes"] = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            out["entity_count"] = session.run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
            out["ingested_file_markers"] = session.run(
                "MATCH (f:IngestedFile) RETURN count(f) AS c"
            ).single()["c"]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _ollama_tags() -> Dict[str, Any]:
    out: Dict[str, Any] = {"url": settings.OLLAMA_BASE_URL.rstrip("/"), "ok": False, "has_embedding_model": None, "error": None}
    if httpx is None:
        out["error"] = "httpx 未安装，跳过 Ollama 探测（pip install httpx）"
        return out
    try:
        r = httpx.get(f"{out['url']}/api/tags", timeout=8.0)
        r.raise_for_status()
        data = r.json()
        names: List[str] = []
        for m in data.get("models") or []:
            if isinstance(m, dict) and m.get("name"):
                names.append(m["name"])
        out["ok"] = True
        emb = settings.EMBEDDING_MODEL
        out["has_embedding_model"] = any(
            n == emb or n.startswith(emb.split(":")[0] + ":") for n in names
        )
        out["models_sample"] = names[:12]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _infer_root_cause(
    files: int,
    vec_rows: Optional[int],
    vec_err: Optional[str],
    di_hint: Any,
    entities: Optional[int],
    ollama_emb: Optional[bool],
) -> List[str]:
    hints: List[str] = []
    if files == 0:
        hints.append("数据目录下没有可摄取文件（或 DATA_RAW_DIR 为空）。")
        return hints
    if vec_err:
        hints.append(f"向量库：{vec_err}")
        if "不存在" in vec_err or "does not exist" in vec_err.lower():
            hints.append("可能尚未成功写入向量，或 EMBEDDING_MODEL 与当前表名不一致。")
        return hints
    if vec_rows == 0:
        hints.append("向量表行数为 0：摄取未写入向量，或写入了别的模型表。")
        if ollama_emb is False:
            hints.append("Ollama 中可能缺少配置的 EMBEDDING_MODEL，请 ollama pull 对应嵌入模型。")
        elif ollama_emb is None and httpx:
            hints.append("无法连接 Ollama，请检查 OLLAMA_BASE_URL 与服务是否启动。")
        return hints
    if not di_hint or (isinstance(di_hint, dict) and "rows_found" not in di_hint):
        hints.append("向量有数据，但未在 metadata 中检出 di_summary/di_keywords：Document Intelligence 可能未执行或失败。")
        return hints
    if entities == 0:
        hints.append("DI 已有迹象，但 Neo4j 无 Entity：图抽取未产出或文档不易抽实体。")
        return hints
    hints.append("各层均有数据；若 Insight 仍空，检查 corpus 聚合语言与缓存，或 di 字段是否为空字符串。")
    return hints


def run_diagnosis() -> Dict[str, Any]:
    files = _eligible_file_count()
    v = _pg_vector_stats()
    g = _neo4j_stats()
    o = _ollama_tags()

    vec_rows = v.get("row_count")
    vec_err = v.get("error")
    di_hint = v.get("di_sample")
    entities = g.get("entity_count")

    ollama_emb = o.get("has_embedding_model") if o.get("ok") else None
    if o.get("error") and not o.get("ok"):
        ollama_emb = None

    causes = _infer_root_cause(files, vec_rows, vec_err, di_hint, entities, ollama_emb)

    return {
        "data_raw_dir": settings.DATA_RAW_DIR,
        "eligible_files": files,
        "vector": v,
        "neo4j": g,
        "ollama": o,
        "likely_causes": causes,
    }


def _print_report(d: Dict[str, Any]) -> None:
    print("=== GraphRAG 摄取链路诊断 ===\n")
    print(f"DATA_RAW_DIR: {d['data_raw_dir']}")
    print(f"可摄取文件数: {d['eligible_files']}")
    print()
    print("--- 向量 (PGVector) ---")
    v = d["vector"]
    print(f"  表: public.{v['table']}")
    if v.get("error"):
        print(f"  ✘ {v['error']}")
    else:
        print(f"  行数: {v['row_count']}")
        if v.get("di_sample"):
            print(f"  DI 抽样: {v['di_sample']}")
        else:
            print("  DI 抽样: 未检出 di_summary / di_keywords（可能未跑 DI）")
    print()
    print("--- Neo4j ---")
    g = d["neo4j"]
    if g.get("error"):
        print(f"  ✘ {g['error']}")
    else:
        print(f"  总节点: {g['total_nodes']}")
        print(f"  Entity: {g['entity_count']}")
        print(f"  IngestedFile 标记: {g['ingested_file_markers']}")
    print()
    print("--- Ollama（嵌入） ---")
    o = d["ollama"]
    print(f"  URL: {o['url']}")
    if o.get("error"):
        print(f"  ? {o['error']}")
    else:
        print(f"  可达: {'是' if o.get('ok') else '否'}")
        print(f"  配置 EMBEDDING_MODEL={settings.EMBEDDING_MODEL!r} 是否在列表: {o.get('has_embedding_model')}")
        if o.get("models_sample"):
            print(f"  模型示例: {', '.join(o['models_sample'])}")
    print()
    print("--- 综合判断 ---")
    for line in d["likely_causes"]:
        print(f"  → {line}")
    print()
    print("口诀: Insight 空看 di_*；Graph 统计看 Entity；两者都空先看向量。")


def main() -> int:
    parser = argparse.ArgumentParser(description="诊断摄取链路：文件 / 向量 / DI / 图")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()
    d = run_diagnosis()
    if args.json:
        # JSON 可序列化
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    else:
        _print_report(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
