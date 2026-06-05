#!/bin/sh
# Após deploy Railway: avisa no Telegram e roda a 1ª previsão.
echo "Kronos boot: aguardando 45s (rede + volume)..."
sleep 45

python - <<'PY' || true
import os, sys
sys.path.insert(0, "/app")
try:
    from lib.kronos_config import apply_v31_defaults, format_boot_message
    apply_v31_defaults()
    from lib.telegram import send_kronos_alert
    send_kronos_alert("Serviço iniciado", format_boot_message())
except Exception as e:
    print("boot telegram:", e)
PY

echo "Kronos boot: cron assume previsões (evita 2x signal no deploy = OOM)"
echo "Próximo alerta: minuto 15 a cada 2h UTC (ex. 18:15, 20:15)"
