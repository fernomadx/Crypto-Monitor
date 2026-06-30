#!/usr/bin/env bash
# Bootstrap + teste na Hetzner (cole na Console do servidor ou via SSH):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-bootstrap-test.sh | sudo bash
# Com previsão 1H (demora):
#   curl -fsSL ... | sudo bash -s -- --signal
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
KRONOS_DIR="${KRONOS_DIR:-/opt/Kronos}"
RUN_SIGNAL=0
for arg in "$@"; do
  [ "$arg" = "--signal" ] && RUN_SIGNAL=1
done

echo "=== Hetzner bootstrap + teste ==="

if [ "$(id -u)" -ne 0 ]; then
  echo "Execute com sudo/root"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip libgomp1 2>/dev/null \
  || apt-get install -y -qq git python3 python3-venv python3-pip

if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch origin main
  git -C "$REPO_DIR" checkout main
  git -C "$REPO_DIR" pull origin main
else
  git clone --branch main --depth 1 https://github.com/fernomadx/Crypto-Monitor.git "$REPO_DIR"
fi

if [ ! -f "$REPO_DIR/vps/.env" ]; then
  cp "$REPO_DIR/vps/.env.example" "$REPO_DIR/vps/.env"
  echo ""
  echo "ERRO: Edite $REPO_DIR/vps/.env (KRONOS_TELEGRAM_* ou TELEGRAM_*) e rode de novo."
  exit 1
fi

if [ ! -d "$KRONOS_DIR/.git" ]; then
  git clone --depth 1 https://github.com/shiyu-coder/Kronos.git "$KRONOS_DIR"
fi

if [ ! -x "$REPO_DIR/vps/.venv/bin/python" ]; then
  echo "==> Criando venv (PyTorch — pode demorar 10–20 min na 1ª vez)..."
  python3 -m venv "$REPO_DIR/vps/.venv"
  "$REPO_DIR/vps/.venv/bin/pip" install --upgrade pip wheel
  "$REPO_DIR/vps/.venv/bin/pip" install -r "$REPO_DIR/vps/requirements.txt"
else
  "$REPO_DIR/vps/.venv/bin/pip" install -r "$REPO_DIR/vps/requirements-railway.txt" -q
fi

grep -q '^KRONOS_PATH=' "$REPO_DIR/vps/.env" || echo "KRONOS_PATH=$KRONOS_DIR" >> "$REPO_DIR/vps/.env"
grep -q '^DB_PATH=' "$REPO_DIR/vps/.env" || echo "DB_PATH=$REPO_DIR/data/kronos_vps.db" >> "$REPO_DIR/vps/.env"
mkdir -p "$REPO_DIR/data" "$REPO_DIR/vps/charts"

# Kronos v4.0 — regras anti-perda (Hetzner BTCCURSOR)
apply_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$REPO_DIR/vps/.env" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$REPO_DIR/vps/.env"
  else
    echo "${key}=${val}" >> "$REPO_DIR/vps/.env"
  fi
}
apply_env KRONOS_LEVERAGE 3
apply_env KRONOS_MIN_TARGET_PCT 1.0
apply_env KRONOS_MIN_RR 3.0
apply_env KRONOS_MAX_STOP_PCT_4H 0.8
apply_env KRONOS_BIAS_THRESHOLD_PCT 0.40
apply_env KRONOS_SCORE_TICKERS BTC
apply_env QUANT_KRONOS_MODE veto
echo "==> Regras Kronos v4.0 aplicadas em vps/.env"

chmod +x "$REPO_DIR/vps/hetzner_test.sh"
export REPO_DIR
ARGS=(--score)
[ "$RUN_SIGNAL" -eq 1 ] && ARGS+=(--signal)
bash "$REPO_DIR/vps/hetzner_test.sh" "${ARGS[@]}"

echo ""
echo "=== Bootstrap concluído — veja Telegram [KRONOS] scorecard ==="
