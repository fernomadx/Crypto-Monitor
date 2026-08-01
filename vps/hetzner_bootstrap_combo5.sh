#!/usr/bin/env bash
# Bootstrap COMBO5 na Hetzner — rode na Console (root):
#   curl -fsSL <URL> | bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKcGa0Tr8FtHKqrcvGXIjE+HAjmTIdDD3rrTAvSHZUvi cursor-trade-desk@20260731'
BRANCH="${COMBO5_BRANCH:-main}"

echo "=== COMBO5 bootstrap @ $REPO_DIR ==="

mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
grep -qxF "$PUBKEY" ~/.ssh/authorized_keys || echo "$PUBKEY" >> ~/.ssh/authorized_keys
echo "  ✅ SSH pubkey do agent instalada"

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone https://github.com/fernomadx/Crypto-Monitor.git "$REPO_DIR"
fi

cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH" || git checkout -B "$BRANCH" "origin/$BRANCH"
git reset --hard "origin/$BRANCH"

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
upsert TRADE_DESK_ENABLED 1
upsert TRADE_DESK_MIN_CONFIDENCE 0.55

mkdir -p /data/combo5
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
chmod +x "$REPO_DIR/vps/run_combo5.sh" "$REPO_DIR/vps/combo5_signal.py"

touch /var/log/combo5.log
CRON_COMBO="*/5 * * * * /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -vE 'combo5|run_combo5' > "$TMP" || true
echo "$CRON_COMBO" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "=== Teste imediato (1 ciclo) ==="
set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a
"$REPO_DIR/vps/.venv/bin/python" "$REPO_DIR/vps/combo5_signal.py" || true
echo
echo "=== COMBO5 no ar ==="
echo "  cron: a cada 5 min"
echo "  log:  tail -f /var/log/combo5.log"
echo "  Telegram: alertas [COMBO5] (usa KRONOS_TELEGRAM_* ou TELEGRAM_*)"
crontab -l | grep -E 'combo5|run_combo5' || true
