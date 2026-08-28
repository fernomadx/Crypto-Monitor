#!/usr/bin/env bash
# Reativa COMBO5 na Hetzner e desliga quant_bot duplicado (Telegram 409).
# Console Hetzner (root):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-heal-bots.sh | sudo bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
BRANCH="${COMBO5_BRANCH:-main}"
AGENT_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDURnwyitmfIBdkbSLLNpg7GlXglTK2V7unbFWPN4H/t cursor-hetzner-heal@20260827'
LEGACY_PUBKEYS=(
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINmDK/J6uK0c+KqAU+1E5oRD05lYoNtE6YvndNF8cy3L cursor-combo5@20260804'
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKcGa0Tr8FtHKqrcvGXIjE+HAjmTIdDD3rrTAvSHZUvi cursor-trade-desk@20260731'
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDT5atqz6fydTO+E6U65+mkEPBWNyJP0MwFmOShVWfsX cursor-agent@crypto-monitor'
)

echo "=== Hetzner heal bots @ $REPO_DIR ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
echo "Host: $(hostname) IPs: $(hostname -I 2>/dev/null || true)"

mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
for pk in "$AGENT_PUBKEY" "${LEGACY_PUBKEYS[@]}"; do
  grep -qxF "$pk" ~/.ssh/authorized_keys || echo "$pk" >> ~/.ssh/authorized_keys
done
echo "  ✅ SSH pubkeys"

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone https://github.com/fernomadx/Crypto-Monitor.git "$REPO_DIR"
fi
cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH" || git checkout -B "$BRANCH" "origin/$BRANCH"
git reset --hard "origin/$BRANCH"
echo "  ✅ git $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"

ENV_FILE="$REPO_DIR/vps/.env"
touch "$ENV_FILE"
upsert() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

# Comandos /ping /combo5 /quant: só o Railway faz getUpdates.
# COMBO5 cron continua aqui (alertas de entrada/saída).
upsert QUANT_BOT_ENABLED 0
upsert COMBO5_ENABLED 1
upsert COMBO5_STATE_DIR /data/combo5
upsert MEXC_ANALISE_BOT 1
mkdir -p /data/combo5 /data /data/mexc_analise
chmod 755 /data/combo5 /data/mexc_analise

if [ ! -x "$REPO_DIR/vps/.venv/bin/python" ]; then
  python3 -m venv "$REPO_DIR/vps/.venv"
  "$REPO_DIR/vps/.venv/bin/pip" install -q -U pip
fi
"$REPO_DIR/vps/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt" || true
"$REPO_DIR/vps/.venv/bin/pip" install -q pandas numpy requests python-dotenv || true

cat > "$REPO_DIR/vps/run_combo5.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
set -a
# shellcheck disable=SC1091
source "$REPO_DIR/vps/.env"
set +a
cd "$REPO_DIR"
exec "$REPO_DIR/vps/.venv/bin/python" "$REPO_DIR/vps/combo5_signal.py" "$@"
EOF
chmod +x "$REPO_DIR/vps/run_combo5.sh" "$REPO_DIR/vps/combo5_signal.py" \
  "$REPO_DIR/vps/mexc_analise_bot.py" "$REPO_DIR/vps/ensure_mexc_analise.sh" 2>/dev/null || true

# SSH: se UFW bloqueou 22, libera (Cloud Firewall do painel Hetzner é outro lugar)
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
  ufw allow OpenSSH >/dev/null 2>&1 || true
  echo "  ✅ UFW: OpenSSH permitido"
fi

echo "  → parando quant_bot (evita Telegram 409 com o Railway)"
pkill -f 'quant_bot.py' 2>/dev/null || true
sleep 1

touch /var/log/combo5.log /data/quant_bot.log /data/mexc_analise.log
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -vE 'combo5|run_combo5|ensure_quant_bot|quant_bot|mexc_analise' > "$TMP" || true
{
  echo "*/5 * * * * /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
  echo "10 * * * * COMBO5_FORCE_STATUS=1 /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
  echo "*/2 * * * * REPO_DIR=/opt/crypto-monitor /opt/crypto-monitor/vps/ensure_mexc_analise.sh >> /data/mexc_analise.log 2>&1"
} >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "  ✅ cron COMBO5 (5 min + :10 UTC) + watchdog MEXC Análise"

echo "  → subindo daemon 📊 MEXC Análise"
REPO_DIR="$REPO_DIR" BOT="$REPO_DIR/vps/mexc_analise_bot.py" \
  "$REPO_DIR/vps/ensure_mexc_analise.sh" || true

echo
echo "=== Diagnóstico ==="
echo "-- disk --"
df -h / /data 2>/dev/null || df -h /
echo "-- processes --"
ps -ef | grep -E 'quant_bot|combo5_signal|kronos_|mexc_analise' | grep -v grep || echo "  (nenhum processo bot listado)"
echo "-- crontab --"
crontab -l | grep -E 'combo5|quant_bot|kronos|mexc' || echo "  (sem linhas combo5/quant/kronos/mexc)"
echo "-- combo5 log --"
tail -n 20 /var/log/combo5.log 2>/dev/null || echo "  (sem log)"
echo "-- mexc_analise log --"
tail -n 20 /data/mexc_analise.log 2>/dev/null || echo "  (sem log)"

set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

echo
echo "=== Teste Telegram + 1 ciclo COMBO5 ==="
"$REPO_DIR/vps/.venv/bin/python" - <<'PY' || true
import os, sys
sys.path.insert(0, "/opt/crypto-monitor")
import requests
tok = (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("KRONOS_TELEGRAM_BOT_TOKEN") or "").strip()
if not tok:
    print("  ❌ sem TELEGRAM_* / KRONOS_TELEGRAM_* em vps/.env")
    raise SystemExit(0)
me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).json()
print("  bot:", me.get("result", {}).get("username"), "ok=", me.get("ok"))
wh = requests.get(f"https://api.telegram.org/bot{tok}/getWebhookInfo", timeout=15).json()
info = wh.get("result") or {}
print("  webhook:", info.get("url") or "(polling)")
try:
    from lib.telegram import send_combo5_alert
    send_combo5_alert(
        "Heal Hetzner",
        "VPS reativada.\n"
        "• COMBO5 cron 5 min + <code>:10</code> UTC\n"
        "• 📊 MEXC Análise daemon (BTC 1h)\n"
        "• <code>quant_bot</code> off aqui (comandos no Railway)\n",
    )
    print("  ✅ alerta [COMBO5] Heal enviado")
except Exception as exc:
    print("  ⚠️ Telegram send:", exc)
try:
    from lib.telegram import send
    send("📊 <b>MEXC Análise</b> reativada na Hetzner (heal).")
    print("  ✅ alerta MEXC Análise enviado")
except Exception as exc:
    print("  ⚠️ MEXC send:", exc)
PY

COMBO5_FORCE_STATUS=1 "$REPO_DIR/vps/.venv/bin/python" "$REPO_DIR/vps/combo5_signal.py" || true

echo
echo "=== Heal concluído ==="
echo "  git:  $(git -C "$REPO_DIR" rev-parse --short HEAD)"
echo "  COMBO5 cron + MEXC Análise daemon ativos; quant_bot off nesta VPS"
echo "  Telegram: [COMBO5] Heal Hetzner + 📊 MEXC Análise"
echo "  log:  tail -f /var/log/combo5.log"
