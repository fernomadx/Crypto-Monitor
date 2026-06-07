#!/bin/sh
# Garante uma única instância do quant_bot (Railway/Hetzner).
set -eu

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  exit 0
fi

mkdir -p /data

# Mata duplicatas (race no boot/cron)
pids=$(ps -ef 2>/dev/null | grep -v grep | grep '[q]uant_bot.py' | awk '{print $2}' || true)
n=0
for _ in $pids; do n=$((n + 1)); done
if [ "$n" -gt 1 ]; then
  echo "ensure_quant_bot: $n instâncias — reiniciando uma só"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 2
elif [ "$n" -eq 1 ]; then
  exit 0
fi

nohup python /app/vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
echo "ensure_quant_bot: iniciado pid $!"
