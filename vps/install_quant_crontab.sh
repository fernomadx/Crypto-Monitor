#!/usr/bin/env bash
# Instala cron do QUANT watcher (idempotente, sem prompt).
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
PY="${PY:-$REPO_DIR/vps/.venv/bin/python}"
MARKER="# quant-watcher-crypto-monitor"

line="*/5 * * * * set -a && . $REPO_DIR/vps/.env && set +a && cd $REPO_DIR && $PY vps/quant_watcher.py >> /var/log/quant_watcher.log 2>&1 $MARKER"

if crontab -l 2>/dev/null | grep -qF "$MARKER"; then
  echo "cron QUANT watcher já instalado"
  exit 0
fi

( crontab -l 2>/dev/null || true; echo "$line" ) | crontab -
echo "cron QUANT watcher instalado (5 min)"
