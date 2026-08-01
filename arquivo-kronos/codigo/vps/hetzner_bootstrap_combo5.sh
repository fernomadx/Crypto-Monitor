#!/usr/bin/env bash
# Bootstrap COMBO5 na Hetzner — Console (root):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-deploy-combo5.sh | sudo bash
#
# (Mantido por compatibilidade; o deploy completo está em scripts/hetzner-deploy-combo5.sh)
set -euo pipefail
REPO_DIR="${REPO_DIR:-/opt/crypto-monitor}"
if [ -f "$REPO_DIR/scripts/hetzner-deploy-combo5.sh" ]; then
  exec bash "$REPO_DIR/scripts/hetzner-deploy-combo5.sh"
fi
exec bash -c "$(curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-deploy-combo5.sh)"
