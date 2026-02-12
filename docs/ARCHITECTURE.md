# Architecture (MVP -> Scale)

## MVP flow
1. Source registry stores feed URL + polling metadata.
2. Ingestion runner fetches active RSS feeds.
3. Normalizer standardizes URL, timestamps, language, and summary.
4. Dedup key uses normalized URL and title hash.
5. API serves latest articles + source metadata.

## Current components
- `app/main.py`: HTTP interface
- `app/ingest.py`: feed fetch, parse, normalize, upsert
- `db/schema.sql`: source/article persistence

## Scale path
- Move SQLite to Postgres.
- Move manual ingestion trigger to scheduled queue workers.
- Add Redis for queueing/caching.
- Add search service (OpenSearch) when FTS limits are hit.
- Split enrichment/tagging into async worker pipeline.

## Key non-functional requirements
- Freshness: 2-5 minute ingest lag for top sources.
- Reliability: retries with backoff; per-source failure isolation.
- Compliance: snippets only, attribution + canonical outbound links.
