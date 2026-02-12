import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable

DB_PATH = os.getenv("DB_PATH", "/Users/sugamgandhi/Desktop/stock_news/data/news.db")


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


@contextmanager
def get_conn():
    ensure_parent_dir(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_columns(conn: sqlite3.Connection, table_name: str, column_defs: Iterable[str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_def in column_defs:
        column_name = column_def.split()[0]
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")


def init_db(schema_path: str = "/Users/sugamgandhi/Desktop/stock_news/db/schema.sql") -> None:
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_conn() as conn:
        conn.executescript(schema_sql)
        # Backward-compatible evolution for local dev DBs created before hardening.
        ensure_columns(
            conn,
            "sources",
            [
                "last_polled_at TEXT",
                "last_success_at TEXT",
                "last_error_at TEXT",
                "last_error_message TEXT",
                "consecutive_failures INTEGER NOT NULL DEFAULT 0",
                "last_entries_seen INTEGER NOT NULL DEFAULT 0",
                "last_inserted INTEGER NOT NULL DEFAULT 0",
                "last_updated_count INTEGER NOT NULL DEFAULT 0",
                "last_duration_ms INTEGER NOT NULL DEFAULT 0",
            ],
        )
        # Backfill FTS index for rows that existed before FTS triggers were added.
        conn.execute(
            """
            INSERT INTO articles_fts(rowid, title, summary)
            SELECT a.id, a.title, a.summary
            FROM articles a
            WHERE NOT EXISTS (
                SELECT 1
                FROM articles_fts f
                WHERE f.rowid = a.id
            )
            """
        )
