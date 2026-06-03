#!/bin/sh
# Após deploy Railway: roda um sinal logo (usa TELEGRAM_* e TICKERS do projeto).
set -e
echo "Kronos boot: aguardando 30s para rede..."
sleep 30
echo "Kronos boot: primeira execução..."
python /app/vps/kronos_signal.py || echo "Kronos boot: falhou (ver logs) — cron tentará de novo em 4h"
