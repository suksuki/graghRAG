"""
Person entity extraction/storage (minimal schema).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

import psycopg2

from configs.config import settings

logger = logging.getLogger(__name__)


def _conn():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )


def ensure_person_entities_table() -> None:
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS person_entities (
              id BIGSERIAL PRIMARY KEY,
              person TEXT NOT NULL,
              title TEXT NULL,
              projects JSONB NOT NULL DEFAULT '[]'::jsonb,
              file_name TEXT NOT NULL,
              chunk_id TEXT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_person_entities_unique "
            "ON person_entities(file_name, person);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_person_entities_file ON person_entities(file_name);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_person_entities_person ON person_entities(person);"
        )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_person_entities_table failed: %s", e)


def _extract_json_array(raw: str) -> List[Dict[str, Any]]:
    s = (raw or "").strip()
    if not s:
        return []
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    try:
        data = json.loads(s)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        pass
    m2 = re.search(r"\[[\s\S]*\]", s)
    if not m2:
        return []
    try:
        data = json.loads(m2.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def extract_person_entities_from_text(text: str, llm: Any, file_name: str) -> List[Dict[str, Any]]:
    t = (text or "").strip()
    if not t:
        return []
    if len(t) > 12000:
        t = t[:11999] + "…"
    prompt = (
        "从以下文档内容中提取“人员信息”，返回 JSON 数组：\n\n"
        "要求：\n"
        "- 只提取明确出现的人员\n"
        "- 每个对象包含：\n"
        "  - person（姓名）\n"
        "  - title（职位，如无则为 null）\n"
        "  - projects（负责的项目列表，如无则空数组）\n"
        "- 不要推测，不要补全\n"
        "- 只输出 JSON 数组，不要输出 markdown\n\n"
        f"文本：\n{t}\n"
    )
    try:
        raw = str(llm.complete(prompt)).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("extract_person_entities_from_text LLM failed: %s", e)
        return []
    rows = _extract_json_array(raw)
    out: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        person = str(r.get("person") or "").strip()
        if not person:
            continue
        title_val = r.get("title")
        title = None if title_val is None else str(title_val).strip() or None
        projects_val = r.get("projects")
        projects: List[str] = []
        if isinstance(projects_val, list):
            for p in projects_val:
                ps = str(p or "").strip()
                if ps:
                    projects.append(ps[:200])
        key = (file_name, person)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "person": person[:80],
                "title": title[:120] if isinstance(title, str) else None,
                "projects": projects[:20],
                "source_doc": file_name,
            }
        )
    return out


def upsert_person_entities(file_name: str, rows: List[Dict[str, Any]]) -> int:
    if not file_name or not rows:
        return 0
    ensure_person_entities_table()
    wrote = 0
    try:
        conn = _conn()
        cur = conn.cursor()
        for r in rows:
            person = str(r.get("person") or "").strip()
            if not person:
                continue
            title = r.get("title")
            if title is not None:
                title = str(title).strip() or None
            projects = r.get("projects") if isinstance(r.get("projects"), list) else []
            cur.execute(
                """
                INSERT INTO person_entities (person, title, projects, file_name)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (file_name, person)
                DO UPDATE SET
                  title = EXCLUDED.title,
                  projects = EXCLUDED.projects,
                  updated_at = NOW()
                """,
                (person, title, json.dumps(projects, ensure_ascii=False), file_name),
            )
            wrote += 1
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("upsert_person_entities failed: %s", e)
    return wrote


def fetch_person_entities(file_name: str, query_text: str, limit: int = 8) -> List[Dict[str, Any]]:
    if not file_name:
        return []
    ensure_person_entities_table()
    q = str(query_text or "").strip()
    rows: List[Dict[str, Any]] = []
    try:
        conn = _conn()
        cur = conn.cursor()
        if q:
            cur.execute(
                """
                SELECT person, title, projects, file_name
                FROM person_entities
                WHERE file_name = %s
                  AND (
                    person ILIKE %s
                    OR %s ILIKE ('%%' || person || '%%')
                  )
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (file_name, f"%{q}%", q, int(limit)),
            )
        else:
            cur.execute(
                """
                SELECT person, title, projects, file_name
                FROM person_entities
                WHERE file_name = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (file_name, int(limit)),
            )
        for person, title, projects, source_doc in cur.fetchall():
            plist = projects if isinstance(projects, list) else []
            rows.append(
                {
                    "person": str(person or ""),
                    "title": str(title) if title is not None else None,
                    "projects": [str(x) for x in plist if str(x or "").strip()],
                    "source_doc": str(source_doc or file_name),
                }
            )
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_person_entities failed: %s", e)
    return rows
