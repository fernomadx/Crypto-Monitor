#!/usr/bin/env bash
# Dump /root/trading-bot → fernomadx/apolo-paper (no secrets).
# Requires GH_TOKEN or GITHUB_TOKEN with Contents write on the repo.
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
APOLO_DIR="${APOLO_DIR:-/root/trading-bot}"
APOLO_REPO="${APOLO_REPO:-fernomadx/apolo-paper}"
STAGE="${STAGE:-/tmp/apolo-paper-stage-${STAMP}}"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

if [ ! -d "$APOLO_DIR" ]; then
  echo "FATAL: APOLO_DIR missing: $APOLO_DIR" >&2
  exit 1
fi

rm -rf "$STAGE"
mkdir -p "$STAGE"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '*.pem' \
    --exclude '*.key' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude 'node_modules' \
    "$APOLO_DIR/" "$STAGE/"
else
  cp -a "$APOLO_DIR/." "$STAGE/"
  rm -rf "$STAGE/.git" "$STAGE/.venv" "$STAGE/venv" "$STAGE/__pycache__" || true
fi

find "$STAGE" -type f \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' \) -delete 2>/dev/null || true

cd "$STAGE"
git init -b main
git config user.email "rescue@local"
git config user.name "VPS Rescue"
printf '%s\n' '.env' '.env.*' '*.pem' '*.key' '__pycache__/' '.venv/' 'venv/' 'node_modules/' > .gitignore
if [ ! -f README.md ]; then
  cat > README.md <<EOF
# APOLO (paper)

Rescued from Kronos VPS \`$APOLO_DIR\` at ${STAMP}.

- Mode: paper only
- Risk: 1% equity per trade
- Do not commit secrets
EOF
fi
git add -A
git commit -m "chore: rescue APOLO from Kronos VPS ${STAMP}"

if [ -z "$TOKEN" ]; then
  TAR="/root/apolo-paper-${STAMP}.tar.gz"
  tar -C "$(dirname "$STAGE")" -czf "$TAR" "$(basename "$STAGE")"
  echo "NO_GH_TOKEN: created $TAR — scp off the box or export GH_TOKEN and re-run"
  exit 2
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${TOKEN}@github.com/${APOLO_REPO}.git"
if git push -u origin main; then
  echo "PUSH_OK → https://github.com/${APOLO_REPO}"
else
  echo "main push failed — force once onto landing repo (empty README init)"
  git push -u origin main --force
  echo "PUSH_FORCE_OK → https://github.com/${APOLO_REPO}"
fi
