#!/usr/bin/env bash
# Teste de saúde BTCCURSOR (Hetzner) — rode na VPS:
#   cd /opt/crypto-monitor && sudo bash vps/hetzner_test.sh
# Opções:
#   --signal   roda uma previsão Kronos (demora ~2–10 min)
#   --score    envia scorecard ao Telegram
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
RUN_SIGNAL=0
RUN_SCORE=0
for arg in "$@"; do
  case "$arg" in
    --signal) RUN_SIGNAL=1 ;;
    --score) RUN_SCORE=1 ;;
  esac
done

cd "$REPO_DIR"
PY="${REPO_DIR}/vps/.venv/bin/python"
[ -x "$PY" ] || PY=python3

echo "=== BTCCURSOR / Hetzner — teste $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "Host: $(hostname) | Repo: $REPO_DIR"
echo "Git: $(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo '?') $(git -C "$REPO_DIR" log -1 --oneline 2>/dev/null || true)"
echo

fail=0
ok() { echo "  ✅ $1"; }
warn() { echo "  ⚠️  $1"; fail=$((fail + 1)); }
bad() { echo "  ❌ $1"; fail=$((fail + 1)); }

# .env
if [ -f "$REPO_DIR/vps/.env" ]; then
  ok ".env presente"
  set -a
  # shellcheck disable=SC1091
  source "$REPO_DIR/vps/.env"
  set +a
else
  bad "vps/.env ausente — copie de vps/.env.example"
fi

if [ -n "${KRONOS_TELEGRAM_BOT_TOKEN:-}" ]; then
  ok "KRONOS_TELEGRAM_BOT_TOKEN configurado"
elif [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  warn "Usando TELEGRAM_* (mesmo bot Railway — pode duplicar alertas)"
else
  bad "Sem token Telegram (KRONOS_TELEGRAM_* ou TELEGRAM_*)"
fi

[ -n "${KRONOS_TELEGRAM_CHAT_ID:-${TELEGRAM_CHAT_ID:-}}" ] && ok "Chat ID OK" || bad "Chat ID ausente"

# Kronos repo
[ -d "${KRONOS_PATH:-/opt/Kronos}" ] && ok "Kronos em ${KRONOS_PATH:-/opt/Kronos}" || bad "KRONOS_PATH não encontrado"

# Cron — Kronos deve estar OFF na Hetzner (Railway é o único ativo)
if crontab -l 2>/dev/null | grep -qE 'kronos|run_kronos'; then
  bad "Cron Kronos ainda ativo — rode: bash vps/hetzner_disable_kronos.sh"
  crontab -l 2>/dev/null | grep -E 'kronos|run_kronos' | sed 's/^/      /'
elif [ "${KRONOS_VPS_ENABLED:-0}" = "1" ]; then
  warn "KRONOS_VPS_ENABLED=1 mas cron ausente"
else
  ok "Cron Kronos desligado (correto — Railway ativo)"
fi

# Logs recentes
for log in /var/log/kronos_signal.log /var/log/kronos_scorecard.log "$REPO_DIR/vps/kronos_signal.log"; do
  if [ -f "$log" ]; then
    echo
    echo "--- tail $log ---"
    tail -5 "$log" 2>/dev/null || true
  fi
done

echo
echo "=== APIs MEXC + Telegram ==="
export REPO_DIR
"$PY" << 'PY' || fail=$((fail + 1))
import os, sys
repo = os.environ.get("REPO_DIR", "/opt/crypto-monitor")
sys.path.insert(0, repo)
from lib.mexc_klines import fetch_klines
from lib.mexc_contract import fetch_contract_klines
import requests

spot = fetch_klines("BTCUSDT", "1h", 2)
print(f"MEXC spot: OK close={float(spot['close'].iloc[-1]):,.2f}")
fut = fetch_contract_klines("BTCUSDT", "1h", 2)
print(f"MEXC futures: OK close={float(fut['close'].iloc[-1]):,.2f}")

tok = os.environ.get("KRONOS_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
if tok:
    me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).json()
    u = me.get("result", {}).get("username", "?")
    print(f"Telegram bot: @{u} ok={me.get('ok')}")
PY

echo
echo "=== Scorecard / catálogo ==="
if [ -f "$REPO_DIR/vps/kronos_status.py" ]; then
  "$PY" "$REPO_DIR/vps/kronos_status.py" 2>&1 | head -40 || warn "kronos_status falhou"
else
  warn "kronos_status.py ausente — git pull origin main"
fi

if [ "$RUN_SCORE" -eq 1 ]; then
  echo
  echo "=== Scorecard Telegram ==="
  "$PY" "$REPO_DIR/vps/kronos_scorecard.py" --force || bad "kronos_scorecard falhou"
fi

if [ "$RUN_SIGNAL" -eq 1 ]; then
  echo
  echo "=== Previsão Kronos (1H) ==="
  if [ -x "$REPO_DIR/vps/run_kronos.sh" ]; then
    "$REPO_DIR/vps/run_kronos.sh" /var/log/kronos_signal.log 1h || bad "kronos_signal falhou"
  else
    "$PY" "$REPO_DIR/vps/kronos_signal.py" --tf 1h || bad "kronos_signal falhou"
  fi
  ok "Previsão enviada (verifique Telegram [KRONOS])"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "=== RESULTADO: OK ($fail avisos/erros) ==="
  exit 0
else
  echo "=== RESULTADO: $fail problema(s) — veja acima ==="
  exit 1
fi
