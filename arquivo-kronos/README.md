# Arquivo Kronos + Crypto-Monitor

Pasta de referência com **tudo que foi criado/ajustado** neste projeto — para consultar sem caçar no repo.

**Repo:** [fernomadx/Crypto-Monitor](https://github.com/fernomadx/Crypto-Monitor)  
**Branch principal com código completo:** `main`

## Acesso web

**https://fernomadx.github.io/Crypto-Monitor/**

Portal com navegação por pastas e visualização de docs/código no browser (GitHub Pages).

---

## Comece aqui

| Arquivo | Conteúdo |
|---------|----------|
| [01-indice-arquivos.md](docs/01-indice-arquivos.md) | Lista de cada script/lib e o que faz |
| [02-railway.md](docs/02-railway.md) | Deploy Railway, cron, variáveis |
| [03-hetzner-btccursor.md](docs/03-hetzner-btccursor.md) | VPS Hetzner, bot dedicado |
| [04-scorecard-simulacao.md](docs/04-scorecard-simulacao.md) | Regras PnL, limite, 10x, 4H |
| [05-cron-e-telegram.md](docs/05-cron-e-telegram.md) | Horários e tipos de alerta |
| [06-comandos-uteis.md](docs/06-comandos-uteis.md) | Comandos Shell / testes |
| [07-decisoes-e-contexto.md](docs/07-decisoes-e-contexto.md) | O que foi pedido e decidido |
| [08-export-memorias.md](docs/08-export-memorias.md) | Preferências e contexto exportado |

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

```bash
./sync-from-repo.sh
git add . && git commit -m "chore: sync arquivo-kronos" && git push
```

O workflow `.github/workflows/arquivo-kronos-pages.yml` republica o site automaticamente.

Quando criar algo novo no projeto, adicione uma linha em `docs/01-indice-arquivos.md` e, se for decisão importante, em `docs/07-decisoes-e-contexto.md`.
