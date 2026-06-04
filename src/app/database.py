"""
PostgreSQL layer — persistent storage for AI analysis results.

Analyses are kept for 28 days (Parliament's register update cycle).
After that they are treated as stale and Claude is called again.

Gracefully degrades to a no-op when DATABASE_URL is not set or
Postgres is unreachable — behaviour is identical to uncached.

Railway: add the Postgres plugin and DATABASE_URL is injected automatically.
"""

import logging
import os

import psycopg2
from psycopg2 import pool as pg_pool

log = logging.getLogger(__name__)

ANALYSIS_MAX_AGE_DAYS = 28

_pool: pg_pool.SimpleConnectionPool | None = None


def _get_pool() -> pg_pool.SimpleConnectionPool | None:
    global _pool
    if _pool is not None:
        return _pool

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None

    # Railway (and some tools) emit postgres:// — psycopg2 needs postgresql://
    url = url.replace("postgres://", "postgresql://", 1)

    try:
        _pool = pg_pool.SimpleConnectionPool(1, 5, url)
        log.info("PostgreSQL connected")
        return _pool
    except Exception as exc:
        log.warning("PostgreSQL unavailable, DB layer disabled: %s", exc)
        return None


def ensure_tables() -> None:
    """
    Create the analyses table if it doesn't exist.
    Called once at app startup — safe to run repeatedly.
    """
    p = _get_pool()
    if not p:
        return
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    member_id      INTEGER      NOT NULL,
                    prompt_key     VARCHAR(50)  NOT NULL,
                    prompt_version INTEGER      NOT NULL,
                    result_text    TEXT         NOT NULL,
                    generated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (member_id, prompt_key)
                )
            """)
        conn.commit()
        log.info("DB: analyses table ready")
    except Exception as exc:
        log.warning("DB ensure_tables failed: %s", exc)
        conn.rollback()
    finally:
        p.putconn(conn)


def get_analysis(member_id: int, prompt_key: str, prompt_version: int) -> str | None:
    """
    Return cached result text if a fresh row exists, else None.
    A row is stale if it is older than ANALYSIS_MAX_AGE_DAYS days
    or was generated with a different prompt version.
    """
    p = _get_pool()
    if not p:
        return None
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT result_text FROM analyses
                WHERE member_id = %s
                  AND prompt_key = %s
                  AND prompt_version = %s
                  AND generated_at > NOW() - INTERVAL '28 days'
                """,
                (member_id, prompt_key, prompt_version),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:
        log.warning("DB get_analysis failed: %s", exc)
        return None
    finally:
        p.putconn(conn)


def save_analysis(
    member_id: int, prompt_key: str, prompt_version: int, result_text: str
) -> None:
    """
    Upsert an analysis result.
    If a row for this (member_id, prompt_key) already exists it is overwritten
    with the new version and a fresh timestamp.
    """
    p = _get_pool()
    if not p:
        return
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analyses
                    (member_id, prompt_key, prompt_version, result_text, generated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (member_id, prompt_key) DO UPDATE
                    SET prompt_version = EXCLUDED.prompt_version,
                        result_text    = EXCLUDED.result_text,
                        generated_at   = NOW()
                """,
                (member_id, prompt_key, prompt_version, result_text),
            )
        conn.commit()
    except Exception as exc:
        log.warning("DB save_analysis failed: %s", exc)
        conn.rollback()
    finally:
        p.putconn(conn)
