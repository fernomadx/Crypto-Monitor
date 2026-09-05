#!/usr/bin/env bash
# Mata o bot CCXT legado na Hetzner 204 (📊 MEXC Análise → RequestTimeout).
# NÃO toca no daemon novo: vps/mexc_analise_bot.py (Railway).
#
# Console (root):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-kill-legacy-mexc.sh | sudo bash
set -euo pipefail

kill_legacy_mexc_ccxt() {
  echo "=== Matando CCXT legado (crypto-mexc-bot / crypto-chart-analyzer) ==="

  if command -v systemctl >/dev/null 2>&1; then
    for unit in crypto-mexc-bot crypto-mexc crypto-chart-analyzer mexc-bot; do
      if systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^${unit}\.service"; then
        systemctl stop "${unit}.service" 2>/dev/null || true
        systemctl disable "${unit}.service" 2>/dev/null || true
        echo "  ✅ systemd ${unit} stop+disable"
      fi
    done
  fi

  # Processos do analyzer antigo — padrões explícitos para não matar mexc_analise_bot.py
  pkill -f '/opt/crypto-chart-analyzer' 2>/dev/null || true
  pkill -f 'crypto-mexc-bot' 2>/dev/null || true
  pkill -f 'crypto_chart_analyzer' 2>/dev/null || true
  # CCXT apontando para api.mexc.com/api/v1/contract/kline (string do RequestTimeout)
  pkill -f 'ccxt.*mexc' 2>/dev/null || true

  if crontab -l 2>/dev/null | grep -qE 'crypto-chart-analyzer|crypto-mexc-bot|crypto-mexc '; then
    crontab -l 2>/dev/null \
      | grep -vE 'crypto-chart-analyzer|crypto-mexc-bot|crypto-mexc ' \
      | crontab - 2>/dev/null || true
    echo "  ✅ cron legado MEXC removido"
  else
    echo "  ✅ cron legado MEXC ausente"
  fi

  leftover="$(ps -ef | grep -E 'crypto-chart-analyzer|crypto-mexc-bot' | grep -v grep || true)"
  if [ -n "$leftover" ]; then
    echo "  ⚠️ ainda listado:"
    echo "$leftover" | sed 's/^/      /'
  else
    echo "  ✅ nenhum processo CCXT legado"
  fi
}

kill_legacy_mexc_ccxt
