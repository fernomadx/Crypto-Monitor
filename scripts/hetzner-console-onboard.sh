#!/usr/bin/env bash
# Cole na Console web da Hetzner (204.168.179.200 ou qualquer VPS):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-console-onboard.sh | sudo bash
set -euo pipefail

echo "==> Autorizando chave deploy (Railway/GitHub Actions)..."
mkdir -p ~/.ssh && chmod 700 ~/.ssh
curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/vps_deploy_key.pub \
  >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

echo "==> Bootstrap Kronos v4.0..."
curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-bootstrap-test.sh | bash

echo "==> Pronto. Railway pode usar: /vps $(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
