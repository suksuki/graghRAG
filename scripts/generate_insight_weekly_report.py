#!/usr/bin/env python3
"""
Generate weekly insight decision report from insight_events.

Usage:
  python scripts/generate_insight_weekly_report.py --write
  python scripts/generate_insight_weekly_report.py --days 7
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from configs.config import settings

BOARD_PATH = Path("docs/INSIGHT_DECISION_BOARD.md")
AUTO_START = "<!-- AUTO_WEEKLY_REPORT:START -->"
AUTO_END = "<!-- AUTO_WEEKLY_REPORT:END -->"
REAL_SESSION_SQL = "session_id NOT LIKE 's_test%%' AND session_id NOT LIKE 's_mock%%'"


@dataclass
class WeeklyStats:
    total_queries: int
    total_sessions: int
    real_user_ratio: float
    ready_for_decision: bool
    click_rate: float
    follow_up_rate: float
    not_found_rate: float
    semantic_expansion_rate: float
    doc_scope_usage_rate: float
    doc_scope_conversion_rate: float
    click_rate_scoped: float
    click_rate_global: float
    sampled_sessions: List[Dict[str, Any]]


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except Exception:
        return 0.0


def _i(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(v)
    except Exception:
        return 0


def _fetch_stats(days: int) -> WeeklyStats:
    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
    cur = conn.cursor()

    time_filter = f"to_timestamp(ts / 1000.0) >= now() - interval '{int(days)} days'"

    cur.execute(
        f"""
        SELECT
          COUNT(*) FILTER (
            WHERE event='query_submitted'
              AND {REAL_SESSION_SQL}
          ) AS total_queries,
          COUNT(DISTINCT session_id) FILTER (
            WHERE event='query_submitted'
              AND {REAL_SESSION_SQL}
          ) AS total_sessions,
          COUNT(DISTINCT session_id) FILTER (
            WHERE event='query_submitted'
              AND {REAL_SESSION_SQL}
          ) * 1.0
            / NULLIF(COUNT(DISTINCT session_id) FILTER (WHERE event='query_submitted'), 0)
            AS real_user_ratio
        FROM insight_events
        WHERE {time_filter};
        """
    )
    tq, ts, rur = cur.fetchone()
    total_queries = _i(tq)
    total_sessions = _i(ts)
    real_user_ratio = _f(rur)
    ready_for_decision = (
        total_queries >= 50 and total_sessions >= 20 and real_user_ratio >= 0.8
    )

    cur.execute(
        f"""
        WITH filtered AS (
          SELECT *
          FROM insight_events
          WHERE {time_filter}
            AND session_id IS NOT NULL
            AND session_id <> ''
            AND {REAL_SESSION_SQL}
        )
        SELECT
          COUNT(*) FILTER (WHERE event='click_reference') * 1.0
            / NULLIF(COUNT(*) FILTER (WHERE event='query_submitted'), 0) AS click_rate,
          (
            WITH q AS (
              SELECT session_id, to_timestamp(ts / 1000.0) AS t
              FROM filtered
              WHERE event='query_submitted'
            ),
            pairs AS (
              SELECT q1.session_id
              FROM q q1 JOIN q q2
                ON q1.session_id=q2.session_id
               AND q2.t>q1.t
               AND q2.t<=q1.t + interval '30 seconds'
            )
            SELECT COUNT(DISTINCT session_id) * 1.0
              / NULLIF((SELECT COUNT(DISTINCT session_id) FROM q), 0)
            FROM pairs
          ) AS follow_up_rate,
          COUNT(*) FILTER (
            WHERE event='answer_generated' AND payload->>'contains_not_found'='true'
          ) * 1.0 / NULLIF(COUNT(*) FILTER (WHERE event='answer_generated'), 0) AS not_found_rate,
          COUNT(*) FILTER (
            WHERE event='answer_generated' AND payload->>'semantic_expansion_used'='true'
          ) * 1.0 / NULLIF(COUNT(*) FILTER (WHERE event='answer_generated'), 0) AS semantic_expansion_rate
        FROM filtered;
        """
    )
    click_rate, follow_up_rate, not_found_rate, semantic_expansion_rate = cur.fetchone()

    cur.execute(
        f"""
        WITH filtered AS (
          SELECT *
          FROM insight_events
          WHERE {time_filter}
            AND session_id IS NOT NULL
            AND session_id <> ''
            AND {REAL_SESSION_SQL}
        ),
        selections AS (
          SELECT
            session_id,
            doc_id,
            ts,
            LEAD(ts) OVER (PARTITION BY session_id ORDER BY ts ASC) AS next_select_ts
          FROM filtered
          WHERE event = 'select_doc_scope'
        ),
        converted_selections AS (
          SELECT COUNT(*) AS converted_count
          FROM selections s
          WHERE EXISTS (
            SELECT 1
            FROM filtered q
            WHERE q.event = 'query_with_doc_scope'
              AND q.session_id = s.session_id
              AND COALESCE(q.doc_id, '') = COALESCE(s.doc_id, '')
              AND q.ts > s.ts
              AND (s.next_select_ts IS NULL OR q.ts < s.next_select_ts)
          )
        )
        SELECT
          COUNT(*) FILTER (WHERE event = 'query_with_doc_scope') * 1.0
          / NULLIF(COUNT(*) FILTER (WHERE event = 'query_submitted'), 0) AS doc_scope_usage_rate,
          (SELECT converted_count * 1.0 FROM converted_selections)
          / NULLIF(COUNT(*) FILTER (WHERE event = 'select_doc_scope'), 0) AS doc_scope_conversion_rate
        FROM filtered;
        """
    )
    doc_scope_usage_rate, doc_scope_conversion_rate = cur.fetchone()

    cur.execute(
        f"""
        WITH filtered AS (
          SELECT *
          FROM insight_events
          WHERE {time_filter}
            AND session_id IS NOT NULL
            AND session_id <> ''
            AND {REAL_SESSION_SQL}
        ),
        query_events AS (
          SELECT
            session_id,
            ts,
            CASE
              WHEN event = 'query_with_doc_scope' THEN true
              WHEN event = 'query_submitted' AND (payload->>'has_doc_scope') = 'true' THEN true
              ELSE false
            END AS is_scoped
          FROM filtered
          WHERE event IN ('query_submitted', 'query_with_doc_scope')
        ),
        queries AS (
          SELECT
            session_id,
            ts AS query_ts,
            BOOL_OR(is_scoped) AS is_scoped,
            LEAD(ts) OVER (PARTITION BY session_id ORDER BY ts ASC) AS next_query_ts
          FROM query_events
          GROUP BY session_id, ts
        ),
        attributed AS (
          SELECT
            q.session_id,
            q.query_ts,
            q.is_scoped,
            EXISTS (
              SELECT 1
              FROM filtered c
              WHERE c.event = 'click_reference'
                AND c.session_id = q.session_id
                AND c.ts > q.query_ts
                AND (q.next_query_ts IS NULL OR c.ts < q.next_query_ts)
            ) AS clicked
          FROM queries q
        )
        SELECT
          COUNT(*) FILTER (WHERE is_scoped AND clicked) * 1.0
            / NULLIF(COUNT(*) FILTER (WHERE is_scoped), 0) AS click_rate_scoped,
          COUNT(*) FILTER (WHERE NOT is_scoped AND clicked) * 1.0
            / NULLIF(COUNT(*) FILTER (WHERE NOT is_scoped), 0) AS click_rate_global
        FROM attributed;
        """
    )
    click_rate_scoped, click_rate_global = cur.fetchone()

    cur.execute(
        f"""
        WITH base AS (
          SELECT session_id, max(ts) AS last_ts
          FROM insight_events
          WHERE session_id IS NOT NULL
            AND session_id <> ''
            AND {REAL_SESSION_SQL}
            AND {time_filter}
          GROUP BY session_id
        ),
        q AS (
          SELECT session_id, ts,
                 payload->>'query_len' AS query_len,
                 row_number() OVER (PARTITION BY session_id ORDER BY ts ASC) AS rn
          FROM insight_events
          WHERE event='query_submitted' AND {time_filter}
        ),
        q1 AS (
          SELECT session_id, ts AS q1_ts, query_len
          FROM q WHERE rn=1
        ),
        q2 AS (
          SELECT x.session_id, x.query_len
          FROM (
            SELECT q1.session_id, q.query_len,
                   row_number() OVER (PARTITION BY q1.session_id ORDER BY q.ts ASC) AS rn2
            FROM q1
            JOIN q ON q.session_id=q1.session_id
                  AND q.ts>q1.q1_ts
                  AND q.ts<=q1.q1_ts + 30000
          ) x
          WHERE x.rn2=1
        ),
        a1 AS (
          SELECT DISTINCT ON (session_id) session_id, payload->>'answer_len' AS answer_len
          FROM insight_events
          WHERE event='answer_generated' AND {time_filter}
          ORDER BY session_id, ts ASC
        ),
        c AS (
          SELECT DISTINCT session_id
          FROM insight_events
          WHERE event='click_reference' AND {time_filter}
        )
        SELECT b.session_id, q1.query_len, a1.answer_len,
               CASE WHEN c.session_id IS NULL THEN 'no' ELSE 'yes' END AS click,
               q2.query_len AS q2_len
        FROM base b
        JOIN q1 ON q1.session_id=b.session_id
        LEFT JOIN a1 ON a1.session_id=b.session_id
        LEFT JOIN q2 ON q2.session_id=b.session_id
        LEFT JOIN c ON c.session_id=b.session_id
        ORDER BY b.last_ts DESC
        LIMIT 5;
        """
    )
    sampled = []
    for sid, q1_len, a1_len, click, q2_len in cur.fetchall():
        sampled.append(
            {
                "session_id": sid,
                "path": f"query_len={q1_len or 'N/A'} -> answer_len={a1_len or 'N/A'} -> click={click} -> q2_len={q2_len or 'none'}",
            }
        )

    cur.close()
    conn.close()

    return WeeklyStats(
        total_queries=total_queries,
        total_sessions=total_sessions,
        real_user_ratio=real_user_ratio,
        ready_for_decision=ready_for_decision,
        click_rate=_f(click_rate),
        follow_up_rate=_f(follow_up_rate),
        not_found_rate=_f(not_found_rate),
        semantic_expansion_rate=_f(semantic_expansion_rate),
        doc_scope_usage_rate=_f(doc_scope_usage_rate),
        doc_scope_conversion_rate=_f(doc_scope_conversion_rate),
        click_rate_scoped=_f(click_rate_scoped),
        click_rate_global=_f(click_rate_global),
        sampled_sessions=sampled,
    )


def _auto_block(stats: WeeklyStats, days: int) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    sessions_text = "\n".join(
        [f"- Session #{i+1}: `{s['path']}`" for i, s in enumerate(stats.sampled_sessions)]
    )
    if not sessions_text:
        sessions_text = "- 无样本"

    payload = {
        "total_queries": stats.total_queries,
        "total_sessions": stats.total_sessions,
        "real_user_ratio": stats.real_user_ratio,
        "ready_for_decision": stats.ready_for_decision,
        "click_rate": stats.click_rate,
        "follow_up_rate": stats.follow_up_rate,
        "not_found_rate": stats.not_found_rate,
        "semantic_expansion_rate": stats.semantic_expansion_rate,
    }

    return (
        f"{AUTO_START}\n"
        f"## 自动周报（最近 {days} 天）\n\n"
        f"- 生成日期：`{today}`\n"
        f"- 样本量（session）：`{stats.total_sessions}`\n"
        f"- 采样门槛：`query_submitted>=50 && session>=20 && real_user_ratio>=0.8`\n"
        f"- 就绪状态：`{str(stats.ready_for_decision).lower()}`\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"### 核心指标\n"
        f"- Doc Scope 使用率：`{stats.doc_scope_usage_rate:.4f}`\n"
        f"- Scope 选择后转化率（select -> scoped query）：`{stats.doc_scope_conversion_rate:.4f}`\n"
        f"- scoped 查询窗口点击率：`{stats.click_rate_scoped:.4f}`\n"
        f"- global 查询窗口点击率：`{stats.click_rate_global:.4f}`\n\n"
        f"### Session 行为路径（5 条）\n"
        f"{sessions_text}\n"
        f"{AUTO_END}\n"
    )


def _write_board(block: str) -> None:
    content = BOARD_PATH.read_text(encoding="utf-8") if BOARD_PATH.exists() else ""
    if AUTO_START in content and AUTO_END in content:
        start = content.index(AUTO_START)
        end = content.index(AUTO_END) + len(AUTO_END)
        updated = content[:start] + block.rstrip() + content[end:]
    else:
        updated = content.rstrip() + "\n\n" + block
    BOARD_PATH.write_text(updated + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    stats = _fetch_stats(args.days)
    generated_at = datetime.now(timezone.utc).isoformat()
    result = {
        "generated_at": generated_at,
        "total_queries": stats.total_queries,
        "total_sessions": stats.total_sessions,
        "real_user_ratio": stats.real_user_ratio,
        "ready_for_decision": stats.ready_for_decision,
        "click_rate": stats.click_rate,
        "follow_up_rate": stats.follow_up_rate,
        "not_found_rate": stats.not_found_rate,
        "semantic_expansion_rate": stats.semantic_expansion_rate,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.write:
        block = _auto_block(stats, args.days)
        _write_board(block)
        print(f"written: {BOARD_PATH}")


if __name__ == "__main__":
    main()
