# Deploy on Render (Blueprint)

## 1) Push repository to GitHub
Render Blueprint deploys from your GitHub repo.

## 2) Create service from Blueprint
- In Render, choose: **New +** -> **Blueprint**.
- Select this repository.
- Render reads `/render.yaml` and creates:
  - `stock-news-web` (FastAPI + UI)
  - `stock-news-ingest-cron` (scheduled ingest every 5 min)

## 3) Set required env var
In Render dashboard for `stock-news-ingest-cron`, set:
- `BASE_URL = https://<your-web-service>.onrender.com`

## 4) Deploy
Deploy both services.

## 5) Initialize data once
After web deploy is live:
```bash
curl -X POST "https://<your-web-service>.onrender.com/v1/sources/seed"
curl -X POST "https://<your-web-service>.onrender.com/v1/ingest/run?force_all=true"
```

## 6) Verify
```bash
curl "https://<your-web-service>.onrender.com/health"
curl "https://<your-web-service>.onrender.com/v1/articles?limit=10&offset=0"
```

## Notes
- SQLite persistence is stored on Render disk at `/var/data/news.db`.
- Keep web service to 1 instance while using SQLite.
- Next production step is migrating to Postgres.
