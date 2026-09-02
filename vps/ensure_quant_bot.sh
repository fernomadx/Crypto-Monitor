#!/bin/sh
# Garante uma única instância do quant_bot (Railway/Hetzner).
# Reinicia o bot quando o deploy muda (RAILWAY_DEPLOYMENT_ID ou hash do script).
set -eu

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  exit 0
fi

# Hetzner não deve pollar o mesmo token do Railway (Telegram 409 mata /ping /combo5).
case "${QUANT_BOT_ENABLED:-1}" in
  0|false|no|off) exit 0 ;;
esac

mkdir -p /data

# O log chegou a ~800 MB com traceback de ReadTimeout a cada long-poll.
_rotate_if_huge() {
  log="$1"
  max="${2:-10485760}"
  if [ -f "$log" ]; then
    sz=$(wc -c < "$log" | tr -d '[:space:]')
    if [ "${sz:-0}" -gt "$max" ]; then
      mv "$log" "${log}.1" 2>/dev/null || true
      echo "ensure_quant_bot: rotacionou $log (${sz} bytes)"
    fi
  fi
}
_rotate_if_huge /data/quant_bot.log

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
