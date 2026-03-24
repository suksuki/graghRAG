#!/usr/bin/env python3
"""
一次性回填：为缺少 kg_source / kg_confidence 的关系打上 legacy / 1.0，
与查询层 coalesce 语义一致，便于统计与健康度面板。

用法（项目根）:
  python3 scripts/backfill_kg_rel_provenance.py --dry-run
  python3 scripts/backfill_kg_rel_provenance.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.graph_engine import GraphEngine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill r.kg_source / r.kg_confidence on Neo4j")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计待更新条数，不写库",
    )
    args = parser.parse_args()

    eng = GraphEngine()
    driver = eng.graph_store._driver  # type: ignore[attr-defined]

    count_cy = """
    MATCH ()-[r]->()
    WHERE r.kg_source IS NULL OR r.kg_confidence IS NULL
    RETURN count(r) AS n
    """
    set_cy = """
    MATCH ()-[r]->()
    WHERE r.kg_source IS NULL OR r.kg_confidence IS NULL
    SET r.kg_source = coalesce(r.kg_source, 'legacy'),
        r.kg_confidence = coalesce(r.kg_confidence, 1.0)
    RETURN count(r) AS n
    """

    with driver.session() as session:
        pending = session.run(count_cy).single()["n"]
        print(f"待处理关系数: {pending}")
        if args.dry_run:
            return 0
        updated = session.run(set_cy).single()["n"]
        print(f"已更新关系数: {updated}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
