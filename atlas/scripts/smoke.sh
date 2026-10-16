#!/usr/bin/env bash
set -euo pipefail
cd /workspace/atlas
source .venv/bin/activate
export ATLAS_DATABASE_URL=postgresql+asyncpg://atlas:atlas@localhost:5432/atlas
export ATLAS_ENV=development

# stop old
pkill -f '/workspace/atlas/.venv/bin/uvicorn' || true
sleep 1

nohup /workspace/atlas/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 > /tmp/atlas-api.log 2>&1 &
echo "API_PID=$!"
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8080/version >/dev/null; then
    break
  fi
  sleep 0.5
done

echo '=== VERSION ==='
curl -s http://127.0.0.1:8080/version
echo
echo '=== READY ==='
curl -s http://127.0.0.1:8080/ready
echo
echo '=== HEALTH ==='
curl -s http://127.0.0.1:8080/health | python -m json.tool
echo '=== SNAPSHOT ==='
curl -s -m 180 'http://127.0.0.1:8080/market/btc/snapshot?refresh=true' -o /tmp/atlas-snap.json
python - <<'PY'
import json
d=json.load(open('/tmp/atlas-snap.json'))
if 'detail' in d and 'symbol' not in d:
    print('SNAPSHOT_ERROR', d)
    raise SystemExit(1)
print({k:d.get(k) for k in ('symbol','price','data_quality','sources','lag_sec')})
print('tfs', {k: len(v) for k,v in d.get('timeframes',{}).items()})
PY
echo '=== ANALYSIS ==='
curl -s -m 300 -X POST 'http://127.0.0.1:8080/analysis/btc/run?collect=true' -o /tmp/atlas-analysis.json
python - <<'PY'
import json
d=json.load(open('/tmp/atlas-analysis.json'))
if 'decision' not in d:
    print('ANALYSIS_ERROR', d)
    raise SystemExit(1)
dec=d['decision']
print('id', d['decision_id'])
print('decision', dec['decision'], 'conf', dec['confidence'], 'dq', dec['data_quality'])
print('regime', dec['market_regime'])
print('hyp', dec['primary_hypothesis'][:240])
print('specialists', [s['specialist'] for s in dec['specialist_votes']])
print('md_len', len(d['report_markdown']))
PY
echo '=== COMPOSE ==='
docker compose config >/dev/null && echo COMPOSE_OK
echo '=== DOCKER BUILD ==='
export DOCKER_HOST=tcp://127.0.0.1:2375
docker build -t atlas:0.1.0 . 2>&1 | tail -40
