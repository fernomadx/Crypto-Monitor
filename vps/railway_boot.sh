#!/bin/sh
# Após deploy Railway: avisa no Telegram e roda a 1ª previsão.
echo "Kronos boot: aguardando 45s (rede + volume)..."
sleep 45

# Reset manual único (NÃO é cron): crie /data/kronos.do_reset no Shell OU
# defina KRONOS_RESET_CATALOG_ONCE=1 nas Variables e remova após 1 deploy.
if [ -f /data/kronos.do_reset ] || [ "$KRONOS_RESET_CATALOG_ONCE" = "1" ]; then
  echo "Kronos boot: reset catálogo solicitado..."
  python /app/vps/kronos_reset_catalog.py --confirm >> /data/kronos.log 2>&1 || true
  rm -f /data/kronos.do_reset
fi

python - <<'PY' || true
import os, sys
sys.path.insert(0, "/app")
try:
    from lib.telegram import send_kronos_alert
    tickers = os.environ.get("TICKERS", "BTC,ETH,SOL")
    send_kronos_alert(
        "Serviço iniciado",
        f"Kronos no crypto-monitor.\nMoedas: <code>{tickers}</code>\nGerando 1ª previsão (pode levar 15–40 min em CPU)...",
    )
except Exception as e:
    print("boot telegram:", e)
PY

echo "Kronos boot: primeira execução..."
python /app/vps/kronos_signal.py >> /data/kronos.log 2>&1 || {
  echo "Kronos boot: falhou"
  python - <<'PY' || true
import sys
sys.path.insert(0, "/app")
from lib.telegram import send_kronos_alert
send_kronos_alert("Erro no boot", "Ver /data/kronos.log no Railway. Cron tenta de novo em 4h.")
PY
}
