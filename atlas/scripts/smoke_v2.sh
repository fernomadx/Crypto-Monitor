#!/usr/bin/env bash
set -euo pipefail
cd /workspace/atlas
source .venv/bin/activate
export ATLAS_DATABASE_URL=postgresql+asyncpg://atlas:atlas@localhost:5432/atlas
export ATLAS_ENV=development

echo '== migrate =='
alembic -c migrations/alembic.ini upgrade head

echo '== quality =='
ruff check app tests --no-cache
mypy app
pytest -q

echo '== restart api =='
pkill -f '/workspace/atlas/.venv/bin/uvicorn' || true
sleep 1
nohup /workspace/atlas/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 > /tmp/atlas-api.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8080/version >/dev/null && break; sleep 0.3; done
curl -s http://127.0.0.1:8080/version; echo

echo '== walkforward demo =='
curl -s -X POST http://127.0.0.1:8080/replay/walkforward/demo | python -m json.tool | head -40

echo '== analysis =='
curl -s -m 300 -X POST 'http://127.0.0.1:8080/analysis/btc/run?collect=true' -o /tmp/v2-analysis.json -w 'HTTP=%{http_code}\n'
python - <<'PY'
import json
d=json.load(open('/tmp/v2-analysis.json'))
dec=d['decision']
print(dec['decision'], dec['confidence'])
print([(s['specialist'], s['bias'], s['availability']) for s in dec['specialist_votes']])
liq=[s for s in dec['specialist_votes'] if s['specialist']=='liquidity_derivatives'][0]
print('liq', liq['availability'], liq['bias'], (liq.get('metrics') or {}).get('positioning_regime'), (liq.get('metrics') or {}).get('funding'))
PY

echo '== alerts =='
curl -s 'http://127.0.0.1:8080/alerts?limit=5' | python -m json.tool | head -30

echo '== weights propose =='
curl -s -X POST 'http://127.0.0.1:8080/weights/propose?min_evaluations=20' | python -m json.tool | head -20

echo '== dashboard =='
curl -s -o /dev/null -w 'DASH_HTTP=%{http_code}\n' http://127.0.0.1:8080/dashboard

echo '== compose =='
docker compose config >/dev/null && echo COMPOSE_OK
