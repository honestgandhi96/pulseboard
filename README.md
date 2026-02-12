# Stock News Aggregator MVP

This repo bootstraps a finance news aggregation backend + frontend similar to Pulse-style products:
- Pull latest news from RSS feeds
- Normalize + deduplicate
- Full-text search (SQLite FTS5)
- Pagination metadata for feed UX
- Source-diversified default ranking (reduces single-source domination)
- Track ingestion runs and per-source health metrics

## Tech (MVP)
- API: FastAPI
- Storage: SQLite (upgrade to Postgres in next phase)
- Ingestion: RSS polling via `feedparser`
- Frontend: static HTML/CSS/JS served by FastAPI

## Quickstart
```bash
cd /Users/sugamgandhi/Desktop/stock_news/apps/api
./run.sh
```

API + UI run at `http://localhost:8000`.

## First run flow
1. Seed sources:
```bash
curl -X POST http://localhost:8000/v1/sources/seed
```
2. Trigger ingestion:
```bash
curl -X POST "http://localhost:8000/v1/ingest/run?force_all=true"
```
3. Fetch paginated articles:
```bash
curl "http://localhost:8000/v1/articles?limit=20&offset=0"
```
4. Full-text search:
```bash
curl "http://localhost:8000/v1/articles?limit=20&offset=0&q=inflation"
```

## Scheduled ingestion
See `/Users/sugamgandhi/Desktop/stock_news/docs/SCHEDULING.md`.

## Key files
- `/Users/sugamgandhi/Desktop/stock_news/apps/api/app/main.py`: API + frontend mount
- `/Users/sugamgandhi/Desktop/stock_news/apps/api/app/ingest.py`: RSS ingest + dedup logic
- `/Users/sugamgandhi/Desktop/stock_news/db/schema.sql`: schema + FTS index/triggers
- `/Users/sugamgandhi/Desktop/stock_news/apps/web/index.html`: frontend UI
- `/Users/sugamgandhi/Desktop/stock_news/apps/web/styles.css`: visual system and responsive layout
- `/Users/sugamgandhi/Desktop/stock_news/apps/web/app.js`: API integration and pagination controls
- `/Users/sugamgandhi/Desktop/stock_news/config/sources.json`: initial source registry
- `/Users/sugamgandhi/Desktop/stock_news/docs/API_CONTRACT.md`: endpoint contract
