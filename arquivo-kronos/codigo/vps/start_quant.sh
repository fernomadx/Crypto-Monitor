#!/usr/bin/env bash
# Sobe QUANT no Hetzner: teste → bot → lembrete cron watcher
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
cd "$REPO_DIR"

if [ ! -f vps/.env ]; then
  echo "Crie vps/.env a partir de vps/.env.example"
  exit 1
fi

set -a
source vps/.env
set +a

PY="${REPO_DIR}/vps/.venv/bin/python"
mkdir -p /data /var/log

echo "==> 1/3 Teste QUANT"
"$PY" vps/quant_test.py

echo "==> 2/3 Bot on-demand (quant_bot)"
if pgrep -f "vps/quant_bot.py" >/dev/null 2>&1; then
  echo "     quant_bot já rodando (pid $(pgrep -f 'vps/quant_bot.py' | head -1))"
else
  nohup "$PY" vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
  echo "     iniciado pid $! — log /data/quant_bot.log"
fi

echo "==> 3/3 Watcher"
echo "     Adicione ao crontab (a cada 5 min):"
echo "     */5 * * * * set -a && . $REPO_DIR/vps/.env && set +a && cd $REPO_DIR && $PY vps/quant_watcher.py >> /var/log/quant_watcher.log 2>&1"
echo ""
echo "Telegram: /help /quant /pesquisa bitcoin funding"
echo "Modo Kronos: QUANT_KRONOS_MODE=warn (teste) ou veto (produção)"
