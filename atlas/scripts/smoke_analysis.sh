#!/usr/bin/env bash
set -euo pipefail
cd /workspace/atlas
source .venv/bin/activate
export ATLAS_DATABASE_URL=postgresql+asyncpg://atlas:atlas@localhost:5432/atlas
pkill -f '/workspace/atlas/.venv/bin/uvicorn' || true
sleep 1
nohup /workspace/atlas/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 > /tmp/atlas-api.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8080/version >/dev/null && break; sleep 0.3; done
curl -s -m 300 -X POST 'http://127.0.0.1:8080/analysis/btc/run?collect=true' -o /tmp/atlas-analysis3.json -w 'HTTP=%{http_code}\n'
python - <<'PY'
import json
d=json.load(open('/tmp/atlas-analysis3.json'))
assert 'decision' in d, d
dec=d['decision']
print('id', d['decision_id'])
print(dec['decision'], dec['confidence'], dec['data_quality'])
print('regime', dec['market_regime'])
print('hyp', dec['primary_hypothesis'][:220])
print('specialists', [(s['specialist'], s['bias'], s['availability']) for s in dec['specialist_votes']])
print('md_len', len(d['report_markdown']))
PY
docker compose config >/dev/null && echo COMPOSE_OK
export DOCKER_HOST=tcp://127.0.0.1:2375
docker build -t atlas:0.1.0 . 
