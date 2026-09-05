#!/usr/bin/env bash
# Recupera HTTP 502 no BTCCURSOR (204) — nginx/streamlit/docker.
# NÃO mata mexc_analise_bot.py (Railway). NÃO destroi volumes.
#
# Console (root@204.168.179.200):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-heal-204.sh | sudo bash
set -euo pipefail

echo "=== Heal HTTP 204 @ $(hostname) ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
echo "Host IPs: $(hostname -I 2>/dev/null || true)"

http_code() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$1" 2>/dev/null || echo 000
}

code="$(http_code http://127.0.0.1/)"
echo "-- http://127.0.0.1/ → ${code} --"
if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ]; then
  echo "  ✅ nginx já responde ${code}"
  exit 0
fi

echo "  ⚠️ HTTP ${code} — restart conservador (nginx + backends óbvios)"

if command -v systemctl >/dev/null 2>&1; then
  for svc in nginx caddy streamlit crypto-web crypto-dashboard crypto-chart-analyzer; do
    if systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^${svc}\.service"; then
      echo "  → systemctl restart ${svc}"
      systemctl restart "${svc}" || true
    fi
  done
fi

if command -v docker >/dev/null 2>&1; then
  mapfile -t names < <(docker ps -a --format '{{.Names}}' | grep -iE 'streamlit|nginx|web|app|dashboard|chart' || true)
  if [ "${#names[@]}" -gt 0 ]; then
    for name in "${names[@]}"; do
      echo "  → docker restart $name"
      docker restart "$name" || true
    done
  else
    echo "  ℹ️ nenhum container web/streamlit listado"
  fi
fi

# Streamlit solto (dashboard), não o daemon MEXC novo
if pgrep -af 'streamlit' >/dev/null 2>&1; then
  echo "  → streamlit listado; sem pkill (evita matar sessão). Reinicie o unit se existir."
  pgrep -af 'streamlit' | sed 's/^/      /' || true
fi

sleep 3
code="$(http_code http://127.0.0.1/)"
echo "-- http://127.0.0.1/ (depois) → ${code} --"
if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ]; then
  echo "  ✅ HTTP recuperado"
else
  echo "  ⚠️ HTTP ainda ${code} — dashboard, não os bots Telegram (esses estão no Railway)"
fi
echo "=== Heal HTTP 204 concluído ==="
