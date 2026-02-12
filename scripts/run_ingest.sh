#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT_DIR/apps/api"
VENV_DIR="$API_DIR/.venv"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/ingest.log"
LOCK_DIR="$LOG_DIR/ingest.lock.d"

mkdir -p "$LOG_DIR"

cd "$API_DIR"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf '[%s] ingest skipped: previous run still active\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> "$LOG_FILE"
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

if ! python -c "import fastapi, feedparser" >/dev/null 2>&1; then
  python -m pip install -q -r requirements.txt
fi

# Seed source registry if this is a fresh DB.
python - <<'PY' >> "$LOG_FILE" 2>&1
import json
from pathlib import Path
from app.db import init_db, get_conn

init_db()
config_path = Path("/Users/sugamgandhi/Desktop/stock_news/config/sources.json")

with get_conn() as conn:
    count = conn.execute("SELECT COUNT(1) AS c FROM sources").fetchone()["c"]
    if int(count) == 0 and config_path.exists():
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        for source in payload.get("sources", []):
            conn.execute(
                """
                INSERT INTO sources (
                    name,
                    feed_url,
                    polling_interval_minutes,
                    status,
                    trust_score,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    feed_url = excluded.feed_url,
                    polling_interval_minutes = excluded.polling_interval_minutes,
                    status = excluded.status,
                    trust_score = excluded.trust_score,
                    updated_at = datetime('now')
                """,
                (
                    source["name"],
                    source["feed_url"],
                    int(source.get("polling_interval_minutes", 5)),
                    source.get("status", "active"),
                    int(source.get("trust_score", 50)),
                ),
            )
        print("seeded sources from config")
PY

STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
python -m app.cli ingest --trigger-type scheduled >> "$LOG_FILE" 2>&1
printf '[%s] scheduled ingest completed\n' "$STARTED_AT" >> "$LOG_FILE"
