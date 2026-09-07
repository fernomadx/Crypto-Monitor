#!/usr/bin/env bash
set -euo pipefail
cd /workspace/atlas
source .venv/bin/activate
export ATLAS_DATABASE_URL=postgresql+asyncpg://atlas:atlas@localhost:5432/atlas
pkill -f '/workspace/atlas/.venv/bin/uvicorn' || true
sleep 1
nohup /workspace/atlas/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 > /tmp/atlas-api.log 2>&1 &
for i in $(seq 1 40); do curl -sf http://127.0.0.1:8080/version >/dev/null && break; sleep 0.25; done
echo VERSION=$(curl -s http://127.0.0.1:8080/version)
echo DASH=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/dashboard)
echo WF=$(curl -s -X POST http://127.0.0.1:8080/replay/walkforward/demo | python -c 'import sys,json; d=json.load(sys.stdin); print(d["n_folds"], len(d["folds"]))')
curl -s -m 300 -X POST 'http://127.0.0.1:8080/analysis/btc/run?collect=true' -o /tmp/v2-analysis.json -w 'ANALYSIS_HTTP=%{http_code}\n'
python - <<'PY'
import json
d=json.load(open('/tmp/v2-analysis.json'))
dec=d['decision']
print('DEC', dec['decision'], dec['confidence'])
print('VOTES', [(s['specialist'], s['bias'], s['availability']) for s in dec['specialist_votes']])
liq=[s for s in dec['specialist_votes'] if s['specialist']=='liquidity_derivatives'][0]
print('LIQ', liq['availability'], liq['bias'], (liq.get('metrics') or {}).get('funding'), (liq.get('metrics') or {}).get('positioning_regime'))
PY
echo ALERTS=$(curl -s 'http://127.0.0.1:8080/alerts?limit=3' | python -c 'import sys,json; print(len(json.load(sys.stdin)))')
echo WEIGHTS=$(curl -s -X POST 'http://127.0.0.1:8080/weights/propose?min_evaluations=20')
docker compose config >/dev/null && echo COMPOSE_OK
