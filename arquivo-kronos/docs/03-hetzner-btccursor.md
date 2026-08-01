# Hetzner — BTCCURSOR (opcional, separado)

Kronos **pode** rodar na VPS com **outro bot** — não substitui o Railway a menos que você desligue lá.

## Bot dedicado

```env
KRONOS_TELEGRAM_BOT_TOKEN=   # @BotFather — bot novo
KRONOS_TELEGRAM_CHAT_ID=
DB_PATH=/opt/crypto-monitor/data/kronos_vps.db
```

Guia completo: `vps/BTCCURSOR.md` no repo.

## Install

```bash
ssh root@IP_HETZNER
git clone https://github.com/fernomadx/Crypto-Monitor.git /opt/crypto-monitor
cp vps/.env.example vps/.env && nano vps/.env
sudo bash vps/install.sh
crontab -e   # vps/crontab.example
```

## GitHub deploy

Secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` → workflow `Deploy Kronos to VPS` / `Deploy COMBO5 to Hetzner`.

## COMBO5 + `/combo5` na Hetzner

Na Console Hetzner (root), uma linha:

```bash
curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-deploy-combo5.sh | sudo bash
```

Isso faz `git pull`, cron COMBO5 (5 min + `:10` UTC), reinicia `quant_bot` com `/combo5` · `/analise`.

**Nota:** sem `VPS_SSH_KEY` no GitHub, o agente Cloud não acessa a VPS — use o comando acima na Console.
