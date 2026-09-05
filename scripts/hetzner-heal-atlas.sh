#!/usr/bin/env bash
# Recupera ATLAS HTTP 502 no Hetzner 77 (Pingora → :8001).
# NÃO destroi volumes, NÃO recria containers, NÃO mexe em fundos Senpi.
#
# Console (root@77.42.126.222):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-heal-atlas.sh | sudo bash
set -euo pipefail

echo "=== Heal ATLAS @ $(hostname) ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
echo "Host IPs: $(hostname -I 2>/dev/null || true)"
if ! { curl -sf --max-time 3 "http://127.0.0.1:8001/health" >/dev/null 2>&1 \
  || docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qiE 'atlas|pingora' \
  || [ -e /root/.hermes/scripts/atlas-watchdog.sh ]; }; then
  echo "  ⚠️ Este host não parece o ATLAS (77.42.126.222). Abortando sem mudanças."
  exit 0
fi

atlas_ok() {
  curl -sf --max-time 8 "http://127.0.0.1:8001/health" >/dev/null 2>&1
}

echo "-- :8001/health --"
if atlas_ok; then
  echo "  ✅ ATLAS :8001 já responde"
else
  echo "  ❌ ATLAS :8001 sem health — tentando restart conservador"
fi

echo "-- docker --"
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | head -40 || true
  mapfile -t names < <(docker ps -a --format '{{.Names}}' | grep -iE 'atlas|pingora' || true)
  if [ "${#names[@]}" -eq 0 ]; then
    echo "  ⚠️ nenhum container atlas/pingora listado"
  else
    for name in "${names[@]}"; do
      echo "  → docker restart $name (sem recreate)"
      docker restart "$name" || true
    done
    sleep 4
  fi
else
  echo "  ⚠️ docker não encontrado"
fi

echo "-- proxy host --"
for svc in nginx caddy pingora; do
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^${svc}\.service"; then
    echo "  → systemctl restart $svc"
    systemctl restart "$svc" || true
  fi
done

WATCHDOG="/root/.hermes/scripts/atlas-watchdog.sh"
if [ -x "$WATCHDOG" ]; then
  echo "  → atlas-watchdog --force"
  "$WATCHDOG" --force || true
elif [ -f "$WATCHDOG" ]; then
  bash "$WATCHDOG" --force || true
else
  echo "  ⚠️ watchdog ausente: $WATCHDOG"
fi

echo "-- :8001/health (depois) --"
if atlas_ok; then
  echo "  ✅ ATLAS :8001 OK"
  curl -sS --max-time 8 "http://127.0.0.1:8001/health" || true
  echo
else
  echo "  ❌ ATLAS :8001 ainda falhou — veja RESCUE.md em fernomadx/atlas-kronos-ops"
  echo "     docker logs (últimas 80 linhas, se houver container atlas):"
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -i atlas | head -3 | while read -r n; do
    echo "     === $n ==="
    docker logs --tail 80 "$n" 2>&1 || true
  done
fi

echo "=== Heal ATLAS concluído ==="
