# Configurar acesso GitHub → Hetzner (BTCCURSOR)

Permite **Actions → Deploy Kronos to VPS** rodar `hetzner_test.sh --score` via SSH.

## 1. Chave SSH na Hetzner

No [Hetzner Cloud Console](https://console.hetzner.cloud/) → seu servidor → **SSH Keys** → Add SSH Key.

Cole o conteúdo de [`vps_deploy_key.pub`](vps_deploy_key.pub).

Ou na VPS (como root):

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/vps_deploy_key.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

## 2. Secrets no GitHub

Repositório → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|--------|--------|
| `VPS_HOST` | IPv4 do servidor (painel Hetzner → Overview) |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | chave **privada** correspondente a `vps_deploy_key.pub` |

> A chave privada **não** fica no repo por segurança. Gere um par localmente ou peça ao agente Cloud (sessão com chave efémera).

Gerar par novo:

```bash
ssh-keygen -t ed25519 -f ./vps_deploy -N ""
# Hetzner: vps_deploy.pub
# GitHub secret VPS_SSH_KEY: conteúdo de vps_deploy (privada)
```

## 3. Rodar teste

**Actions** → **Deploy Kronos to VPS** → **Run workflow**

Opcional: informe o IPv4 no campo `vps_host` se `VPS_HOST` secret ainda não existir.

## 4. Teste manual na VPS (sem GitHub)

Console Hetzner ou SSH:

```bash
curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-bootstrap-test.sh | sudo bash
```
