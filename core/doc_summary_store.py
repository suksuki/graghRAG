"""
Minimal storage for document-level summaries.
"""

from __future__ import annotations

import logging
from typing import Optional

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


def ensure_doc_summaries_table() -> None:
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_summaries (
              id BIGSERIAL PRIMARY KEY,
              file_name TEXT NOT NULL UNIQUE,
              summary_text TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_doc_summaries_file_name ON doc_summaries(file_name);"
        )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_doc_summaries_table failed: %s", e)


def upsert_doc_summary(file_name: str, summary_text: str) -> bool:
    fn = str(file_name or "").strip()
    st = str(summary_text or "").strip()
    if not fn or not st:
        return False
    ensure_doc_summaries_table()
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO doc_summaries (file_name, summary_text)
            VALUES (%s, %s)
            ON CONFLICT (file_name)
            DO UPDATE SET
              summary_text = EXCLUDED.summary_text,
              updated_at = NOW()
            """,
            (fn, st),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("upsert_doc_summary failed: %s", e)
        return False


def fetch_doc_summary(file_name: str) -> Optional[str]:
    fn = str(file_name or "").strip()
    if not fn:
        return None
    ensure_doc_summaries_table()
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT summary_text
            FROM doc_summaries
            WHERE file_name = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (fn,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return str(row[0] or "").strip() or None
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_doc_summary failed: %s", e)
        return None
