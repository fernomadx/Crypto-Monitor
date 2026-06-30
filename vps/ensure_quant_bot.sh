#!/bin/sh
# Garante uma única instância do quant_bot (Railway/Hetzner).
# Reinicia o bot quando o deploy muda (RAILWAY_DEPLOYMENT_ID ou hash do script).
set -eu

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  exit 0
fi

mkdir -p /data

BOT="/app/vps/quant_bot.py"
STAMP="/data/quant_bot.deploy_id"
if [ -f "$BOT" ]; then
  CURRENT="${RAILWAY_DEPLOYMENT_ID:-$(md5sum "$BOT" 2>/dev/null | awk '{print $1}')}"
else
  CURRENT="${RAILWAY_DEPLOYMENT_ID:-unknown}"
fi
STORED=""
[ -f "$STAMP" ] && STORED=$(cat "$STAMP")

pids=$(ps -ef 2>/dev/null | grep -v grep | grep '[q]uant_bot.py' | awk '{print $2}' || true)
n=0
for _ in $pids; do n=$((n + 1)); done

if [ "$STORED" != "$CURRENT" ]; then
  if [ "$n" -gt 0 ]; then
    echo "ensure_quant_bot: novo deploy ($CURRENT) — reiniciando bot"
    for pid in $pids; do kill "$pid" 2>/dev/null || true; done
    sleep 2
  fi
  echo "$CURRENT" > "$STAMP"
  n=0
elif [ "$n" -gt 1 ]; then
  echo "ensure_quant_bot: $n instâncias — reiniciando uma só"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 2
  n=0
elif [ "$n" -eq 1 ]; then
  exit 0
fi

nohup python "$BOT" >> /data/quant_bot.log 2>&1 &
echo "ensure_quant_bot: iniciado pid $! (deploy $CURRENT)"
