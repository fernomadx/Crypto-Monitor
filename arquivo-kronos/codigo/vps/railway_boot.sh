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

echo "QUANT boot: bot + watcher..."
python - <<'PY' || true
import os, sys
sys.path.insert(0, "/app")
os.environ.setdefault("QUANT_STATE_PATH", "/data/quant_state.json")
os.environ.setdefault("QUANT_KRONOS_MODE", "warn")
try:
    from lib.telegram import send_quant_alert
    send_quant_alert(
        "Online",
        "Bot QUANT ativo no Railway.\n"
        "Comandos: <code>/ping</code> <code>/quant</code> "
        "<code>/pesquisa sua pergunta</code>\n"
        "<i>Canal [QUANT] separado do [KRONOS].</i>",
    )
except Exception as e:
    print("quant boot telegram:", e)
PY

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "QUANT: skip quant_bot (sem TELEGRAM_*)"
else
  if ! pgrep -f "vps/quant_bot.py" >/dev/null 2>&1; then
    nohup python /app/vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
    echo "QUANT bot pid $!"
  else
    echo "QUANT bot já rodando"
  fi
fi
