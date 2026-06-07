#!/usr/bin/env bash
# Sobe QUANT completo — sem prompts (Hetzner / VPS).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR"

ENV_FILE="${QUANT_ENV_FILE:-$REPO_DIR/vps/.env}"
if [ ! -f "$ENV_FILE" ] && [ -f /data/quant.env ]; then
  ENV_FILE=/data/quant.env
fi
if [ ! -f "$ENV_FILE" ]; then
  cp "$REPO_DIR/vps/.env.example" "$REPO_DIR/vps/.env"
  ENV_FILE="$REPO_DIR/vps/.env"
  echo "AVISO: criado $ENV_FILE — preencha chaves se alertas não chegarem"
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

PY="${PY:-$REPO_DIR/vps/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi

DATA_ROOT="${DATA_ROOT:-/data}"
if ! mkdir -p "$DATA_ROOT" 2>/dev/null; then
  DATA_ROOT="$REPO_DIR/data"
  mkdir -p "$DATA_ROOT"
fi
# Sobrescreve .env se /data não existir neste host
export QUANT_STATE_PATH="$DATA_ROOT/quant_state.json"
export QUANT_BOT_OFFSET="$DATA_ROOT/quant_bot_offset.txt"
export QUANT_KRONOS_MODE="${QUANT_KRONOS_MODE:-warn}"

echo "==> 1/4 Teste QUANT"
"$PY" vps/quant_test.py || true

echo "==> 2/4 Bot on-demand"
_tok="${TELEGRAM_BOT_TOKEN:-}"
_chat="${TELEGRAM_CHAT_ID:-}"
if [ -z "$_tok" ] || [ -z "$_chat" ] || [[ "$_tok" == *your_* ]] || [[ "$_chat" == *your_* ]]; then
  echo "     SKIP bot — configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID em vps/.env"
else
  if pgrep -f "vps/quant_bot.py" >/dev/null 2>&1; then
    echo "     quant_bot já rodando (pid $(pgrep -f 'vps/quant_bot.py' | head -1))"
  else
    nohup "$PY" vps/quant_bot.py >> "$DATA_ROOT/quant_bot.log" 2>&1 &
    echo "     quant_bot pid $! — $DATA_ROOT/quant_bot.log"
  fi
fi

echo "==> 3/4 Cron watcher"
REPO_DIR="$REPO_DIR" PY="$PY" bash vps/install_quant_crontab.sh || echo "     SKIP cron (sem crontab?)"

echo "==> 4/4 Uma varredura de notícias agora"
"$PY" vps/quant_watcher.py || true

echo ""
echo "QUANT ativo. Telegram: /ping /quant /pesquisa <texto>"
echo "Modo Kronos: $QUANT_KRONOS_MODE"
