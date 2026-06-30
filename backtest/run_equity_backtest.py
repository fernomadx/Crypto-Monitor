#!/usr/bin/env python3
"""
Backtest com capital fixo e alavancagem — relatório mensal.

Exemplo:
    python3 backtest/run_equity_backtest.py
    python3 backtest/run_equity_backtest.py --timeframe 4h --start 2025-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data_fetcher import fetch_ohlcv_range
from backtest.ema_retest_strategy import EntryFilterConfig, generate_signals
from backtest.equity_simulator import simulate_equity


def print_report(summary, symbol: str, timeframe: str, start: str, end: str) -> None:
    print(f"\n{'=' * 60}")
    print("BACKTEST EQUITY — EMA 20/50 + 2 retestes")
    print(f"{'=' * 60}")
    print(f"Par:          {symbol}")
    print(f"Timeframe:    {timeframe}")
    print(f"Período:      {start} → {end}")
    print(f"Capital:      {summary.initial_capital:,.2f} USDC")
    print(f"Alavancagem:  {summary.leverage}x")
    if summary.fixed_margin_usdc:
        print(f"Margem/trade:  {summary.fixed_margin_usdc:,.2f} USDC (fixo)")
        print(f"Notional/trade: {summary.fixed_margin_usdc * summary.leverage:,.2f} USDC")
        if summary.trades_skipped:
            print(f"Trades ignorados (sem margem): {summary.trades_skipped}")
    else:
        print(f"Notional/trade: equity × {summary.leverage}")
    print(f"{'=' * 60}\n")

    print("--- RESUMO TOTAL ---")
    print(f"Capital final:     {summary.final_capital:,.2f} USDC")
    print(f"Lucro/prejuízo:    {summary.total_return_usd:+,.2f} USDC")
    print(f"Retorno total:     {summary.total_return_pct:+.2f}%")
    print(f"Max drawdown:      {summary.max_drawdown_pct:.2f}% ({summary.max_drawdown_usd:,.2f} USDC)")
    print(f"Trades:            {summary.total_trades}")
    print(f"Win rate:          {summary.win_rate_pct:.1f}%")
    if summary.liquidated:
        print("⚠️  Conta liquidada durante o período.")
    print()

    if summary.monthly.empty:
        print("Nenhum trade no período.")
        return

    print("--- RESULTADO MÊS A MÊS ---\n")
    headers = (
        "Mês",
        "Trades",
        "Win%",
        "Início USDC",
        "Fim USDC",
        "PnL mês",
        "Ret.% mês",
        "DD mês%",
        "Acum. USDC",
        "Acum.%",
    )
    col_w = [10, 6, 6, 11, 11, 10, 9, 8, 11, 8]
    line = " | ".join(h.ljust(w) for h, w in zip(headers, col_w))
    print(line)
    print("-" * len(line))

    for _, row in summary.monthly.iterrows():
        vals = [
            row["month"],
            str(int(row["trades"])),
            f"{row['win_rate_pct']:.0f}",
            f"{row['start_usdc']:,.2f}",
            f"{row['end_usdc']:,.2f}",
            f"{row['pnl_usdc']:+,.2f}",
            f"{row['return_pct']:+.2f}",
            f"{row['max_dd_pct']:.2f}",
            f"{row['cumulative_usdc']:,.2f}",
            f"{row['cumulative_return_pct']:+.2f}",
        ]
        print(" | ".join(v.ljust(w) for v, w in zip(vals, col_w)))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest equity com alavancagem")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h", help="Timeframe (padrão 1h)")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD (padrão: hoje UTC)")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--leverage", type=int, default=20)
    parser.add_argument(
        "--position-usdc",
        type=float,
        default=None,
        help="Margem fixa por trade em USDC (ex: 100)",
    )
    parser.add_argument("--fee", type=float, default=0.0005, help="Taxa por lado (0.05%%)")
    parser.add_argument(
        "--output",
        default="backtest/results_equity.json",
    )
    args = parser.parse_args()

    end_dt = (
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        if args.end
        else datetime.now(timezone.utc)
    )
    end_str = end_dt.strftime("%Y-%m-%d")

    print(f"\nBaixando {args.symbol} {args.timeframe} ({args.start} → {end_str})...")
    df = fetch_ohlcv_range(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=args.start,
        end=end_dt,
    )
    print(f"Candles: {len(df)} | {df.index[0]} → {df.index[-1]}")

    _, trades = generate_signals(df, entry_filter=EntryFilterConfig.none())
    summary = simulate_equity(
        trades,
        initial_capital=args.capital,
        leverage=args.leverage,
        fee_rate=args.fee,
        fixed_margin_usdc=args.position_usdc,
    )

    print_report(summary, args.symbol, args.timeframe, args.start, end_str)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "start": args.start,
        "end": end_str,
        "capital": args.capital,
        "leverage": args.leverage,
            "position_usdc": args.position_usdc,
        "candles": len(df),
        "exchange": df.attrs.get("exchange"),
        "summary": {
            "initial_capital": summary.initial_capital,
            "final_capital": round(summary.final_capital, 2),
            "total_return_usd": round(summary.total_return_usd, 2),
            "total_return_pct": round(summary.total_return_pct, 2),
            "max_drawdown_pct": round(summary.max_drawdown_pct, 2),
            "max_drawdown_usd": round(summary.max_drawdown_usd, 2),
            "total_trades": summary.total_trades,
            "win_rate_pct": round(summary.win_rate_pct, 2),
            "liquidated": summary.liquidated,
        },
        "monthly": summary.monthly.to_dict(orient="records"),
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"JSON salvo em {out}")


if __name__ == "__main__":
    main()
