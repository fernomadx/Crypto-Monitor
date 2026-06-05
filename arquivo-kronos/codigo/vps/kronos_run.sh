#!/bin/sh
# Evita 2 execuções simultâneas (boot + cron) que derrubam o container.
LOCK="/data/kronos.signal.lock"
LOG="${1:-/data/kronos.log}"

if [ -f "$LOCK" ]; then
  old_pid=$(cat "$LOCK" 2>/dev/null)
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skip: kronos_signal já rodando (pid $old_pid)" >> "$LOG"
    exit 0
  fi
fi

(
  echo $$ > "$LOCK"
  trap 'rm -f "$LOCK"' EXIT
  cd /app && exec python /app/vps/kronos_signal.py
) >> "$LOG" 2>&1
