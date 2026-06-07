#!/bin/sh
# Cron horário: 1H sempre; 4H em 0,4,8,12,16,20 UTC (após fechamento do candle).
# Roda em sequência para não disputar o lock do kronos_run.sh.
LOG="${1:-/data/kronos.log}"

/app/vps/kronos_run.sh "$LOG" 1h

H=$(date -u +%H)
case "$H" in
  00|04|08|12|16|20) /app/vps/kronos_run.sh "$LOG" 4h ;;
esac
