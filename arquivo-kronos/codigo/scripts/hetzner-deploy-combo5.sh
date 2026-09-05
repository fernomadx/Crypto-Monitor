#!/usr/bin/env bash
# Deploy COMBO5 + /combo5 na Hetzner — cole na Console (root):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-deploy-combo5.sh | sudo bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
BRANCH="${COMBO5_BRANCH:-main}"
# Chave do cloud agent (sessão atual) — permite SSH pós-bootstrap
AGENT_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDURnwyitmfIBdkbSLLNpg7GlXglTK2V7unbFWPN4H/t cursor-hetzner-heal@20260827'
# Chaves já usadas em bootstraps anteriores
LEGACY_PUBKEYS=(
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINmDK/J6uK0c+KqAU+1E5oRD05lYoNtE6YvndNF8cy3L cursor-combo5@20260804'
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKcGa0Tr8FtHKqrcvGXIjE+HAjmTIdDD3rrTAvSHZUvi cursor-trade-desk@20260731'
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDT5atqz6fydTO+E6U65+mkEPBWNyJP0MwFmOShVWfsX cursor-agent@crypto-monitor'
)

echo "=== Hetzner COMBO5 deploy @ $REPO_DIR (branch $BRANCH) ==="

mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
for pk in "$AGENT_PUBKEY" "${LEGACY_PUBKEYS[@]}"; do
  grep -qxF "$pk" ~/.ssh/authorized_keys || echo "$pk" >> ~/.ssh/authorized_keys
done
echo "  ✅ SSH pubkeys instaladas"

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

upsert COMBO5_ENABLED 1
upsert QUANT_BOT_ENABLED 0
upsert COMBO5_TICKERS BTC
upsert COMBO5_NOTIONAL_USDT 1000
upsert COMBO5_STATE_DIR /data/combo5
upsert COMBO5_MIN_STRENGTH_PCT 0.8
upsert COMBO5_MIN_DESK_CONF 0.65
upsert COMBO5_ATR_MIN_PCT 0.5
upsert COMBO5_ATR_MAX_PCT 1.1
upsert COMBO5_RR 2.0
upsert COMBO5_EXIT_ON_OPPOSITE 1
upsert COMBO5_EXIT_ON_WEAK 1
upsert COMBO5_HEARTBEAT_MINUTES 60
upsert TRADE_DESK_ENABLED 1
upsert TRADE_DESK_MIN_CONFIDENCE 0.55

mkdir -p /data/combo5 /data
chmod 755 /data/combo5

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
  "$REPO_DIR/vps/ensure_quant_bot.sh" "$REPO_DIR/vps/start_quant.sh" 2>/dev/null || true

touch /var/log/combo5.log /data/quant_bot.log
# quant_bot no mesmo TELEGRAM_BOT_TOKEN do Railway gera Telegram 409 e mata /ping /combo5.
pkill -f 'quant_bot.py' 2>/dev/null || true
if [ -f "$REPO_DIR/scripts/hetzner-kill-legacy-mexc.sh" ]; then
  bash "$REPO_DIR/scripts/hetzner-kill-legacy-mexc.sh"
else
  systemctl stop crypto-mexc-bot 2>/dev/null || true
  systemctl disable crypto-mexc-bot 2>/dev/null || true
  pkill -f '/opt/crypto-chart-analyzer' 2>/dev/null || true
  pkill -f 'crypto-mexc-bot' 2>/dev/null || true
fi
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -vE 'combo5|run_combo5|ensure_quant_bot|quant_bot|crypto-chart-analyzer|crypto-mexc' > "$TMP" || true
{
  echo "*/5 * * * * /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
  echo "10 * * * * COMBO5_FORCE_STATUS=1 /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
} >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "  ✅ cron COMBO5 (5 min + :10h) — quant_bot off (comandos no Railway)"

echo "=== Teste imediato COMBO5 (1 ciclo) ==="
set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a
COMBO5_FORCE_STATUS=1 "$REPO_DIR/vps/.venv/bin/python" "$REPO_DIR/vps/combo5_signal.py" || true

echo
echo "=== COMBO5 no ar (Hetzner) ==="
echo "  git:  $(git -C "$REPO_DIR" rev-parse --short HEAD)"
echo "  cron: a cada 5 min + análise :10 UTC"
echo "  log:  tail -f /var/log/combo5.log"
echo "  comandos Telegram (/combo5 /ping): Railway (QUANT_BOT_ENABLED=0 aqui)"
crontab -l | grep -E 'combo5|quant_bot' || true
if ps -ef | grep -v grep | grep -q '[q]uant_bot.py'; then
  echo "  ⚠️ quant_bot ainda listado — deve estar off nesta VPS (Telegram 409)"
else
  echo "  ✅ quant_bot off nesta VPS"
fi
if ps -ef | grep -v grep | grep -qE 'crypto-mexc-bot|/opt/crypto-chart-analyzer'; then
  echo "  ⚠️ CCXT legado ainda listado — RequestTimeout no Telegram"
else
  echo "  ✅ CCXT legado off nesta VPS"
fi
