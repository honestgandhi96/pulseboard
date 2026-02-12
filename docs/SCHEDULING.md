# Scheduled Ingestion Setup

Use one scheduler only:
- Linux with systemd: use user timer.
- macOS or minimal Linux: use cron.

## 1) Prerequisites
```bash
cd /Users/sugamgandhi/Desktop/stock_news/apps/api
./run.sh
```
In another shell, seed sources once:
```bash
curl -X POST http://localhost:8000/v1/sources/seed
```
Stop the API server after this if you only want background ingestion.

## 2) Option A: systemd user timer (Linux)
Install timer:
```bash
cd /Users/sugamgandhi/Desktop/stock_news
./scripts/install_systemd_user.sh
```

Check timer:
```bash
systemctl --user status stock-news-ingest.timer
systemctl --user list-timers --all | grep stock-news-ingest
```

Check job logs:
```bash
journalctl --user -u stock-news-ingest.service -n 100 --no-pager
```

## 3) Option B: cron (macOS/Linux)
Install cron entry:
```bash
cd /Users/sugamgandhi/Desktop/stock_news
./scripts/install_cron.sh
```

Verify:
```bash
crontab -l | grep run_ingest.sh
```

## 4) Runtime logs
Cron/systemd job writes to:
- `/Users/sugamgandhi/Desktop/stock_news/logs/ingest.log`

Tail logs:
```bash
tail -f /Users/sugamgandhi/Desktop/stock_news/logs/ingest.log
```

## 5) Validate ingestion health
```bash
curl "http://localhost:8000/v1/ingest/runs?limit=10"
curl "http://localhost:8000/v1/sources?status=active"
```
