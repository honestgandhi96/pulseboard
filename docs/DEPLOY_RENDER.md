# Deploy on Render with Supabase

## 1) Push repository to GitHub
Render Blueprint deploys from your GitHub repo.

## 2) Get your Supabase Postgres connection string
In Supabase:
- Project Settings -> Database
- Copy the pooled or direct Postgres connection string
- Use it as `DATABASE_URL`

## 3) Create services from Blueprint
- In Render, choose: **New +** -> **Blueprint**
- Select this repository
- Render reads `/render.yaml` and creates:
  - `stock-news-web`
  - `stock-news-ingest-cron`

## 4) Set required env vars
On `stock-news-web`:
- `DATABASE_URL=postgresql://...`

On `stock-news-ingest-cron`:
- `BASE_URL=https://<your-web-service>.onrender.com`

## 5) Deploy
Deploy the Blueprint after both env vars are set.

## 6) Initialize data once
After the web service is live:
```bash
curl -X POST "https://<your-web-service>.onrender.com/v1/sources/seed"
curl -X POST "https://<your-web-service>.onrender.com/v1/ingest/run?force_all=true"
```

## 7) Verify
```bash
curl "https://<your-web-service>.onrender.com/health"
curl "https://<your-web-service>.onrender.com/v1/articles?limit=10&offset=0"
```

## Notes
- The app now supports `DATABASE_URL` for Postgres and falls back to local SQLite only when `DATABASE_URL` is not set.
- Render no longer needs a persistent disk when you use Supabase.
- Search uses SQLite FTS locally and Postgres full-text search in Supabase.
