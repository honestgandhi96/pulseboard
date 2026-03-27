import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = os.getenv("DB_PATH", "/Users/sugamgandhi/Desktop/stock_news/data/news.db")
ROOT_DIR = Path(__file__).resolve().parents[3]


def is_postgres() -> bool:
    return bool(DATABASE_URL)


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def adapt_sql(sql: str) -> str:
    if not is_postgres():
        return sql
    return sql.replace("?", "%s")


def sql_now() -> str:
    return "CURRENT_TIMESTAMP" if is_postgres() else "datetime('now')"


def dictify_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


@contextmanager
def get_conn():
    if is_postgres():
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
        return

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


def execute(conn: Any, sql: str, params: Sequence[Any] | None = None) -> Any:
    return conn.execute(adapt_sql(sql), tuple(params or ()))


def query_one(conn: Any, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    row = execute(conn, sql, params).fetchone()
    return dict(row) if row else None


def query_all(conn: Any, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    return dictify_rows(execute(conn, sql, params).fetchall())


def ensure_columns(conn: sqlite3.Connection, table_name: str, column_defs: Iterable[str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_def in column_defs:
        column_name = column_def.split()[0]
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")


def init_db() -> None:
    schema_name = "schema_postgres.sql" if is_postgres() else "schema.sql"
    schema_path = ROOT_DIR / "db" / schema_name

    with schema_path.open("r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_conn() as conn:
        if is_postgres():
            conn.execute(schema_sql)
            return

        conn.executescript(schema_sql)
        # Backward-compatible evolution for older local SQLite DBs.
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
