#!/usr/bin/env bash
# Instalação completa Kronos na VPS — rode UMA vez como root ou com sudo:
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/vps/install.sh | sudo bash
# Ou, com repo local:
#   sudo REPO_DIR=/opt/crypto-monitor bash vps/install.sh
#
# Requer: vps/.env com KRONOS_TELEGRAM_BOT_TOKEN + KRONOS_TELEGRAM_CHAT_ID (bot dedicado BTCCURSOR)

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
KRONOS_DIR="${KRONOS_DIR:-/opt/Kronos}"
REPO_URL="${REPO_URL:-https://github.com/fernomadx/Crypto-Monitor.git}"
BRANCH="${BRANCH:-main}"
CRON_SCHEDULE="${CRON_SCHEDULE:-15 * * * *}"
LOG_FILE="${LOG_FILE:-/var/log/kronos_signal.log}"

echo "=== Kronos VPS install ==="
echo "REPO_DIR=$REPO_DIR"
echo "KRONOS_DIR=$KRONOS_DIR"

echo "==> Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git \
  libgomp1 2>/dev/null || apt-get install -y -qq python3 python3-venv python3-pip git

echo "==> Repositório crypto-monitor"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch origin "$BRANCH"
  git -C "$REPO_DIR" checkout "$BRANCH"
  git -C "$REPO_DIR" pull origin "$BRANCH"
else
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$REPO_DIR"
fi

echo "==> Repositório Kronos"
if [ -d "$KRONOS_DIR/.git" ]; then
  git -C "$KRONOS_DIR" pull --ff-only || true
else
  git clone --depth 1 https://github.com/shiyu-coder/Kronos.git "$KRONOS_DIR"
fi

echo "==> Python venv + dependências (pode demorar — PyTorch)"
python3 -m venv "$REPO_DIR/vps/.venv"
"$REPO_DIR/vps/.venv/bin/pip" install --upgrade pip wheel
"$REPO_DIR/vps/.venv/bin/pip" install -r "$REPO_DIR/vps/requirements.txt"

mkdir -p "$REPO_DIR/vps/charts" "$REPO_DIR/data"
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="$REPO_DIR/vps/kronos_signal.log"

if [ ! -f "$REPO_DIR/vps/.env" ]; then
  if [ -f "$REPO_DIR/vps/.env.example" ]; then
    cp "$REPO_DIR/vps/.env.example" "$REPO_DIR/vps/.env"
  fi
  echo ""
  echo "ERRO: Configure $REPO_DIR/vps/.env antes de continuar (vps/BTCCURSOR.md):"
  echo "  KRONOS_TELEGRAM_BOT_TOKEN=..."
  echo "  KRONOS_TELEGRAM_CHAT_ID=..."
  echo "  DB_PATH=$REPO_DIR/data/kronos_vps.db"
  echo "  KRONOS_PATH=$KRONOS_DIR"
  exit 1
fi

if ! grep -qE '^KRONOS_TELEGRAM_BOT_TOKEN=.+' "$REPO_DIR/vps/.env" 2>/dev/null; then
  echo "AVISO: KRONOS_TELEGRAM_BOT_TOKEN ausente — usará TELEGRAM_* (mesmo bot do Railway)."
fi

# Garante KRONOS_PATH no .env
if ! grep -q '^KRONOS_PATH=' "$REPO_DIR/vps/.env"; then
  echo "KRONOS_PATH=$KRONOS_DIR" >> "$REPO_DIR/vps/.env"
fi

PY="$REPO_DIR/vps/.venv/bin/python"
RUN_WRAPPER="$REPO_DIR/vps/run_kronos.sh"

cat > "$RUN_WRAPPER" << EOF
#!/usr/bin/env bash
set -a
source "$REPO_DIR/vps/.env"
set +a
cd "$REPO_DIR"
exec "$PY" "$REPO_DIR/vps/kronos_signal.py"
EOF
chmod +x "$RUN_WRAPPER"

if [ "${KRONOS_VPS_ENABLED:-0}" = "1" ]; then
  echo "==> KRONOS_VPS_ENABLED=1 ignorado — Kronos não corre na Hetzner."
fi
echo "==> Kronos cron NÃO instalado (casa única = Railway)."
bash "$REPO_DIR/vps/hetzner_disable_kronos.sh" 2>/dev/null || true

echo ""
echo "=== Instalação concluída ==="
echo "Kronos: OFF nesta VPS (só Railway). COMBO5/MEXC Análise podem ficar aqui."
