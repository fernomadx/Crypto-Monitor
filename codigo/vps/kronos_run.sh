#!/bin/sh
# Evita 2 execuções simultâneas (boot + cron) que derrubam o container.
# Uso: kronos_run.sh [log] [tf]
#   tf: 1h | 4h | 1d (opcional — cron no fechamento do candle)
LOCK="/data/kronos.signal.lock"
LOG="${1:-/data/kronos.log}"
TF="${2:-}"

if [ -f "$LOCK" ]; then
  old_pid=$(cat "$LOCK" 2>/dev/null)
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skip: kronos_signal já rodando (pid $old_pid) tf=${TF:-all}" >> "$LOG"
    exit 0
  fi
fi

(
  echo $$ > "$LOCK"
  trap 'rm -f "$LOCK"' EXIT
  cd /app
  if [ -n "$TF" ]; then
    exec python /app/vps/kronos_signal.py --tf "$TF"
  else
    exec python /app/vps/kronos_signal.py
  fi
) >> "$LOG" 2>&1
