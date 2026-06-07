#!/bin/sh
# Garante kronos_daemon rodando (modelo em RAM, alerta no candle 1H).
set -eu

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -z "${KRONOS_TELEGRAM_BOT_TOKEN:-}" ]; then
  exit 0
fi

mkdir -p /data

pids=$(ps -ef 2>/dev/null | grep -v grep | grep '[k]ronos_daemon.py' | awk '{print $2}' || true)
n=0
for _ in $pids; do n=$((n + 1)); done
if [ "$n" -gt 1 ]; then
  echo "ensure_kronos_daemon: $n instâncias — reiniciando uma só"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 3
elif [ "$n" -eq 1 ]; then
  exit 0
fi

nohup python /app/vps/kronos_daemon.py >> /data/kronos_daemon.log 2>&1 &
echo "ensure_kronos_daemon: iniciado pid $!"
