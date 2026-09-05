#!/usr/bin/env bash
# Teste de saúde BTCCURSOR (Hetzner) — rode na VPS:
#   cd /opt/crypto-monitor && sudo bash vps/hetzner_test.sh
# --signal / --score recusados: Kronos só no Railway.
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
note() { echo "  ℹ️  $1"; }
warn() { echo "  ⚠️  $1"; fail=$((fail + 1)); }
bad() { echo "  ❌ $1"; fail=$((fail + 1)); }

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
  note "Usando TELEGRAM_* (COMBO5 nesta VPS; comandos no Railway)"
else
  bad "Sem token Telegram (KRONOS_TELEGRAM_* ou TELEGRAM_*)"
fi

[ -n "${KRONOS_TELEGRAM_CHAT_ID:-${TELEGRAM_CHAT_ID:-}}" ] && ok "Chat ID OK" || bad "Chat ID ausente"

# Kronos paper só no Railway — /opt/Kronos ausente no 204 não é falha.
if [ -d "${KRONOS_PATH:-/opt/Kronos}" ]; then
  ok "Kronos em ${KRONOS_PATH:-/opt/Kronos} (não deve gerar [KRONOS] daqui)"
else
  note "KRONOS_PATH ausente — esperado (paper só no Railway)"
fi

if crontab -l 2>/dev/null | grep -qE 'kronos|run_kronos'; then
  bad "Cron Kronos ainda ativo — rode: bash vps/hetzner_disable_kronos.sh"
  crontab -l 2>/dev/null | grep -E 'kronos|run_kronos' | sed 's/^/      /'
elif [ "${KRONOS_VPS_ENABLED:-0}" = "1" ]; then
  bad "KRONOS_VPS_ENABLED=1 — Kronos só no Railway. Rode: bash vps/hetzner_disable_kronos.sh"
else
  ok "Cron Kronos desligado (correto — Railway ativo)"
fi

if crontab -l 2>/dev/null | grep -qE 'run_combo5|combo5_signal'; then
  ok "Cron COMBO5 ativo"
else
  warn "Cron COMBO5 ausente — rode: bash scripts/hetzner-heal-bots.sh"
fi

if ps -ef 2>/dev/null | grep -v grep | grep -q '[q]uant_bot.py'; then
  bad "quant_bot rodando aqui — Telegram 409 com o Railway. Mate-o (QUANT_BOT_ENABLED=0)"
elif [ "${QUANT_BOT_ENABLED:-0}" = "1" ]; then
  warn "QUANT_BOT_ENABLED=1 mas processo ausente"
else
  ok "quant_bot off nesta VPS (comandos no Railway)"
fi

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
print(f"MEXC futures 1h: OK close={float(fut['close'].iloc[-1]):,.2f}")
fut4 = fetch_contract_klines("BTCUSDT", "4h", 2)
print(f"MEXC futures 4h: OK close={float(fut4['close'].iloc[-1]):,.2f}")

tok = os.environ.get("KRONOS_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
if tok:
    me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).json()
    u = me.get("result", {}).get("username", "?")
    print(f"Telegram bot: @{u} ok={me.get('ok')}")
PY

echo
echo "=== Scorecard / catálogo (informativo — paper no Railway) ==="
if [ -f "$REPO_DIR/vps/kronos_status.py" ]; then
  # head fecha o pipe → SIGPIPE no python; não contar como falha.
  "$PY" "$REPO_DIR/vps/kronos_status.py" 2>&1 | head -40 || true
else
  note "kronos_status.py ausente — git pull origin main"
fi

if [ "$RUN_SCORE" -eq 1 ] || [ "$RUN_SIGNAL" -eq 1 ]; then
  echo
  bad "--signal/--score recusados: Kronos paper só no Railway (evita [KRONOS] duplicado)"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "=== RESULTADO: OK ($fail avisos/erros) ==="
  exit 0
else
  echo "=== RESULTADO: $fail problema(s) — veja acima ==="
  exit 1
fi
