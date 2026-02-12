#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC_DIR="$ROOT_DIR/ops/systemd"
UNIT_DST_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="stock-news-ingest.service"
TIMER_NAME="stock-news-ingest.timer"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found. Use cron installer instead: $ROOT_DIR/scripts/install_cron.sh"
  exit 1
fi

mkdir -p "$UNIT_DST_DIR"
cp "$UNIT_SRC_DIR/$SERVICE_NAME" "$UNIT_DST_DIR/$SERVICE_NAME"
cp "$UNIT_SRC_DIR/$TIMER_NAME" "$UNIT_DST_DIR/$TIMER_NAME"

systemctl --user daemon-reload
systemctl --user enable --now "$TIMER_NAME"
systemctl --user list-timers --all | grep -F "$TIMER_NAME" || true

echo "Systemd user timer installed: $TIMER_NAME"
echo "Check logs with: journalctl --user -u $SERVICE_NAME -n 100 --no-pager"
