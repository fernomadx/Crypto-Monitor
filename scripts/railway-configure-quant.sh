#!/usr/bin/env bash
# Configura QUANT no Railway via CLI (rode no seu PC após railway login).
# Uso:
#   export RAILWAY_TOKEN=seu_project_token
#   export LLMQUANT_API_KEY=sua_chave
#   bash scripts/railway-configure-quant.sh

set -euo pipefail

: "${RAILWAY_TOKEN:?Defina RAILWAY_TOKEN (Railway → Project → Settings → Tokens)}"
: "${LLMQUANT_API_KEY:?Defina LLMQUANT_API_KEY}"

npx -y @railway/cli variable set \
  "LLMQUANT_API_KEY=$LLMQUANT_API_KEY" \
  QUANT_KRONOS_MODE=warn \
  QUANT_STATE_PATH=/data/quant_state.json \
  QUANT_IMPACT_THRESHOLD=0.70 \
  QUANT_IMPACT_ALERTS=true \
  QUANT_MAX_AGE_HOURS=4

echo "Redeploy..."
npx -y @railway/cli redeploy --yes
echo "OK — teste /ping no Telegram"
