# Índice de arquivos criados/alterados

## Core Kronos

| Arquivo | Função |
|---------|--------|
| `vps/kronos_signal.py` | Carrega Kronos-mini, MEXC, prevê 1H/4H/1D, gráficos, Telegram `[KRONOS]`, catálogo DB |
| `lib/kronos_tracker.py` | Tabela `kronos_predictions`, simulação limite+taxas+10x, scorecard, ranking TF |
| `lib/kronos_levels.py` | Alvo (mais barras), stop, R:R mínimo 1.5, piso 0.35% |
| `lib/kronos_alignment.py` | Conflito/alinhado multi-TF; scorecard só 4H operável |
| `lib/telegram.py` | `KRONOS_TELEGRAM_*` (VPS) ou fallback `TELEGRAM_*` (Railway) |

## Scorecard e relatórios

| Arquivo | Função |
|---------|--------|
| `vps/kronos_scorecard.py` | Fecha previsões maduras; Telegram se houver novidade ou `--weekly` |
| `vps/kronos_daily_report.py` | Relatório diário 12:00 BRT — ranking 1H/4H/Diário |
| `vps/kronos_status.py` | Resumo no terminal (Railway Shell / VPS) |
| `vps/kronos_reset_catalog.py` | Apaga só `kronos_predictions` com `--confirm` (manual) |

## VPS / Hetzner BTCCURSOR

| Arquivo | Função |
|---------|--------|
| `vps/BTCCURSOR.md` | Guia Hetzner CPX31, bot @BotFather, install |
| `vps/install.sh` | Install completo em `/opt/crypto-monitor` |
| `vps/setup_btccursor.sh` | Setup inicial leve |
| `vps/crontab.example` | Cron 1h na VPS |
| `vps/.env.example` | `KRONOS_TELEGRAM_*`, `DB_PATH`, env Kronos |
| `vps/railway_boot.sh` | Boot Railway: 1ª previsão após deploy |

## SMC (educacional)

| Arquivo | Função |
|---------|--------|
| `lib/smc_strategy.py` | FVG + CHoCH simplificado |
| `vps/smc_backtest.py` | Backtest na MEXC (`python vps/smc_backtest.py`) |

## Infra

| Arquivo | Função |
|---------|--------|
| `Dockerfile` | Railway: monitor + Kronos + PyTorch |
| `Dockerfile.kronos` | Serviço Railway só Kronos (opcional) |
| `crontab` | Cron Railway (agents + kronos) |
| `crontab.kronos` | Cron só Kronos |
| `.github/workflows/kronos-daily-report.yml` | Disparo manual relatório |
| `.github/workflows/deploy-kronos-vps.yml` | Deploy SSH Hetzner |
