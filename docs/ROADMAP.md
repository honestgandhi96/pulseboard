# 90-Day Roadmap

## Phase 1 (Weeks 1-2): Ingestion Core
- Finalize source registry format and source quality criteria.
- Build poller, parser, normalization, and dedup.
- Add source health checks: success/failure rate, last-seen timestamp.
- Deliver: stable ingestion pipeline for 20-40 feeds.

## Phase 2 (Weeks 3-4): API + Search Basics
- Add article list/filter endpoints (source, time, keyword).
- Implement Postgres migration and indexes.
- Add simple full-text search (Postgres FTS).
- Deliver: API v1 used by frontend lists and search.

## Phase 3 (Weeks 5-6): Frontend MVP
- Build responsive web app (home feed, source filter, article card, details link-out).
- Add loading/error states and empty states.
- Add basic telemetry (page views, article click-through).
- Deliver: publicly usable MVP.

## Phase 4 (Weeks 7-8): Ranking + Relevance
- Add ranking score (recency + trust_score + engagement).
- Add topic and symbol tagging pipeline.
- Add trending endpoints.
- Deliver: default ranked feed with topic pages.

## Phase 5 (Weeks 9-10): Reliability + Ops
- Add observability dashboards (ingestion latency, parse error rate, duplicate ratio).
- Add alerting for feed outage and low-volume anomalies.
- Add retry policies and circuit-breaking for bad feeds.
- Deliver: operational hardening for production.

## Phase 6 (Weeks 11-12): Monetization/Retention Hooks
- User accounts and watchlists.
- Notification candidates (digest email/push).
- Saved articles and personalization primitives.
- Deliver: retention-ready v1.5.

## Exit Criteria for MVP
- New RSS items appear in < 5 minutes median.
- Duplicate ratio below 15% after clustering.
- API p95 under 300 ms for `/v1/articles` at target traffic.
- > 99% ingestion job completion for active feeds.
