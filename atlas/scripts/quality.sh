#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== ruff =="
ruff check app tests
echo "== mypy =="
mypy app
echo "== pytest =="
pytest -q --cov=app --cov-report=term-missing
echo "== docker compose config =="
docker compose config >/dev/null
echo "OK"
