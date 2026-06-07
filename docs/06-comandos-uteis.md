# Comandos úteis

## Railway Shell

```bash
# Status + ranking timeframe
python3 vps/kronos_status.py

# Forçar scorecard no Telegram
python3 vps/kronos_scorecard.py --force

# Relatório diário agora
python3 vps/kronos_daily_report.py

# Uma previsão manual
python3 vps/kronos_signal.py

# Reset catálogo (só se quiser zerar)
python3 vps/kronos_reset_catalog.py          # dry-run
python3 vps/kronos_reset_catalog.py --confirm
```

## VPS Hetzner

```bash
set -a && source /opt/crypto-monitor/vps/.env && set +a
cd /opt/crypto-monitor
vps/.venv/bin/python vps/kronos_signal.py
tail -f /var/log/kronos_signal.log
```

## Backtest SMC (local / VPS)

```bash
python3 vps/smc_backtest.py --symbol BTCUSDT --interval 4h --limit 500
```

## Atualizar código

```bash
cd /opt/crypto-monitor && git pull origin main
```
