#!/bin/sh
# Garante quant_bot rodando (Railway/Hetzner). Usa ps — pgrep não existe no python:slim.
set -eu

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  exit 0
fi

if ps -ef 2>/dev/null | grep -v grep | grep -q '[q]uant_bot.py'; then
  exit 0
fi

mkdir -p /data
nohup python /app/vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
echo "ensure_quant_bot: iniciado pid $!"
