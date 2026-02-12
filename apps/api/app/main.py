import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import get_conn, init_db
from .ingest import ingest_all

app = FastAPI(title="Stock News Aggregator API", version="0.3.0")

ROOT_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT_DIR / "apps" / "web"
app.mount("/assets", StaticFiles(directory=str(WEB_DIR), html=False), name="web-assets")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def frontend() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def validate_source_payload(source: Dict[str, Any]) -> None:
    if not source.get("name"):
        raise HTTPException(status_code=400, detail="Source name is required")
    if not source.get("feed_url"):
        raise HTTPException(
            status_code=400,
            detail=f"feed_url is required for source {source.get('name', '<unknown>')}",
        )


def normalize_search_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", query.lower())
    if not tokens:
        return ""
    return " AND ".join(f"{token}*" for token in tokens[:8])


@app.post("/v1/sources/seed")
def seed_sources(config_path: str = "/Users/sugamgandhi/Desktop/stock_news/config/sources.json") -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Config not found: {config_path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = payload.get("sources", [])

    inserted = 0
    updated = 0

    with get_conn() as conn:
        for source in sources:
            validate_source_payload(source)
            exists_before = conn.execute(
                "SELECT 1 FROM sources WHERE name = ?",
                (source["name"],),
            ).fetchone()

            conn.execute(
                """
                INSERT INTO sources (
                    name,
                    feed_url,
                    polling_interval_minutes,
                    status,
                    trust_score,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    feed_url = excluded.feed_url,
                    polling_interval_minutes = excluded.polling_interval_minutes,
                    status = excluded.status,
                    trust_score = excluded.trust_score,
                    updated_at = datetime('now')
                """,
                (
                    source["name"],
                    source["feed_url"],
                    int(source.get("polling_interval_minutes", 5)),
                    source.get("status", "active"),
                    int(source.get("trust_score", 50)),
                ),
            )
            if exists_before:
                updated += 1
            else:
                inserted += 1

    return {"seeded": len(sources), "inserted": inserted, "updated": updated}


@app.get("/v1/sources")
def list_sources(status: Optional[str] = None) -> List[Dict[str, Any]]:
    query = """
        SELECT
            id,
            name,
            feed_url,
            polling_interval_minutes,
            status,
            trust_score,
            last_polled_at,
            last_success_at,
            last_error_at,
            last_error_message,
            consecutive_failures,
            last_entries_seen,
            last_inserted,
            last_updated_count,
            last_duration_ms,
            created_at,
            updated_at
        FROM sources
    """
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY trust_score DESC, id ASC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.post("/v1/ingest/run")
def run_ingestion(
    force_all: bool = Query(default=False),
    source_id: Optional[int] = Query(default=None),
    trigger_type: str = Query(default="manual", pattern="^(manual|scheduled)$"),
) -> Dict[str, Any]:
    try:
        return ingest_all(trigger_type=trigger_type, force_all=force_all, source_id=source_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/ingest/runs")
def list_ingestion_runs(limit: int = Query(default=20, ge=1, le=200)) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                started_at,
                completed_at,
                status,
                trigger_type,
                total_sources,
                successful_sources,
                failed_sources,
                total_inserted,
                total_updated,
                error_message
            FROM ingestion_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/v1/ingest/runs/{run_id}/sources")
def list_ingestion_run_sources(run_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        run = conn.execute("SELECT id FROM ingestion_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        rows = conn.execute(
            """
            SELECT
                id,
                run_id,
                source_id,
                source_name,
                started_at,
                completed_at,
                status,
                entries_seen,
                inserted,
                updated,
                errors,
                duration_ms,
                error_message
            FROM ingestion_source_runs
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/v1/articles")
def list_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, min_length=2, max_length=100),
) -> Dict[str, Any]:
    clauses: List[str] = []
    params: List[Any] = []
    rank_select = ""
    order_by = "COALESCE(a.published_at, a.fetched_at) DESC"
    joins = ""

    normalized_q = normalize_search_query(q) if q else ""
    if q and not normalized_q:
        return {
            "items": [],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": 0,
                "total": 0,
                "has_next": False,
                "has_prev": offset > 0,
                "next_offset": None,
                "prev_offset": max(0, offset - limit),
                "total_pages": 0,
                "current_page": 1,
            },
            "filters": {"source_id": source_id, "q": q},
        }

    if normalized_q:
        joins += " JOIN articles_fts ON articles_fts.rowid = a.id"
        clauses.append("articles_fts MATCH ?")
        params.append(normalized_q)
        rank_select = ", bm25(articles_fts, 1.4, 0.8) AS search_rank"
        order_by = "search_rank ASC, COALESCE(a.published_at, a.fetched_at) DESC"

    if source_id is not None:
        clauses.append("a.source_id = ?")
        params.append(source_id)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    count_sql = f"""
        SELECT COUNT(1) AS total
        FROM articles a
        {joins}
        {where_sql}
    """

    if not normalized_q and source_id is None:
        # Interleave sources by "slot" so one source cannot dominate top rows.
        data_sql = f"""
            WITH ranked AS (
                SELECT
                    a.id,
                    a.source_id,
                    s.name AS source_name,
                    a.title,
                    a.summary,
                    a.original_url,
                    a.published_at,
                    a.fetched_at,
                    a.language,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.source_id
                        ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
                    ) AS source_slot
                FROM articles a
                JOIN sources s ON s.id = a.source_id
                {where_sql}
            )
            SELECT
                id,
                source_id,
                source_name,
                title,
                summary,
                original_url,
                published_at,
                fetched_at,
                language
            FROM ranked
            ORDER BY source_slot ASC, COALESCE(published_at, fetched_at) DESC
            LIMIT ? OFFSET ?
        """
    else:
        data_sql = f"""
            SELECT
                a.id,
                a.source_id,
                s.name AS source_name,
                a.title,
                a.summary,
                a.original_url,
                a.published_at,
                a.fetched_at,
                a.language
                {rank_select}
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            {joins}
            {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """

    with get_conn() as conn:
        total = int(conn.execute(count_sql, params).fetchone()["total"])
        rows = conn.execute(data_sql, params + [limit, offset]).fetchall()

    total_pages = math.ceil(total / limit) if total > 0 else 0
    current_page = (offset // limit) + 1
    next_offset = offset + limit if (offset + limit) < total else None
    prev_offset = max(0, offset - limit) if offset > 0 else None

    return {
        "items": [dict(r) for r in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_next": next_offset is not None,
            "has_prev": prev_offset is not None,
            "next_offset": next_offset,
            "prev_offset": prev_offset,
            "total_pages": total_pages,
            "current_page": current_page,
        },
        "filters": {
            "source_id": source_id,
            "q": q,
        },
    }
