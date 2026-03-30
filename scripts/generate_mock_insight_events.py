#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

import psycopg2
from psycopg2.extras import Json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from configs.config import settings


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def gen_query_len(qtype: str) -> int:
    if qtype == "A":
        return random.randint(14, 40)
    if qtype == "B":
        return random.randint(10, 32)
    return random.randint(8, 24)


def gen_answer_len(qtype: str) -> int:
    if qtype == "A":
        return random.randint(120, 260)
    if qtype == "B":
        return random.randint(100, 220)
    return random.randint(70, 180)


def build_sessions() -> List[Tuple[str, str, int]]:
    # 20 sessions: A 8, B 8, C 4
    sessions: List[Tuple[str, str, int]] = []
    idx = 1
    for _ in range(8):
        qn = 3 if random.random() < 0.75 else 4
        sessions.append((f"s_mock_A_{idx:02d}", "A", qn))
        idx += 1
    idx = 1
    for _ in range(8):
        qn = 3 if random.random() < 0.85 else 4
        sessions.append((f"s_mock_B_{idx:02d}", "B", qn))
        idx += 1
    idx = 1
    for _ in range(4):
        sessions.append((f"s_mock_C_{idx:02d}", "C", 1))
        idx += 1
    random.shuffle(sessions)
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260330)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    random.seed(args.seed)
    now = datetime.now(timezone.utc)
    sessions = build_sessions()

    events: List[Dict[str, Any]] = []
    base_start = now - timedelta(hours=6)

    for i, (sid, qtype, qcount) in enumerate(sessions):
        session_start = base_start + timedelta(seconds=random.randint(0, 18000))
        doc_id = random.choice(
            ["org_structure.pptx", "team_roles.pptx", "ops_handbook.pptx"]
        )
        events.append(
            {
                "event": "select_doc_scope",
                "ts": ms(session_start),
                "session_id": sid,
                "doc_id": doc_id,
                "payload": {
                    "doc_id": doc_id,
                },
            }
        )
        q_times: List[datetime] = []
        t = session_start
        for qi in range(qcount):
            if qi == 0:
                q_times.append(t)
            else:
                t = t + timedelta(seconds=random.randint(5, 20))
                q_times.append(t)

        prev_len = None
        for qi, qt in enumerate(q_times):
            q_len = gen_query_len(qtype)
            a_len = gen_answer_len(qtype)
            contains_not_found = random.random() < 0.12

            events.append(
                {
                    "event": "query_with_doc_scope",
                    "ts": ms(qt),
                    "session_id": sid,
                    "doc_id": doc_id,
                    "payload": {
                        "query_len": q_len,
                    },
                }
            )

            events.append(
                {
                    "event": "query_submitted",
                    "ts": ms(qt),
                    "session_id": sid,
                    "doc_id": doc_id,
                    "payload": {
                        "query_len": q_len,
                        "has_doc_scope": True,
                        "doc_id": doc_id,
                    },
                }
            )

            at = qt + timedelta(seconds=random.randint(1, 4))
            events.append(
                {
                    "event": "answer_generated",
                    "ts": ms(at),
                    "session_id": sid,
                    "doc_id": doc_id,
                    "payload": {
                        "source": "rag",
                        "answer_len": a_len,
                        "contains_not_found": contains_not_found,
                        "semantic_expansion_used": random.random() < 0.15,
                    },
                }
            )

            if random.random() < 0.18:
                ct = at + timedelta(seconds=random.randint(1, 6))
                events.append(
                    {
                        "event": "click_reference",
                        "ts": ms(ct),
                        "session_id": sid,
                        "doc_id": doc_id,
                        "payload": {
                            "ref_id": str(random.randint(1, 4)),
                            "position": "summary",
                        },
                    }
                )

            if qi > 0 and prev_len is not None:
                events.append(
                    {
                        "event": "follow_up_query",
                        "ts": ms(qt),
                        "session_id": sid,
                        "doc_id": doc_id,
                        "payload": {
                            "prev_query_len": prev_len,
                            "new_query_len": q_len,
                        },
                    }
                )

            prev_len = q_len

    events.sort(key=lambda x: (x["ts"], x["session_id"], x["event"]))

    if args.dry_run:
        print(json.dumps({"events": len(events), "sessions": len(sessions)}, ensure_ascii=False))
        return

    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO insight_events (event, ts, session_id, doc_id, insight_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        [
            (
                e["event"],
                int(e["ts"]),
                e["session_id"],
                e["doc_id"],
                None,
                Json(e["payload"]),
            )
            for e in events
        ],
    )
    conn.commit()
    cur.close()
    conn.close()

    print(
        json.dumps(
            {
                "inserted_events": len(events),
                "inserted_sessions": len(sessions),
                "seed": args.seed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
