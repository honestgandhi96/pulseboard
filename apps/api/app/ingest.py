import hashlib
import html
import re
import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlparse, urlunparse

import feedparser
import certifi

from .db import execute, get_conn, query_all, query_one

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}

FEED_TIMEOUT_SECONDS = 12
FEED_FETCH_RETRIES = 2
SUMMARY_MAX_LEN = 600


def build_ssl_context() -> ssl.SSLContext:
    # Use certifi CA bundle so HTTPS RSS feeds validate reliably across macOS/Python installs.
    return ssl.create_default_context(cafile=certifi.where())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def dt_to_db(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def now_utc_db() -> str:
    return dt_to_db(now_utc())


def parse_db_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def normalize_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    clean_query = [
        (k, v)
        for (k, v) in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    normalized = parsed._replace(
        scheme=(parsed.scheme or "https").lower(),
        netloc=parsed.netloc.lower(),
        query="&".join(f"{k}={v}" if v else k for k, v in clean_query),
        fragment="",
    )
    return urlunparse(normalized)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def title_digest(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def parse_datetime(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt_to_db(dt)
    except (TypeError, ValueError):
        return None


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", value or "")
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_summary(entry: Dict[str, Any]) -> str:
    candidates: List[str] = []

    for key in ("summary", "description", "subtitle"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)

    summary_detail = entry.get("summary_detail")
    if isinstance(summary_detail, dict):
        value = summary_detail.get("value")
        if isinstance(value, str) and value.strip():
            candidates.append(value)

    content_list = entry.get("content")
    if isinstance(content_list, list):
        for item in content_list:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                candidates.append(value)
                break

    media_description = entry.get("media_description")
    if isinstance(media_description, str) and media_description.strip():
        candidates.append(media_description)
    elif isinstance(media_description, list):
        for item in media_description:
            if isinstance(item, dict):
                value = item.get("content")
                if isinstance(value, str) and value.strip():
                    candidates.append(value)
                    break
            elif isinstance(item, str) and item.strip():
                candidates.append(item)
                break

    for raw in candidates:
        clean = strip_html(raw)
        if clean:
            return clean[:SUMMARY_MAX_LEN]

    return ""


def fetch_eligible_sources(force_all: bool = False, source_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        query = """
            SELECT id, name, feed_url, polling_interval_minutes, last_polled_at
            FROM sources
            WHERE status = 'active'
        """
        params: List[Any] = []
        if source_id is not None:
            query += " AND id = ?"
            params.append(source_id)

        query += " ORDER BY trust_score DESC, id ASC"
        rows = query_all(conn, query, params)

    if force_all:
        return rows

    now = now_utc()
    eligible: List[Dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        last_polled = parse_db_datetime(data.get("last_polled_at"))
        if not last_polled:
            eligible.append(data)
            continue
        next_due = last_polled + timedelta(minutes=int(data["polling_interval_minutes"]))
        if next_due <= now:
            eligible.append(data)
    return eligible


def start_run(total_sources: int, trigger_type: str) -> int:
    with get_conn() as conn:
        running = query_one(
            conn,
            """
            SELECT id, started_at
            FROM ingestion_runs
            WHERE status = 'running'
            ORDER BY id DESC
            LIMIT 1
            """
        )
        if running:
            started_at = parse_db_datetime(running["started_at"]) or now_utc()
            if now_utc() - started_at < timedelta(minutes=30):
                raise RuntimeError(f"Ingestion run already active (run_id={running['id']})")

        cur = execute(
            conn,
            """
            INSERT INTO ingestion_runs (started_at, status, trigger_type, total_sources)
            VALUES (?, 'running', ?, ?)
            RETURNING id
            """,
            (now_utc_db(), trigger_type, total_sources),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("failed to create ingestion run")
        return int(row["id"])


def finish_run(
    run_id: int,
    *,
    successful_sources: int,
    failed_sources: int,
    total_inserted: int,
    total_updated: int,
    error_message: Optional[str] = None,
) -> None:
    if failed_sources == 0:
        status = "success"
    elif successful_sources > 0:
        status = "partial_success"
    else:
        status = "failed"

    with get_conn() as conn:
        execute(
            conn,
            """
            UPDATE ingestion_runs
            SET completed_at = ?,
                status = ?,
                successful_sources = ?,
                failed_sources = ?,
                total_inserted = ?,
                total_updated = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                now_utc_db(),
                status,
                successful_sources,
                failed_sources,
                total_inserted,
                total_updated,
                error_message,
                run_id,
            ),
        )


def record_source_run(
    *,
    run_id: int,
    source_id: int,
    source_name: str,
    started_at: str,
    completed_at: str,
    status: str,
    entries_seen: int,
    inserted: int,
    updated: int,
    errors: int,
    duration_ms: int,
    error_message: Optional[str],
) -> None:
    with get_conn() as conn:
        execute(
            conn,
            """
            INSERT INTO ingestion_source_runs (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
                error_message,
            ),
        )


def update_source_health(
    *,
    source_id: int,
    succeeded: bool,
    entries_seen: int,
    inserted: int,
    updated: int,
    duration_ms: int,
    error_message: Optional[str],
) -> None:
    with get_conn() as conn:
        if succeeded:
            execute(
                conn,
                """
                UPDATE sources
                SET last_polled_at = ?,
                    last_success_at = ?,
                    last_error_message = NULL,
                    consecutive_failures = 0,
                    last_entries_seen = ?,
                    last_inserted = ?,
                    last_updated_count = ?,
                    last_duration_ms = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    now_utc_db(),
                    now_utc_db(),
                    entries_seen,
                    inserted,
                    updated,
                    duration_ms,
                    now_utc_db(),
                    source_id,
                ),
            )
        else:
            execute(
                conn,
                """
                UPDATE sources
                SET last_polled_at = ?,
                    last_error_at = ?,
                    last_error_message = ?,
                    consecutive_failures = consecutive_failures + 1,
                    last_entries_seen = ?,
                    last_inserted = ?,
                    last_updated_count = ?,
                    last_duration_ms = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    now_utc_db(),
                    now_utc_db(),
                    (error_message or "ingestion failed")[:500],
                    entries_seen,
                    inserted,
                    updated,
                    duration_ms,
                    now_utc_db(),
                    source_id,
                ),
            )


def fetch_feed(source: Dict[str, Any]) -> feedparser.FeedParserDict:
    last_error: Optional[Exception] = None
    ssl_context = build_ssl_context()
    for attempt in range(FEED_FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(
                source["feed_url"],
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/rss+xml, application/atom+xml, application/xml,text/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Referer": source["feed_url"],
                },
            )
            with urllib.request.urlopen(req, timeout=FEED_TIMEOUT_SECONDS, context=ssl_context) as resp:
                content = resp.read()
            return feedparser.parse(content)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt == FEED_FETCH_RETRIES:
                break
    raise RuntimeError(str(last_error) if last_error else "unknown feed fetch error")


def upsert_article(
    source_id: int,
    title: str,
    summary: str,
    original_url: str,
    normalized: str,
    title_hash: str,
    published_at: Optional[str],
    language: str,
) -> Tuple[bool, int]:
    with get_conn() as conn:
        existing = query_one(
            conn,
            """
            SELECT id FROM articles
            WHERE normalized_url = ? OR title_hash = ?
            LIMIT 1
            """,
            (normalized, title_hash),
        )

        if existing:
            article_id = int(existing["id"])
            execute(
                conn,
                """
                UPDATE articles
                SET summary = COALESCE(NULLIF(?, ''), summary),
                    fetched_at = ?,
                    language = COALESCE(NULLIF(?, ''), language)
                WHERE id = ?
                """,
                (summary, now_utc_db(), language, article_id),
            )
            return (False, article_id)

        cur = execute(
            conn,
            """
            INSERT INTO articles (
                source_id,
                title,
                summary,
                original_url,
                normalized_url,
                title_hash,
                published_at,
                fetched_at,
                language
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                source_id,
                title,
                summary,
                original_url,
                normalized,
                title_hash,
                published_at,
                now_utc_db(),
                language,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("failed to insert article")
        return (True, int(row["id"]))


def ingest_source(source: Dict[str, Any], run_id: int) -> Dict[str, Any]:
    source_started = now_utc()
    status = "success"
    inserted = 0
    updated = 0
    errors = 0
    entries_seen = 0
    error_message: Optional[str] = None

    try:
        parsed = fetch_feed(source)
        entries_seen = len(parsed.entries)

        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                errors += 1
                continue

            normalized = normalize_url(link)
            summary = extract_summary(entry)
            published_at = parse_datetime(entry.get("published") or entry.get("updated"))
            language = (entry.get("language") or "en").strip()[:10] or "en"

            created, _ = upsert_article(
                source_id=int(source["id"]),
                title=title,
                summary=summary,
                original_url=link,
                normalized=normalized,
                title_hash=title_digest(title),
                published_at=published_at,
                language=language,
            )
            if created:
                inserted += 1
            else:
                updated += 1
    except Exception as exc:
        status = "failed"
        error_message = str(exc)

    completed = now_utc()
    duration_ms = int((completed - source_started).total_seconds() * 1000)

    record_source_run(
        run_id=run_id,
        source_id=int(source["id"]),
        source_name=source["name"],
        started_at=dt_to_db(source_started),
        completed_at=dt_to_db(completed),
        status=status,
        entries_seen=entries_seen,
        inserted=inserted,
        updated=updated,
        errors=errors,
        duration_ms=duration_ms,
        error_message=error_message,
    )

    update_source_health(
        source_id=int(source["id"]),
        succeeded=(status == "success"),
        entries_seen=entries_seen,
        inserted=inserted,
        updated=updated,
        duration_ms=duration_ms,
        error_message=error_message,
    )

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
        "entries_seen": entries_seen,
        "duration_ms": duration_ms,
        "error_message": error_message,
    }


def ingest_all(
    *,
    trigger_type: str = "manual",
    force_all: bool = False,
    source_id: Optional[int] = None,
) -> Dict[str, Any]:
    sources = fetch_eligible_sources(force_all=force_all, source_id=source_id)
    run_id = start_run(total_sources=len(sources), trigger_type=trigger_type)

    try:
        results = [ingest_source(source, run_id) for source in sources]
        successful_sources = sum(1 for r in results if r["status"] == "success")
        failed_sources = len(results) - successful_sources
        total_inserted = sum(int(r["inserted"]) for r in results)
        total_updated = sum(int(r["updated"]) for r in results)

        finish_run(
            run_id,
            successful_sources=successful_sources,
            failed_sources=failed_sources,
            total_inserted=total_inserted,
            total_updated=total_updated,
        )

        return {
            "run_id": run_id,
            "sources_polled": len(sources),
            "run_at": now_utc_db(),
            "results": results,
        }
    except Exception as exc:
        finish_run(
            run_id,
            successful_sources=0,
            failed_sources=len(sources),
            total_inserted=0,
            total_updated=0,
            error_message=str(exc),
        )
        raise
