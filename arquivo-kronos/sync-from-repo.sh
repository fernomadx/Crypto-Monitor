#!/usr/bin/env bash
# Atualiza cópias em arquivo-kronos/codigo/ a partir da raiz do repo.
# Rode na raiz: bash arquivo-kronos/sync-from-repo.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/arquivo-kronos/codigo"

copy() {
  local src="$1" dst="${2:-$1}"
  if [ -f "$ROOT/$src" ]; then
    mkdir -p "$(dirname "$DEST/$dst")"
    cp "$ROOT/$src" "$DEST/$dst"
    echo "  ok $dst"
  else
    echo "  skip $src"
  fi
}

echo "==> Sync arquivo-kronos/codigo"
copy lib/kronos_config.py
copy lib/kronos_tracker.py
copy lib/kronos_levels.py
copy lib/kronos_alignment.py
copy lib/llmquant_client.py
copy lib/quant_state.py
copy lib/quant_research.py
copy lib/quant_impact.py
copy lib/kronos_quant.py
copy lib/smc_strategy.py
copy lib/mexc_klines.py
copy lib/telegram.py
copy lib/db.py
copy vps/kronos_run.sh
copy vps/kronos_watchdog.py
copy vps/quant_watcher.py
copy vps/quant_bot.py
copy vps/quant_test.py
copy vps/start_quant.sh
copy vps/install_quant_crontab.sh
copy vps/QUANT.md
copy vps/kronos_signal.py
copy vps/kronos_scorecard.py
copy vps/kronos_daily_report.py
copy vps/kronos_status.py
copy vps/kronos_reset_catalog.py
copy vps/smc_backtest.py
copy vps/railway_boot.sh
copy vps/install.sh
copy vps/setup_btccursor.sh
copy vps/requirements.txt
copy vps/requirements-railway.txt
copy vps/.env.example
copy vps/BTCCURSOR.md
copy vps/README.md
copy vps/crontab.example
copy Dockerfile
copy Dockerfile.kronos
copy crontab
copy crontab.kronos
copy railway.toml
copy .github/workflows/kronos-daily-report.yml workflows/kronos-daily-report.yml
copy .github/workflows/deploy-kronos-vps.yml workflows/deploy-kronos-vps.yml
copy .github/workflows/kronos-telegram-cron.yml workflows/kronos-telegram-cron.yml
copy .github/workflows/arquivo-kronos-pages.yml workflows/arquivo-kronos-pages.yml
copy .github/workflows/sync-arquivo-kronos.yml workflows/sync-arquivo-kronos.yml
copy README.md README-repo.md
echo "==> Concluído"
