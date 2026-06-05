#!/bin/sh
# Após deploy Railway: avisa no Telegram e roda a 1ª previsão.
echo "Kronos boot: aguardando 45s (rede + volume)..."
sleep 45

python - <<'PY' || true
import os, sys
sys.path.insert(0, "/app")
try:
    from lib.kronos_config import format_boot_message
    from lib.telegram import send_kronos_alert
    send_kronos_alert("Serviço iniciado", format_boot_message())
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
