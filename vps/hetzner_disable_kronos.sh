#!/usr/bin/env bash
# Desativa Kronos na Hetzner — o único ambiente ativo é o Railway.
# Rode na VPS: bash vps/hetzner_disable_kronos.sh
# Ou via curl:
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/vps/hetzner_disable_kronos.sh | sudo bash
# Trigger: GitHub Actions "Disable Kronos on VPS" (push em main).
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"

echo "=== Desativando Kronos na Hetzner (Railway é o único ativo) ==="

if crontab -l 2>/dev/null | grep -qE 'kronos|run_kronos'; then
  crontab -l 2>/dev/null \
    | grep -vE 'kronos|run_kronos' \
    | crontab - 2>/dev/null || true
  echo "  ✅ Cron Kronos removido"
else
  echo "  ✅ Cron Kronos já estava ausente"
fi

pkill -f 'kronos_signal.py' 2>/dev/null || true
pkill -f 'kronos_daemon.py' 2>/dev/null || true
pkill -f 'kronos_scorecard.py' 2>/dev/null || true
pkill -f 'kronos_daily_report.py' 2>/dev/null || true

if [ -f "$REPO_DIR/vps/.env" ]; then
  if grep -q '^KRONOS_VPS_ENABLED=' "$REPO_DIR/vps/.env" 2>/dev/null; then
    sed -i 's/^KRONOS_VPS_ENABLED=.*/KRONOS_VPS_ENABLED=0/' "$REPO_DIR/vps/.env"
  else
    echo "KRONOS_VPS_ENABLED=0" >> "$REPO_DIR/vps/.env"
  fi
  echo "  ✅ KRONOS_VPS_ENABLED=0 em vps/.env"
fi

echo ""
echo "=== Kronos OFF nesta VPS. QUANT/monitor podem continuar no Railway. ==="
