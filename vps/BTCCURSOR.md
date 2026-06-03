# BTCCURSOR — Kronos com bot Telegram próprio

O **Railway** continua com o bot do `crypto-monitor` (funding, notícias, orchestrator).

Na **VPS BTCCURSOR** o Kronos usa **outro bot** (`KRONOS_TELEGRAM_*`) — chat pode ser o mesmo seu usuário, mas o bot é outro @username no Telegram.

## 1. Criar o bot (2 min)

1. Abra [@BotFather](https://t.me/BotFather) no Telegram.
2. `/newbot` → nome: `BTCCURSOR Kronos` → username: ex. `btccursor_kronos_bot`.
3. Copie o **token** → `KRONOS_TELEGRAM_BOT_TOKEN`.
4. Abra o bot novo e mande `/start`.
5. Descubra o **chat_id** (seu usuário ou grupo):
   - [@userinfobot](https://t.me/userinfobot) ou
   - `https://api.telegram.org/bot<TOKEN>/getUpdates` após enviar uma mensagem ao bot.

## 2. Instalar na VPS

```bash
ssh root@SEU_IP_BTCCURSOR
git clone https://github.com/fernomadx/Crypto-Monitor.git /opt/crypto-monitor
cd /opt/crypto-monitor
cp vps/.env.example vps/.env
nano vps/.env   # KRONOS_TELEGRAM_BOT_TOKEN, KRONOS_TELEGRAM_CHAT_ID, DB_PATH

sudo bash vps/install.sh
```

Ou deploy via GitHub Actions (secrets `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`).

## 3. Cron na VPS

`install.sh` instala só o sinal. Para scorecard + relatório diário:

```bash
crontab -e
# cole o conteúdo de vps/crontab.example
```

## 4. Railway vs BTCCURSOR

| | Railway | BTCCURSOR VPS |
|--|---------|----------------|
| Bot | `TELEGRAM_*` | `KRONOS_TELEGRAM_*` |
| DB scorecard | `/data/crypto_monitor.db` | `DB_PATH` no `.env` (ex. `kronos_vps.db`) |
| RAM | ≥2 GB | ≥4 GB recomendado |

**Não rode os dois** no mesmo bot se quiser separar; pode rodar os dois em paralelo com DBs diferentes para comparar performance.

## 5. Teste

```bash
set -a && source /opt/crypto-monitor/vps/.env && set +a
cd /opt/crypto-monitor
/opt/crypto-monitor/vps/.venv/bin/python vps/kronos_signal.py
```

Deve chegar só no **bot novo**, não no bot do monitor.
