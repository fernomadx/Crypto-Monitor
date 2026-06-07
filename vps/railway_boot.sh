#!/bin/sh
# Após deploy Railway: QUANT imediato + daemon Kronos (candle 1H/4H/1D).
set -eu

echo "QUANT boot: garantindo bot..."
/app/vps/ensure_quant_bot.sh || true

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
KRONOS_DAEMON_NOTIFY=1 nohup python /app/vps/kronos_daemon.py >> /data/kronos_daemon.log 2>&1 &
echo "kronos_daemon boot pid $! (notify=1)"

python - <<'PY' || true
import os, sys
sys.path.insert(0, "/app")
os.environ.setdefault("QUANT_STATE_PATH", "/data/quant_state.json")
os.environ.setdefault("QUANT_KRONOS_MODE", "warn")
try:
    from lib.telegram import send_quant_alert
    from lib.quant_impact import impact_alerts_enabled

    alerts_on = impact_alerts_enabled()
    thresh = os.environ.get("QUANT_IMPACT_THRESHOLD", "0.70")
    send_quant_alert(
        "Online",
        "Bot QUANT ativo no Railway.\n"
        "Comandos: <code>/ping</code> <code>/quant</code> "
        "<code>/pesquisa sua pergunta</code>\n"
        + (
            f"⚡ Alertas imediatos: <b>ON</b> (notícia forte ≥ {thresh})\n"
            if alerts_on
            else "Alertas imediatos: off (só digest 1H)\n"
        )
        + "<i>Canal [QUANT] separado do [KRONOS].</i>",
    )
except Exception as e:
    print("quant boot telegram:", e)
PY

/app/vps/ensure_quant_bot.sh || true
