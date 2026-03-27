import json
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .db import execute, get_conn, is_postgres, query_all, query_one

ROOT_DIR = Path(__file__).resolve().parents[3]
TAGGING_CONFIG_PATH = ROOT_DIR / "config" / "tagging.json"
OPENAI_MODEL = os.getenv("OPENAI_TAGGING_MODEL", "gpt-4.1-mini")
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/responses")
DEFAULT_TOPIC_WINDOW_HOURS = 96

TAG_TYPES = ("symbol", "sector", "topic")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def truncate_payload(payload: Dict[str, Any], max_chars: int = 12000) -> Dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=True)
    if len(raw) <= max_chars:
        return payload
    return {"truncated": True, "preview": raw[:max_chars]}


@lru_cache(maxsize=1)
def load_tagging_config() -> Dict[str, Any]:
    return json.loads(TAGGING_CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def symbol_index() -> List[Dict[str, Any]]:
    items = []
    for item in load_tagging_config().get("symbols", []):
        aliases = [alias.lower() for alias in item.get("aliases", [])]
        items.append({**item, "aliases_lower": aliases})
    return items


@lru_cache(maxsize=1)
def sector_index() -> List[Dict[str, Any]]:
    items = []
    for item in load_tagging_config().get("sectors", []):
        aliases = [alias.lower() for alias in item.get("aliases", [])]
        items.append({**item, "aliases_lower": aliases})
    return items


@lru_cache(maxsize=1)
def topic_index() -> List[Dict[str, Any]]:
    items = []
    for item in load_tagging_config().get("topics", []):
        aliases = [alias.lower() for alias in item.get("aliases", [])]
        items.append({**item, "aliases_lower": aliases})
    return items


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def build_prompt(article: Dict[str, Any]) -> str:
    config = load_tagging_config()
    symbol_hints = [
        f"{item['display_name']} ({item['canonical_key']})"
        for item in config.get("symbols", [])[:25]
    ]
    sector_hints = [item["display_name"] for item in config.get("sectors", [])]
    topic_hints = [item["display_name"] for item in config.get("topics", [])]

    return (
        "You are classifying a finance news article for an India-first market intelligence product.\n"
        "Return strict JSON with these keys only: "
        '{"symbols":[],"sectors":[],"topics":[],"entities":[],"confidence":0.0}.\n'
        "Rules:\n"
        "- Use short symbol keys where possible for listed companies or major indices.\n"
        "- Prefer India-relevant companies, indices, and regulators when present.\n"
        "- sectors must be from this set: " + ", ".join(sector_hints) + ".\n"
        "- topics must be from this set: " + ", ".join(topic_hints) + ".\n"
        "- entities can include central banks, regulators, exchanges, commodities, or companies.\n"
        "- confidence is a float from 0 to 1.\n"
        "- If unsure, return fewer tags rather than hallucinating.\n\n"
        f"Symbol hints: {', '.join(symbol_hints)}\n\n"
        f"Title: {article.get('title', '')}\n"
        f"Summary: {article.get('summary', '')}\n"
        f"Source: {article.get('source_name', '')}\n"
        f"URL: {article.get('original_url', '')}\n"
    )


def call_openai_tagger(article: Dict[str, Any]) -> Dict[str, Any]:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    payload = {
        "model": OPENAI_MODEL,
        "input": build_prompt(article),
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    output_text = ""
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                output_text += content.get("text", "")

    if not output_text.strip():
        raise RuntimeError("OpenAI tagging response was empty")

    return {
        "raw_response": truncate_payload(data),
        "parsed": json.loads(output_text),
        "model_name": data.get("model", OPENAI_MODEL),
    }


def match_curated_items(text: str, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    haystack = f" {normalize_text(text)} "
    matches: List[Dict[str, Any]] = []
    for item in items:
        if any(f" {alias} " in haystack for alias in item.get("aliases_lower", [])):
            matches.append(item)
    return matches


def heuristic_tags(article: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(
        [
            article.get("title", ""),
            article.get("summary", ""),
            article.get("source_name", ""),
        ]
    )
    symbols = match_curated_items(text, symbol_index())
    sectors = match_curated_items(text, sector_index())
    topics = match_curated_items(text, topic_index())

    symbol_tags = [
        {
            "tag_type": "symbol",
            "canonical_key": item["canonical_key"],
            "display_name": item["display_name"],
            "confidence": 0.72,
            "source": "heuristic",
        }
        for item in symbols
    ]
    sector_tags = [
        {
            "tag_type": "sector",
            "canonical_key": item["canonical_key"],
            "display_name": item["display_name"],
            "confidence": 0.66,
            "source": "heuristic",
        }
        for item in sectors
    ]
    topic_tags = [
        {
            "tag_type": "topic",
            "canonical_key": item["canonical_key"],
            "display_name": item["display_name"],
            "confidence": 0.66,
            "source": "heuristic",
        }
        for item in topics
    ]
    for symbol in symbols:
        if symbol.get("sector") and not any(t["canonical_key"] == symbol["sector"] for t in sector_tags):
            sector_meta = next((item for item in sector_index() if item["canonical_key"] == symbol["sector"]), None)
            if sector_meta:
                sector_tags.append(
                    {
                        "tag_type": "sector",
                        "canonical_key": sector_meta["canonical_key"],
                        "display_name": sector_meta["display_name"],
                        "confidence": 0.64,
                        "source": "heuristic",
                    }
                )
    return {
        "symbols": symbol_tags,
        "sectors": sector_tags,
        "topics": topic_tags,
        "entities": [],
        "confidence": 0.66,
    }


def normalize_symbol_name(raw_value: str) -> Optional[Dict[str, Any]]:
    value = normalize_text(raw_value)
    if not value:
        return None
    for item in symbol_index():
        if value == normalize_text(item["canonical_key"]) or value == normalize_text(item["display_name"]):
            return item
        if value in item.get("aliases_lower", []):
            return item
    value_compact = re.sub(r"[^a-z0-9&]+", "", value)
    for item in symbol_index():
        aliases = [re.sub(r"[^a-z0-9&]+", "", alias) for alias in item.get("aliases_lower", [])]
        if value_compact == re.sub(r"[^a-z0-9&]+", "", item["canonical_key"].lower()) or value_compact in aliases:
            return item
    return None


def normalize_taxonomy_name(raw_value: str, taxonomy: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    value = normalize_text(raw_value)
    if not value:
        return None
    for item in taxonomy:
        if value == normalize_text(item["canonical_key"]) or value == normalize_text(item["display_name"]):
            return item
        if value in item.get("aliases_lower", []):
            return item
    return None


def dedupe_tags(tags: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for tag in tags:
        key = (tag["tag_type"], tag["canonical_key"])
        current = deduped.get(key)
        if current is None or (tag.get("confidence") or 0) > (current.get("confidence") or 0):
            deduped[key] = tag
    return list(deduped.values())


def normalize_ai_payload(article: Dict[str, Any], ai_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    confidence = float(ai_payload.get("confidence") or 0.72)
    tags: List[Dict[str, Any]] = []
    symbols = ai_payload.get("symbols", []) or []
    sectors = ai_payload.get("sectors", []) or []
    topics = ai_payload.get("topics", []) or []

    for value in symbols:
        if not isinstance(value, str):
            continue
        normalized = normalize_symbol_name(value)
        if not normalized:
            continue
        tags.append(
            {
                "tag_type": "symbol",
                "canonical_key": normalized["canonical_key"],
                "display_name": normalized["display_name"],
                "confidence": confidence,
                "source": "ai",
            }
        )
        sector_key = normalized.get("sector")
        if sector_key:
            sector_meta = next((item for item in sector_index() if item["canonical_key"] == sector_key), None)
            if sector_meta:
                tags.append(
                    {
                        "tag_type": "sector",
                        "canonical_key": sector_meta["canonical_key"],
                        "display_name": sector_meta["display_name"],
                        "confidence": max(0.6, confidence - 0.08),
                        "source": "derived",
                    }
                )

    for value in sectors:
        if not isinstance(value, str):
            continue
        normalized = normalize_taxonomy_name(value, sector_index())
        if not normalized:
            continue
        tags.append(
            {
                "tag_type": "sector",
                "canonical_key": normalized["canonical_key"],
                "display_name": normalized["display_name"],
                "confidence": confidence,
                "source": "ai",
            }
        )

    for value in topics:
        if not isinstance(value, str):
            continue
        normalized = normalize_taxonomy_name(value, topic_index())
        if not normalized:
            continue
        tags.append(
            {
                "tag_type": "topic",
                "canonical_key": normalized["canonical_key"],
                "display_name": normalized["display_name"],
                "confidence": confidence,
                "source": "ai",
            }
        )

    if not tags:
        fallback = heuristic_tags(article)
        tags.extend(fallback["symbols"] + fallback["sectors"] + fallback["topics"])

    return dedupe_tags(tags)


def clear_article_tags(conn: Any, article_id: int) -> None:
    execute(conn, "DELETE FROM article_tags WHERE article_id = ?", (article_id,))


def save_enrichment_result(
    conn: Any,
    article_id: int,
    status: str,
    model_name: Optional[str],
    raw_payload: Optional[Dict[str, Any]],
    error_message: Optional[str],
) -> None:
    execute(
        conn,
        """
        INSERT INTO article_enrichment_runs (
            article_id,
            status,
            model_name,
            provider,
            raw_payload,
            error_message,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, 'openai', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            article_id,
            status,
            model_name,
            json.dumps(raw_payload or {}),
            error_message,
        ),
    )


def persist_tags(conn: Any, article_id: int, tags: Iterable[Dict[str, Any]]) -> None:
    clear_article_tags(conn, article_id)
    for tag in dedupe_tags(tags):
        execute(
            conn,
            """
            INSERT INTO article_tags (
                article_id,
                tag_type,
                canonical_key,
                display_name,
                confidence,
                source,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                article_id,
                tag["tag_type"],
                tag["canonical_key"],
                tag["display_name"],
                tag.get("confidence"),
                tag.get("source", "ai"),
            ),
        )


def enrich_article(article_id: int, *, force: bool = False) -> Dict[str, Any]:
    with get_conn() as conn:
        article = query_one(
            conn,
            """
            SELECT
                a.id,
                a.title,
                a.summary,
                a.original_url,
                s.name AS source_name
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            WHERE a.id = ?
            """,
            (article_id,),
        )
        if not article:
            raise RuntimeError(f"article {article_id} not found")

        existing_tags = query_all(
            conn,
            "SELECT id FROM article_tags WHERE article_id = ? LIMIT 1",
            (article_id,),
        )
        if existing_tags and not force:
            return {"article_id": article_id, "status": "skipped", "tags": len(existing_tags)}

        ai_error: Optional[str] = None
        ai_payload: Optional[Dict[str, Any]] = None
        model_name: Optional[str] = None

        try:
            ai_result = call_openai_tagger(article)
            ai_payload = ai_result.get("raw_response")
            model_name = ai_result.get("model_name")
            tags = normalize_ai_payload(article, ai_result.get("parsed", {}))
            status = "success" if tags else "fallback"
        except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
            ai_error = str(exc)
            fallback = heuristic_tags(article)
            tags = dedupe_tags(fallback["symbols"] + fallback["sectors"] + fallback["topics"])
            status = "fallback" if tags else "failed"

        persist_tags(conn, article_id, tags)
        save_enrichment_result(
            conn,
            article_id,
            status,
            model_name or OPENAI_MODEL,
            ai_payload,
            ai_error,
        )
        return {"article_id": article_id, "status": status, "tag_count": len(tags), "error_message": ai_error}


def enrich_articles_without_tags(limit: int = 50, *, force: bool = False) -> Dict[str, Any]:
    with get_conn() as conn:
        if force:
            rows = query_all(
                conn,
                """
                SELECT id
                FROM articles
                ORDER BY COALESCE(published_at, fetched_at) DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = query_all(
                conn,
                """
                SELECT a.id
                FROM articles a
                LEFT JOIN article_tags t ON t.article_id = a.id
                WHERE t.id IS NULL
                ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
                LIMIT ?
                """,
                (limit,),
            )

    results = [enrich_article(int(row["id"]), force=force) for row in rows]
    return {
        "processed": len(results),
        "results": results,
    }


def fetch_article_tags(article_ids: Iterable[int]) -> Dict[int, Dict[str, List[Dict[str, Any]]]]:
    ids = [int(article_id) for article_id in article_ids]
    if not ids:
        return {}

    placeholders = ", ".join("?" for _ in ids)
    order_clause = "article_id ASC, confidence DESC NULLS LAST, display_name ASC"
    if not is_postgres():
        order_clause = "article_id ASC, confidence DESC, display_name ASC"
    with get_conn() as conn:
        rows = query_all(
            conn,
            f"""
            SELECT article_id, tag_type, canonical_key, display_name, confidence, source
            FROM article_tags
            WHERE article_id IN ({placeholders})
            ORDER BY {order_clause}
            """,
            ids,
        )

    tags_by_article: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
    for row in rows:
        article_tags = tags_by_article.setdefault(
            int(row["article_id"]),
            {"symbols": [], "sectors": [], "topics": []},
        )
        bucket_name = f"{row['tag_type']}s"
        article_tags[bucket_name].append(
            {
                "key": row["canonical_key"],
                "label": row["display_name"],
                "confidence": row.get("confidence"),
                "source": row.get("source"),
            }
        )
    return tags_by_article


def attach_tags_to_articles(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tags_by_article = fetch_article_tags([row["id"] for row in rows])
    enriched_rows: List[Dict[str, Any]] = []
    for row in rows:
        tag_payload = tags_by_article.get(int(row["id"]), {"symbols": [], "sectors": [], "topics": []})
        enriched_rows.append(
            {
                **row,
                "symbols": tag_payload["symbols"],
                "sectors": tag_payload["sectors"],
                "topics": tag_payload["topics"],
            }
        )
    return enriched_rows


def trending_tags(tag_type: str, hours: int = DEFAULT_TOPIC_WINDOW_HOURS, limit: int = 8) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        interval_sql = "CURRENT_TIMESTAMP - (? || ' hours')::interval"
        params: List[Any] = [tag_type, hours, limit]
        if not is_postgres():
            interval_sql = f"datetime('now', '-{hours} hours')"
            params = [tag_type, limit]

        query = f"""
            SELECT
                t.canonical_key AS key,
                MAX(t.display_name) AS label,
                COUNT(*) AS article_count,
                MAX(COALESCE(a.published_at, a.fetched_at)) AS latest_at
            FROM article_tags t
            JOIN articles a ON a.id = t.article_id
            WHERE t.tag_type = ?
              AND COALESCE(a.published_at, a.fetched_at) >= {interval_sql}
            GROUP BY t.canonical_key
            ORDER BY article_count DESC, latest_at DESC
            LIMIT ?
        """
        return query_all(conn, query, params)
