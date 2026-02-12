#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_SCRIPT="$ROOT_DIR/scripts/run_ingest.sh"
CRON_EXPR="*/5 * * * *"
CRON_LINE="$CRON_EXPR $RUN_SCRIPT"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

crontab -l 2>/dev/null | grep -v -F "$RUN_SCRIPT" > "$TMP_FILE" || true
echo "$CRON_LINE" >> "$TMP_FILE"
crontab "$TMP_FILE"

echo "Cron schedule installed: $CRON_LINE"
echo "Current crontab:"
crontab -l
