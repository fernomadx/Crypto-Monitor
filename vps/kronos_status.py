#!/usr/bin/env python3
"""Resumo do desempenho Kronos (SQLite /data). Rode no Railway: python vps/kronos_status.py"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_tracker import (  # noqa: E402
    LEVERAGE,
    MARGIN_USDC,
    _aggregate_stats,
    format_scorecard_telegram,
    init_kronos_tables,
    notional_usdc,
)
from lib.db import DB_PATH, get_conn


def _print_timeframe_ranking(s: dict) -> None:
    wr = s.get("by_timeframe_win_rate") or {}
    pnl = s.get("by_timeframe_pnl") or {}
    if not wr:
        return
    print("  Por timeframe:")
    ranked = sorted(wr.items(), key=lambda x: (-x[1], -pnl.get(x[0], 0)))
    for i, (tf, rate) in enumerate(ranked, 1):
        p = pnl.get(tf, 0)
        print(f"    {i}. {tf}: {rate}% acerto PnL · ${p:+.2f}")
    print(f"  → Mais acertivo neste período: {ranked[0][0]} ({ranked[0][1]}%)")


def _print_tf_ranking(days: int | None) -> None:
    label = f"{days} dias" if days else "histórico completo"
    window = f"-{days} days" if days else None
    with get_conn() as conn:
        if window:
            rows = conn.execute(
                """SELECT timeframe, result_short, pnl_usdc_short, direction_hit_short
                   FROM kronos_predictions
                   WHERE scored_short_at IS NOT NULL AND result_short IN ('gain','loss','flat')
                     AND created_at >= datetime('now', ?)""",
                (window,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT timeframe, result_short, pnl_usdc_short, direction_hit_short
                   FROM kronos_predictions
                   WHERE scored_short_at IS NOT NULL AND result_short IN ('gain','loss','flat')"""
            ).fetchall()
    if not rows:
        print(f"\n=== Ranking por TF ({label}): sem trades fechados ===")
        return

    stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "g": 0, "dir": 0, "dir_n": 0, "pnl": 0.0})
    for tf, res, pnl, hit in rows:
        st = stats[tf]
        st["n"] += 1
        if res == "gain":
            st["g"] += 1
        if pnl:
            st["pnl"] += float(pnl)
        if hit is not None:
            st["dir_n"] += 1
            st["dir"] += int(hit)

    print(f"\n=== Ranking por timeframe — {label} ===")
    ranked = sorted(
        stats.items(),
        key=lambda x: (-(100 * x[1]["g"] / x[1]["n"] if x[1]["n"] else 0), -x[1]["pnl"]),
    )
    for i, (tf, st) in enumerate(ranked, 1):
        wr = 100 * st["g"] / st["n"] if st["n"] else 0
        acc = 100 * st["dir"] / st["dir_n"] if st["dir_n"] else 0
        print(
            f"  {i}. {tf}: {wr:.1f}% acerto PnL ({st['g']}/{st['n']}) · "
            f"direção {acc:.1f}% · PnL ${st['pnl']:+.2f}"
        )
    print(f"  Melhor TF (acerto PnL): {ranked[0][0]}")


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
            "SELECT scored_short_at, ticker, timeframe, result_short, pnl_usdc_short "
            "FROM kronos_predictions "
            "WHERE scored_short_at IS NOT NULL ORDER BY scored_short_at DESC LIMIT 1"
        ).fetchone()

    print(f"Previsões catalogadas: {total}")
    print(f"Aguardando vencimento (curto): {pending}")
    print(f"Já avaliadas (curto): {scored}")
    if last_pred:
        print(f"Última previsão: {last_pred[0]} {last_pred[1]} {last_pred[2]} {last_pred[3]}")
    if last_score:
        print(
            f"Última avaliação: {last_score[0]} {last_score[1]} {last_score[2]} "
            f"→ {last_score[3]} ${last_score[4] or 0:+.2f}"
        )

    _print_tf_ranking(30)
    _print_tf_ranking(7)

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
        print(f"  PnL: ${s['total_pnl_usdc']:+.2f} → equity ${s['equity_end']:.2f}")
        print(f"  Taxas: ${s.get('total_fees_usdc', 0):.2f} | PF: {s.get('profit_factor')}")
        _print_timeframe_ranking(s)

    print("\n" + "=" * 50)
    print("Texto Telegram (scorecard):")
    print("=" * 50)
    print(format_scorecard_telegram().replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))


if __name__ == "__main__":
    main()
