#!/usr/bin/env python3
"""Resumo do desempenho Kronos (SQLite /data). Rode no Railway: python vps/kronos_status.py"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_tracker import (  # noqa: E402
    INITIAL_CAPITAL_USDC,
    LEVERAGE,
    MARGIN_USDC,
    _aggregate_stats,
    format_scorecard_telegram,
    init_kronos_tables,
    notional_usdc,
)
from lib.db import DB_PATH, get_conn


def main() -> None:
    init_kronos_tables()
    print(f"DB: {DB_PATH}\n")

    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM kronos_predictions").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM kronos_predictions WHERE scored_short_at IS NULL"
        ).fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM kronos_predictions WHERE scored_short_at IS NOT NULL"
        ).fetchone()[0]
        last_pred = conn.execute(
            "SELECT created_at, ticker, timeframe, bias FROM kronos_predictions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_score = conn.execute(
            "SELECT scored_short_at, ticker, result_short, pnl_usdc_short FROM kronos_predictions "
            "WHERE scored_short_at IS NOT NULL ORDER BY scored_short_at DESC LIMIT 1"
        ).fetchone()

    print(f"Previsões catalogadas: {total}")
    print(f"Aguardando vencimento (curto): {pending}")
    print(f"Já avaliadas (curto): {scored}")
    if last_pred:
        print(f"Última previsão: {last_pred[0]} {last_pred[1]} {last_pred[2]} {last_pred[3]}")
    if last_score:
        print(
            f"Última avaliação: {last_score[0]} {last_score[1]} "
            f"→ {last_score[2]} ${last_score[3] or 0:+.2f}"
        )

    for days in (7, 30, None):
        label = f"{days} dias" if days else "tudo"
        s = _aggregate_stats(days, "short")
        print(f"\n--- Horizonte curto ({label}) — limite + taxas + {LEVERAGE:.0f}x ---")
        if s.get("count", 0) == 0:
            print("  Sem trades fechados ainda.")
            continue
        print(f"  Margem ${MARGIN_USDC:.0f} × {LEVERAGE:.0f}x (nocional ${notional_usdc():.0f})")
        print(f"  Trades: {s['count']} | sem fill: {s.get('no_fill', 0)}")
        print(f"  Acerto PnL: {s['win_rate_pnl_pct']}% ({s['gains']}G / {s['losses']}L / {s['flats']} flat)")
        print(f"  Direção: {s['accuracy_pct']}%")
        print(f"  PnL: ${s['total_pnl_usdc']:+.2f} → equity ${s['equity_end']:.2f} ({s['return_on_capital_pct']:+.2f}%)")
        print(f"  Taxas: ${s.get('total_fees_usdc', 0):.2f} | PF: {s.get('profit_factor')}")

    print("\n" + "=" * 50)
    print("Texto Telegram (scorecard):")
    print("=" * 50)
    print(format_scorecard_telegram().replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))


if __name__ == "__main__":
    main()
