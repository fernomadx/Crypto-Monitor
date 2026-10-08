#!/usr/bin/env bash
# One-shot Console paste for root@77.42.126.222
# Public entrypoint (Crypto-Monitor). Full playbook: fernomadx/atlas-kronos-ops RESCUE.md
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/console-rescue-77.sh | bash
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/root/rescue-${STAMP}"
APOLO_DIR="${APOLO_DIR:-/root/trading-bot}"
DEPLOY_PUB='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDT5atqz6fydTO+E6U65+mkEPBWNyJP0MwFmOShVWfsX cursor-agent@crypto-monitor'
BASE='https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts'

mkdir -p "$OUT"
exec > >(tee -a "$OUT/console.log") 2>&1
echo "=== console-rescue-77 @ ${STAMP} ==="
uname -a || true

echo "== 1) deploy pubkey =="
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
grep -qxF "$DEPLOY_PUB" /root/.ssh/authorized_keys || echo "$DEPLOY_PUB" >> /root/.ssh/authorized_keys
echo "pubkey ok"

echo "== 2) ATLAS heal =="
curl -fsSL --max-time 30 "$BASE/hetzner-heal-atlas.sh" -o "$OUT/hetzner-heal-atlas.sh"
bash "$OUT/hetzner-heal-atlas.sh" | tee "$OUT/atlas-heal.txt" || true
curl -sS --max-time 8 "http://127.0.0.1:8001/health" | tee "$OUT/atlas-health-after.txt" \
  || echo "ATLAS health still down" | tee "$OUT/atlas-health-after.txt"

echo "== 3) APOLO snapshot =="
if [ -d "$APOLO_DIR" ]; then
  ( cd "$APOLO_DIR"
    ls -la | tee "$OUT/apolo-ls.txt" || true
    crontab -l 2>/dev/null | tee "$OUT/crontab.txt" || true
    if [ -f bot.py ]; then python3 bot.py status 2>&1 | tee "$OUT/apolo-status.txt" || true
    else echo "bot.py missing" | tee "$OUT/apolo-status.txt"; fi
    [ -f state.json ] && cp -a state.json "$OUT/state.json" || true
  )
else
  echo "APOLO dir missing: $APOLO_DIR" | tee "$OUT/apolo-status.txt"
fi

echo "== 4) APOLO dump =="
curl -fsSL --max-time 30 "$BASE/dump-apolo-to-github.sh" -o "$OUT/dump-apolo-to-github.sh"
bash "$OUT/dump-apolo-to-github.sh" | tee "$OUT/apolo-dump.txt" || true

echo "== 5) summary =="
ls -la "$OUT" || true
echo "ATLAS:"; cat "$OUT/atlas-health-after.txt" 2>/dev/null || true
echo "APOLO status (head):"; head -n 40 "$OUT/apolo-status.txt" 2>/dev/null || true
echo "=== done — paste $OUT/console.log into Cursor ==="
