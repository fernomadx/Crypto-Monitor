#!/bin/sh
# Watchdog COMBO5 no Railway — se last_ok > 75 min, força 1 ciclo + alerta.
set -eu

if [ "${COMBO5_ENABLED:-1}" = "0" ] || [ "${COMBO5_ENABLED:-1}" = "false" ]; then
  exit 0
fi

mkdir -p /data/combo5
OK_FILE="/data/combo5/last_ok.txt"
STALE_MIN="${COMBO5_STALE_MINUTES:-75}"

need=0
if [ ! -f "$OK_FILE" ]; then
  need=1
else
  # GNU date / busybox: idade do ficheiro em segundos
  now=$(date +%s)
  mtime=$(date -r "$OK_FILE" +%s 2>/dev/null || stat -c %Y "$OK_FILE" 2>/dev/null || echo 0)
  age=$((now - mtime))
  limit=$((STALE_MIN * 60))
  if [ "$age" -gt "$limit" ]; then
    need=1
  fi
fi

if [ "$need" -eq 0 ]; then
  exit 0
fi

echo "ensure_combo5: last_ok stale — forçando ciclo"
COMBO5_FORCE_STATUS=1 python /app/vps/combo5_signal.py >> /data/combo5.log 2>&1 || true
