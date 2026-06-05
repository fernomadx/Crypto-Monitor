#!/bin/sh
# Após deploy Railway: avisa no Telegram e inicia daemon (modelo em memória).
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

echo "Kronos boot: iniciando daemon (modelo em RAM, alerta no fechamento do candle)..."
nohup python /app/vps/kronos_daemon.py >> /data/kronos_daemon.log 2>&1 &
echo "Daemon PID $! — log em /data/kronos_daemon.log"
