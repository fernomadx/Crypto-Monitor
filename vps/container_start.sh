#!/bin/sh
# Entrypoint Railway: daemons + /health ANTES do supercronic (senão o healthcheck mata o container).
set -eu

mkdir -p /data /data/combo5 /data/mexc_analise /data/kronos/charts /data/huggingface

echo "start: QUANT bot"
/app/vps/ensure_quant_bot.sh || true

echo "start: MEXC Análise daemon"
/app/vps/ensure_mexc_analise.sh || true

echo "start: wait /health"
python /app/vps/wait_health.py || true

echo "start: boot Kronos/COMBO5 em background + supercronic"
/app/vps/railway_boot.sh &
exec supercronic /app/crontab
