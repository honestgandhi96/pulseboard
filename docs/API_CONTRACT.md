# API Contract v3

## `GET /`
- Serves the web app UI.

## `GET /health`
- Response:
```json
{ "status": "ok" }
```

## `POST /v1/sources/seed`
- Seeds source registry from `/config/sources.json`.
- Existing sources are updated (`name` is treated as identity).
- Response:
```json
{ "seeded": 3, "inserted": 1, "updated": 2 }
```

## `GET /v1/sources?status=active`
- Returns source registry with health diagnostics.
- Query params:
  - `status` (optional): `active|paused|disabled`

## `POST /v1/ingest/run?force_all=false&source_id=&trigger_type=manual`
- Triggers one ingestion cycle.
- Only due sources are polled unless `force_all=true`.
- Returns `409` when another run is already active.

## `GET /v1/ingest/runs?limit=20`
- Lists recent ingestion runs.

## `GET /v1/ingest/runs/{run_id}/sources`
- Lists per-source results for one run.

## `GET /v1/articles?limit=20&offset=0&source_id=1&q=bank`
- Query params:
  - `limit` (1..100)
  - `offset` (>=0)
  - `source_id` (optional)
  - `q` (optional; full-text search over title+summary)

- Response:
```json
{
  "items": [
    {
      "id": 101,
      "source_id": 1,
      "source_name": "Reuters Business",
      "title": "...",
      "summary": "...",
      "original_url": "https://...",
      "published_at": "2026-02-12 09:59:00",
      "fetched_at": "2026-02-12 10:00:00",
      "language": "en",
      "search_rank": -8.1
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "returned": 20,
    "total": 245,
    "has_next": true,
    "has_prev": false,
    "next_offset": 20,
    "prev_offset": null,
    "total_pages": 13,
    "current_page": 1
  },
  "filters": {
    "source_id": 1,
    "q": "bank"
  }
}
```
