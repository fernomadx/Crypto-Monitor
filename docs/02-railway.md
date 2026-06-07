# Railway (crypto-monitor + Kronos)

## O que roda

- **Mesmo serviço:** agents (funding, MEXC, news, orchestrator) + **Kronos**
- **Bot Telegram:** `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- **DB:** volume `/data` → `crypto_monitor.db` + logs `kronos*.log`

## Cron (UTC) — conferir `crontab` na branch atual

| Minuto | Job |
|--------|-----|
| `*/15` | hyperliquid, mexc |
| `*/10` | sentiment |
| `*/30` | polymarket |
| `0 */4` | orchestrator |
| `:15 */2` | kronos_signal (pode ser `*` ou `*/4` conforme deploy) |
| `:30 */2` | kronos_scorecard |
| `15:00` | kronos_daily_report (12:00 BRT) |

## Variáveis importantes

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TICKERS=BTC,ETH,SOL
DB_PATH=/data/crypto_monitor.db

KRONOS_LEVERAGE=10
KRONOS_SCORE_INTERVAL=4h
KRONOS_POSITION_USDC=100
KRONOS_INITIAL_CAPITAL=1000

# QUANT (obrigatório para /pesquisa e alertas [QUANT])
LLMQUANT_API_KEY=
QUANT_KRONOS_MODE=warn
QUANT_STATE_PATH=/data/quant_state.json
QUANT_IMPACT_THRESHOLD=0.65
QUANT_MAX_AGE_HOURS=4
```

## Configurar QUANT no Railway

1. **Painel Railway** → serviço `crypto-monitor` → **Variables** → **Raw Editor**
2. Cole (com sua chave real em `LLMQUANT_API_KEY`):

```env
LLMQUANT_API_KEY=sua_chave_llmquantdata
QUANT_KRONOS_MODE=warn
QUANT_STATE_PATH=/data/quant_state.json
QUANT_IMPACT_THRESHOLD=0.65
QUANT_MAX_AGE_HOURS=4
```

3. **Deploy** (ou aguarde auto-deploy do GitHub após push na `main`).
4. No Telegram: mensagem `[QUANT] Online` → `/ping` → `/pesquisa momentum bitcoin`.

### Via CLI (opcional)

```bash
export RAILWAY_TOKEN=...   # Project → Settings → Tokens
export LLMQUANT_API_KEY=...
bash scripts/railway-configure-quant.sh
```

### Via GitHub Actions (opcional)

Secrets em **Settings → Secrets → Actions**:

- `RAILWAY_TOKEN` — Project Token do Railway
- `LLMQUANT_API_KEY` — chave de [llmquantdata.com](https://llmquantdata.com)

Depois: **Actions** → **Railway QUANT Config** → **Run workflow**.

> Defaults `QUANT_*` (exceto API key) já vêm no `Dockerfile`; só `LLMQUANT_API_KEY` precisa ser definida no painel.

## Requisitos

- RAM **≥ 2 GB** (Kronos-mini em CPU)
- Volume persistente `/data`

## Logs

```bash
tail -f /data/kronos.log
tail -f /data/kronos_scorecard.log
```
