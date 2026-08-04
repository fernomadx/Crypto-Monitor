#!/usr/bin/env bash
# Deploy COMBO5 + /combo5 na Hetzner — cole na Console (root):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-deploy-combo5.sh | sudo bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
BRANCH="${COMBO5_BRANCH:-main}"
# Chave do cloud agent (sessão atual) — permite SSH pós-bootstrap
AGENT_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINmDK/J6uK0c+KqAU+1E5oRD05lYoNtE6YvndNF8cy3L cursor-combo5@20260804'
# Chaves já usadas em bootstraps anteriores
LEGACY_PUBKEYS=(
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
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -vE 'combo5|run_combo5|ensure_quant_bot|quant_bot' > "$TMP" || true
{
  echo "*/5 * * * * /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
  echo "10 * * * * COMBO5_FORCE_STATUS=1 /opt/crypto-monitor/vps/run_combo5.sh >> /var/log/combo5.log 2>&1"
  echo "*/3 * * * * REPO_DIR=/opt/crypto-monitor /opt/crypto-monitor/vps/ensure_quant_bot_hetzner.sh >> /data/quant_bot.log 2>&1"
} >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "  ✅ cron COMBO5 (5 min + :10h) + quant_bot watchdog"

# Watchdog Hetzner: ensure_quant_bot.sh assume /app — wrapper local
cat > "$REPO_DIR/vps/ensure_quant_bot_hetzner.sh" <<'EOF'
#!/bin/sh
set -eu
REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
export PATH="$REPO_DIR/vps/.venv/bin:/usr/bin:/bin:$PATH"
if [ -f "$REPO_DIR/vps/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_DIR/vps/.env"
  set +a
fi
mkdir -p /data
BOT="$REPO_DIR/vps/quant_bot.py"
STAMP="/data/quant_bot.deploy_id"
CURRENT="$(cd "$REPO_DIR" && git rev-parse HEAD 2>/dev/null || echo unknown)"
STORED=""
[ -f "$STAMP" ] && STORED=$(cat "$STAMP")

pids=$(ps -ef 2>/dev/null | grep -v grep | grep '[q]uant_bot.py' | awk '{print $2}' || true)
n=0
for _ in $pids; do n=$((n + 1)); done

if [ "$STORED" != "$CURRENT" ] || [ "$n" -gt 1 ] || [ "$n" -eq 0 ]; then
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 2
  echo "$CURRENT" > "$STAMP"
  cd "$REPO_DIR"
  nohup "$REPO_DIR/vps/.venv/bin/python" "$BOT" >> /data/quant_bot.log 2>&1 &
  echo "ensure_quant_bot_hetzner: started pid $! sha $CURRENT"
fi
EOF
chmod +x "$REPO_DIR/vps/ensure_quant_bot_hetzner.sh"

# Reinicia quant_bot agora (código novo com /combo5)
bash "$REPO_DIR/vps/ensure_quant_bot_hetzner.sh" || true

echo "=== Teste imediato COMBO5 (1 ciclo) ==="
set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a
COMBO5_FORCE_STATUS=1 "$REPO_DIR/vps/.venv/bin/python" "$REPO_DIR/vps/combo5_signal.py" || true

echo
echo "=== COMBO5 + /combo5 no ar (Hetzner) ==="
echo "  git:  $(git -C "$REPO_DIR" rev-parse --short HEAD)"
echo "  cron: a cada 5 min + análise :10 UTC"
echo "  log:  tail -f /var/log/combo5.log"
echo "  bot:  /combo5  /analise  /c5"
crontab -l | grep -E 'combo5|quant_bot' || true
ps -ef | grep -v grep | grep '[q]uant_bot.py' || echo "  ⚠️ quant_bot não listado — confira TELEGRAM_* em vps/.env"
