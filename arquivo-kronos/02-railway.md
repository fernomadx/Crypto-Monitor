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
```

## Requisitos

- RAM **≥ 2 GB** (Kronos-mini em CPU)
- Volume persistente `/data`

## Logs

```bash
tail -f /data/kronos.log
tail -f /data/kronos_scorecard.log
```
