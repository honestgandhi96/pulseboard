import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import execute, get_conn, init_db, is_postgres, query_all, query_one, sql_now
from .ingest import ingest_all
from .tagging import attach_tags_to_articles, enrich_articles_without_tags, slugify, trending_tags

app = FastAPI(title="Stock News Aggregator API", version="0.3.0")

ROOT_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT_DIR / "apps" / "web"
SOURCES_CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
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


def append_tag_clause(
    clauses: List[str],
    params: List[Any],
    *,
    tag_type: str,
    tag_value: Optional[str],
) -> Optional[str]:
    if not tag_value:
        return None
    normalized = slugify(tag_value)
    clauses.append(
        """
        EXISTS (
            SELECT 1
            FROM article_tags at
            WHERE at.article_id = a.id
              AND at.tag_type = ?
              AND at.canonical_key = ?
        )
        """.strip()
    )
    params.extend([tag_type, normalized])
    return normalized


def empty_articles_payload(
    *,
    limit: int,
    offset: int,
    source_id: Optional[int],
    q: Optional[str],
    symbol: Optional[str],
    sector: Optional[str],
    topic: Optional[str],
) -> Dict[str, Any]:
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
        "filters": {
            "source_id": source_id,
            "q": q,
            "symbol": symbol,
            "sector": sector,
            "topic": topic,
        },
    }


def fetch_articles_payload(
    *,
    limit: int,
    offset: int,
    source_id: Optional[int] = None,
    q: Optional[str] = None,
    symbol: Optional[str] = None,
    sector: Optional[str] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    clauses: List[str] = []
    params: List[Any] = []
    order_by = "COALESCE(a.published_at, a.fetched_at) DESC"

    normalized_q = normalize_search_query(q) if q else ""
    if q and not normalized_q:
        return empty_articles_payload(
            limit=limit,
            offset=offset,
            source_id=source_id,
            q=q,
            symbol=symbol,
            sector=sector,
            topic=topic,
        )

    if normalized_q:
        if is_postgres():
            clauses.append(
                "to_tsvector('simple', coalesce(a.title, '') || ' ' || coalesce(a.summary, '')) @@ "
                "plainto_tsquery('simple', ?)"
            )
            params.append(q or "")
            order_by = (
                "ts_rank_cd(to_tsvector('simple', coalesce(a.title, '') || ' ' || coalesce(a.summary, '')), "
                "plainto_tsquery('simple', ?)) DESC, COALESCE(a.published_at, a.fetched_at) DESC"
            )
        else:
            clauses.append("articles_fts MATCH ?")
            params.append(normalized_q)
            order_by = "bm25(articles_fts, 1.4, 0.8) ASC, COALESCE(a.published_at, a.fetched_at) DESC"

    if source_id is not None:
        clauses.append("a.source_id = ?")
        params.append(source_id)

    normalized_symbol = append_tag_clause(clauses, params, tag_type="symbol", tag_value=symbol)
    normalized_sector = append_tag_clause(clauses, params, tag_type="sector", tag_value=sector)
    normalized_topic = append_tag_clause(clauses, params, tag_type="topic", tag_value=topic)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    joins = ""
    if normalized_q and not is_postgres():
        joins = " JOIN articles_fts ON articles_fts.rowid = a.id"

    count_sql = f"""
        SELECT COUNT(1) AS total
        FROM articles a
        {joins}
        {where_sql}
    """

    use_interleaving = not any([normalized_q, source_id is not None, normalized_symbol, normalized_sector, normalized_topic])

    if use_interleaving:
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
        data_params = list(params)
    else:
        data_params = list(params)
        if normalized_q and is_postgres():
            data_params = data_params + [q or ""]
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
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            {joins}
            {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """

    with get_conn() as conn:
        total_row = query_one(conn, count_sql, params)
        total = int(total_row["total"]) if total_row else 0
        rows = query_all(conn, data_sql, data_params + [limit, offset])

    rows = attach_tags_to_articles(rows)
    total_pages = math.ceil(total / limit) if total > 0 else 0
    current_page = (offset // limit) + 1
    next_offset = offset + limit if (offset + limit) < total else None
    prev_offset = max(0, offset - limit) if offset > 0 else None

    return {
        "items": rows,
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
            "symbol": normalized_symbol,
            "sector": normalized_sector,
            "topic": normalized_topic,
        },
    }


@app.post("/v1/sources/seed")
def seed_sources(config_path: str = str(SOURCES_CONFIG_PATH)) -> Dict[str, Any]:
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
            exists_before = query_one(
                conn,
                "SELECT 1 FROM sources WHERE name = ?",
                (source["name"],),
            )

            execute(
                conn,
                f"""
                INSERT INTO sources (
                    name,
                    feed_url,
                    polling_interval_minutes,
                    status,
                    trust_score,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, {sql_now()}, {sql_now()})
                ON CONFLICT(name) DO UPDATE SET
                    feed_url = excluded.feed_url,
                    polling_interval_minutes = excluded.polling_interval_minutes,
                    status = excluded.status,
                    trust_score = excluded.trust_score,
                    updated_at = {sql_now()}
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
        return query_all(conn, query, params)


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
        return query_all(
            conn,
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
        )


@app.get("/v1/ingest/runs/{run_id}/sources")
def list_ingestion_run_sources(run_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        run = query_one(conn, "SELECT id FROM ingestion_runs WHERE id = ?", (run_id,))
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        return query_all(
            conn,
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
        )


@app.get("/v1/articles")
def list_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, min_length=2, max_length=100),
    symbol: Optional[str] = Query(default=None, min_length=1, max_length=60),
    sector: Optional[str] = Query(default=None, min_length=1, max_length=60),
    topic: Optional[str] = Query(default=None, min_length=1, max_length=60),
) -> Dict[str, Any]:
    return fetch_articles_payload(
        limit=limit,
        offset=offset,
        source_id=source_id,
        q=q,
        symbol=symbol,
        sector=sector,
        topic=topic,
    )


@app.get("/v1/tags/trending")
def get_trending_tags(
    hours: int = Query(default=96, ge=1, le=720),
    limit: int = Query(default=8, ge=1, le=25),
) -> Dict[str, Any]:
    return {
        "window_hours": hours,
        "symbols": trending_tags("symbol", hours=hours, limit=limit),
        "sectors": trending_tags("sector", hours=hours, limit=limit),
        "topics": trending_tags("topic", hours=hours, limit=limit),
    }


@app.get("/v1/tags/symbols/{symbol}")
def get_symbol_articles(
    symbol: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, min_length=2, max_length=100),
) -> Dict[str, Any]:
    return fetch_articles_payload(
        limit=limit,
        offset=offset,
        source_id=source_id,
        q=q,
        symbol=symbol,
    )


@app.get("/v1/tags/topics/{topic}")
def get_topic_articles(
    topic: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, min_length=2, max_length=100),
) -> Dict[str, Any]:
    return fetch_articles_payload(
        limit=limit,
        offset=offset,
        source_id=source_id,
        q=q,
        topic=topic,
    )


@app.post("/v1/enrich/backfill")
def backfill_tags(
    limit: int = Query(default=50, ge=1, le=500),
    force: bool = Query(default=False),
) -> Dict[str, Any]:
    return enrich_articles_without_tags(limit=limit, force=force)
