#!/bin/sh
# Backup se o daemon não gerou previsão no fechamento do candle (~8 min após :00 UTC).
set -eu

STAMP="${KRONOS_LAST_OK:-/data/kronos.last_ok}"
MAX_AGE_SEC="${KRONOS_BACKUP_MAX_AGE_SEC:-3300}"  # 55 min
LOG="${1:-/data/kronos.log}"

if [ -f "$STAMP" ]; then
  now=$(date +%s)
  mtime=$(stat -c %Y "$STAMP" 2>/dev/null || stat -f %m "$STAMP")
  age=$((now - mtime))
  if [ "$age" -lt "$MAX_AGE_SEC" ]; then
    exit 0
  fi
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: sem OK recente — disparando kronos_candle_cron" >> "$LOG"
exec /app/vps/kronos_candle_cron.sh "$LOG"
