# Arquivo Kronos + Crypto-Monitor

Pasta de referência com **tudo que foi criado/ajustado** neste projeto — para consultar sem caçar no repo.

**Repo:** [fernomadx/Crypto-Monitor](https://github.com/fernomadx/Crypto-Monitor)  
**Branch principal com código completo:** `main`

---

## Comece aqui

| Arquivo | Conteúdo |
|---------|----------|
| [01-indice-arquivos.md](01-indice-arquivos.md) | Lista de cada script/lib e o que faz |
| [02-railway.md](02-railway.md) | Deploy Railway, cron, variáveis |
| [03-hetzner-btccursor.md](03-hetzner-btccursor.md) | VPS Hetzner, bot dedicado |
| [04-scorecard-simulacao.md](04-scorecard-simulacao.md) | Regras PnL, limite, 10x, 4H |
| [05-cron-e-telegram.md](05-cron-e-telegram.md) | Horários e tipos de alerta |
| [06-comandos-uteis.md](06-comandos-uteis.md) | Comandos Shell / testes |
| [07-decisoes-e-contexto.md](07-decisoes-e-contexto.md) | O que foi pedido e decidido |
| [08-export-memorias.md](08-export-memorias.md) | Preferências e contexto exportado |

---

## Mapa rápido (código na `main`)

```
lib/
  kronos_tracker.py      # SQLite + scorecard + relatório diário
  kronos_levels.py       # Alvo/stop + R:R
  kronos_alignment.py    # Conflito multi-timeframe
  smc_strategy.py        # SMC simplificado (backtest)
  telegram.py            # send_kronos_alert + bot dedicado KRONOS_TELEGRAM_*

vps/
  kronos_signal.py       # Previsão + gráficos + Telegram
  kronos_scorecard.py    # Avalia trades maduros
  kronos_daily_report.py # Relatório 12:00 BRT
  kronos_status.py       # Ranking por TF no terminal
  kronos_reset_catalog.py # Reset manual DB (opcional)
  smc_backtest.py        # Backtest SMC na MEXC
  BTCCURSOR.md           # Guia Hetzner
  install.sh / crontab.example

Dockerfile               # crypto-monitor + Kronos (Railway)
crontab                  # agents + kronos (Railway)
```

---

## Atualizar este arquivo

Quando criar algo novo no projeto, adicione uma linha em `01-indice-arquivos.md` e, se for decisão importante, em `07-decisoes-e-contexto.md`.
