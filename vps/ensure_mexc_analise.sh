#!/bin/sh
# Watchdog do daemon 📊 MEXC Análise (poll 15s).
set -eu

if [ "${MEXC_ANALISE_BOT:-1}" = "0" ] || [ "${MEXC_ANALISE_BOT:-1}" = "false" ]; then
  exit 0
fi

BOT="${BOT:-/app/vps/mexc_analise_bot.py}"
if [ ! -f "$BOT" ]; then
  BOT="$(cd "$(dirname "$0")/.." && pwd)/vps/mexc_analise_bot.py"
fi

mkdir -p /data/mexc_analise
pids=$(ps -ef 2>/dev/null | grep -v grep | grep '[m]exc_analise_bot.py' | awk '{print $2}' || true)
n=0
for _ in $pids; do n=$((n + 1)); done

if [ "$n" -gt 1 ]; then
  echo "ensure_mexc_analise: $n instâncias — reiniciando uma só"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 2
  n=0
elif [ "$n" -eq 1 ]; then
  exit 0
fi

nohup python "$BOT" >> /data/mexc_analise.log 2>&1 &
echo "ensure_mexc_analise: iniciado pid $!"
