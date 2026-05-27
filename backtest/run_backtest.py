#!/usr/bin/env python3
"""
Backtest EMA 20/50 crossover + double retest across multiple timeframes.

Usage:
    python backtest/run_backtest.py
    python backtest/run_backtest.py --symbol ETH/USDT --timeframes 1h 4h 1d
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data_fetcher import candles_for_timeframe, fetch_ohlcv
from backtest.ema_retest_strategy import generate_signals, summarize_trades


DEFAULT_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def run_single(symbol: str, timeframe: str) -> dict:
    limit = candles_for_timeframe(timeframe)
    print(f"  Baixando {symbol} {timeframe} ({limit} candles)...", flush=True)
    df = fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    _, trades = generate_signals(df)
    stats = summarize_trades(trades)
    stats["timeframe"] = timeframe
    stats["symbol"] = symbol
    stats["candles"] = len(df)
    stats["period_start"] = str(df.index[0])
    stats["period_end"] = str(df.index[-1])
    stats["exchange"] = df.attrs.get("exchange", "unknown")
    stats["pair"] = df.attrs.get("pair", symbol)
    return stats


def print_results_table(results: list[dict]) -> None:
    headers = [
        ("TF", "timeframe"),
        ("Trades", "total_trades"),
        ("Win%", "win_rate_pct"),
        ("Retorno%", "total_return_pct"),
        ("Média%", "avg_return_pct"),
        ("PF", "profit_factor"),
        ("MaxDD%", "max_drawdown_pct"),
        ("Long", "long_trades"),
        ("Short", "short_trades"),
    ]

    col_widths = [max(len(h[0]), 8) for h in headers]
    header_line = " | ".join(h[0].ljust(w) for h, w in zip(headers, col_widths))
    sep = "-+-".join("-" * w for w in col_widths)

    print()
    print(header_line)
    print(sep)

    for r in results:
        row = []
        for (_, key), w in zip(headers, col_widths):
            val = r.get(key, "")
            if isinstance(val, float) and val == float("inf"):
                val = "∞"
            row.append(str(val).ljust(w))
        print(" | ".join(row))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="EMA 20/50 retest backtest")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair")
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=DEFAULT_TIMEFRAMES,
        help="Timeframes to test",
    )
    parser.add_argument(
        "--output",
        default="backtest/results.json",
        help="JSON output path",
    )
    args = parser.parse_args()

    print(f"\n=== Backtest EMA 20/50 + 2 Retestes — {args.symbol} ===\n")

    results: list[dict] = []
    for tf in args.timeframes:
        try:
            stats = run_single(args.symbol, tf)
            results.append(stats)
            print(
                f"  ✓ {tf}: {stats['total_trades']} trades, "
                f"retorno {stats['total_return_pct']}%, win {stats['win_rate_pct']}%"
            )
        except Exception as exc:
            print(f"  ✗ {tf}: erro — {exc}")
            results.append({"timeframe": tf, "error": str(exc)})

    print_results_table([r for r in results if "error" not in r])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Resultados salvos em {out_path}")


if __name__ == "__main__":
    main()
