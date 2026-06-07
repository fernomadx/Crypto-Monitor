#!/usr/bin/env bash
# Setup inicial na VPS (BTCCURSOR ou similar)
# Uso: sudo bash vps/setup_btccursor.sh

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
KRONOS_DIR="${KRONOS_DIR:-/opt/Kronos}"

echo "==> Dependências do sistema"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git

echo "==> Clone crypto-monitor (se ainda não existir)"
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone "https://github.com/fernomadx/Crypto-Monitor.git" "$REPO_DIR" || true
fi

echo "==> Clone Kronos"
if [ ! -d "$KRONOS_DIR/.git" ]; then
  git clone https://github.com/shiyu-coder/Kronos.git "$KRONOS_DIR"
fi

echo "==> venv Kronos"
python3 -m venv "$REPO_DIR/vps/.venv"
"$REPO_DIR/vps/.venv/bin/pip" install --upgrade pip
"$REPO_DIR/vps/.venv/bin/pip" install -r "$REPO_DIR/vps/requirements.txt"

if [ ! -f "$REPO_DIR/vps/.env" ]; then
  cp "$REPO_DIR/vps/.env.example" "$REPO_DIR/vps/.env"
  echo "Edite $REPO_DIR/vps/.env com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID"
fi

echo "==> Teste manual"
echo "  set -a && source $REPO_DIR/vps/.env && set +a"
echo "  cd $REPO_DIR && $REPO_DIR/vps/.venv/bin/python vps/kronos_signal.py"

echo "==> QUANT (opcional): edite vps/.env com LLMQUANT_API_KEY + TELEGRAM_*"
echo "    Bot: nohup $REPO_DIR/vps/.venv/bin/python $REPO_DIR/vps/quant_bot.py >> /data/quant_bot.log 2>&1 &"
echo "    Ver vps/QUANT.md"

echo "==> Pronto. Adicione vps/crontab.example ao crontab do usuário."
