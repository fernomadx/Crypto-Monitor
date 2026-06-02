#!/usr/bin/env bash
# Instalação completa Kronos na VPS — rode UMA vez como root ou com sudo:
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/vps/install.sh | sudo bash
# Ou, com repo local:
#   sudo REPO_DIR=/opt/crypto-monitor bash vps/install.sh
#
# Requer: vps/.env com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (mesmo do Railway)

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
KRONOS_DIR="${KRONOS_DIR:-/opt/Kronos}"
REPO_URL="${REPO_URL:-https://github.com/fernomadx/Crypto-Monitor.git}"
BRANCH="${BRANCH:-main}"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 */4 * * *}"
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

mkdir -p "$REPO_DIR/vps/charts"
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="$REPO_DIR/vps/kronos_signal.log"

if [ ! -f "$REPO_DIR/vps/.env" ]; then
  if [ -f "$REPO_DIR/vps/.env.example" ]; then
    cp "$REPO_DIR/vps/.env.example" "$REPO_DIR/vps/.env"
  fi
  echo ""
  echo "ERRO: Configure $REPO_DIR/vps/.env antes de continuar:"
  echo "  TELEGRAM_BOT_TOKEN=..."
  echo "  TELEGRAM_CHAT_ID=..."
  echo "  KRONOS_PATH=$KRONOS_DIR"
  exit 1
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

echo "==> Cron ($CRON_SCHEDULE)"
CRON_LINE="$CRON_SCHEDULE $RUN_WRAPPER >> $LOG_FILE 2>&1"
(crontab -l 2>/dev/null | grep -v 'kronos_signal.py' | grep -v 'run_kronos.sh' || true; echo "$CRON_LINE") | crontab -

echo "==> Teste inicial (pode levar 10–20 min na 1ª vez — download do modelo)"
"$RUN_WRAPPER" && echo "==> Teste OK — alerta enviado ao Telegram" || {
  echo "==> Teste falhou — veja $LOG_FILE"
  tail -50 "$LOG_FILE" 2>/dev/null || true
  exit 1
}

echo ""
echo "=== Instalação concluída ==="
echo "Cron: $CRON_SCHEDULE"
echo "Log:  $LOG_FILE"
echo "Run:  $RUN_WRAPPER"
crontab -l | grep kronos || true
