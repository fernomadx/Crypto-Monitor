#!/usr/bin/env python3
"""
Backtest EMA 20/50 crossover + double retest across multiple timeframes.
MACD filters configurable on entry.

Usage:
    python3 backtest/run_backtest.py
    python3 backtest/run_backtest.py --macd-above-zero
    python3 backtest/run_backtest.py --macd-hist-rising
    python3 backtest/run_backtest.py --macd-above-zero --macd-hist-rising
    python3 backtest/run_backtest.py --compare-macd
    python3 backtest/run_backtest.py --no-macd
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data_fetcher import candles_for_timeframe, fetch_ohlcv
from backtest.ema_retest_strategy import (
    MACD_PRESETS,
    MacdFilterConfig,
    generate_signals,
    summarize_trades,
)


DEFAULT_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def build_macd_config(args: argparse.Namespace) -> MacdFilterConfig:
    if args.no_macd:
        return MacdFilterConfig(enabled=False)

    require_cross = not args.macd_above_zero_only

    if args.macd_above_zero_only:
        return MacdFilterConfig(
            enabled=True,
            require_cross=False,
            require_above_zero=True,
            require_hist_rising=args.macd_hist_rising,
        )

    return MacdFilterConfig(
        enabled=True,
        require_cross=require_cross,
        require_above_zero=args.macd_above_zero,
        require_hist_rising=args.macd_hist_rising,
    )


def run_single(
    symbol: str,
    timeframe: str,
    macd_cfg: MacdFilterConfig,
    df: pd.DataFrame | None = None,
) -> dict:
    if df is None:
        limit = candles_for_timeframe(timeframe)
        print(f"  Baixando {symbol} {timeframe} ({limit} candles)...", flush=True)
        df = fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    _, trades = generate_signals(df, macd_filter=macd_cfg)
    stats = summarize_trades(trades)
    stats["timeframe"] = timeframe
    stats["symbol"] = symbol
    stats["candles"] = len(df)
    stats["period_start"] = str(df.index[0])
    stats["period_end"] = str(df.index[-1])
    stats["exchange"] = df.attrs.get("exchange", "unknown")
    stats["pair"] = df.attrs.get("pair", symbol)
    stats["macd_mode"] = macd_cfg.label
    return stats


def print_results_table(results: list[dict], title: str = "") -> None:
    if title:
        print(f"\n--- {title} ---")

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


def print_compare_macd_summary(all_results: dict[str, list[dict]]) -> None:
    """Compact table: mode x timeframe return %."""
    timeframes = [r["timeframe"] for r in all_results["cross"] if "error" not in r]
    modes = list(all_results.keys())

    col_w = max(10, max(len(m) for m in modes))
    header = "Modo".ljust(col_w) + " | " + " | ".join(tf.ljust(8) for tf in timeframes)
    print(f"\n=== Retorno composto (%) por modo MACD ===\n")
    print(header)
    print("-" * len(header))

    for mode in modes:
        by_tf = {r["timeframe"]: r for r in all_results[mode] if "error" not in r}
        cells = []
        for tf in timeframes:
            ret = by_tf.get(tf, {}).get("total_return_pct", "—")
            cells.append(str(ret).ljust(8))
        print(mode.ljust(col_w) + " | " + " | ".join(cells))
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
    parser.add_argument("--no-macd", action="store_true", help="Desativa filtro MACD")
    parser.add_argument(
        "--macd-above-zero",
        action="store_true",
        help="Long: MACD > 0 | Short: MACD < 0 (soma ao cross, se ativo)",
    )
    parser.add_argument(
        "--macd-above-zero-only",
        action="store_true",
        help="Só MACD acima/abaixo de zero, sem exigir cross",
    )
    parser.add_argument(
        "--macd-hist-rising",
        action="store_true",
        help="Long: histograma crescente | Short: decrescente",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compara config atual vs sem MACD",
    )
    parser.add_argument(
        "--compare-macd",
        action="store_true",
        help="Compara todos os modos MACD (sem, cross, cross+zero, cross+hist, full)",
    )
    args = parser.parse_args()

    if args.compare_macd:
        print(f"\n=== Comparação modos MACD — {args.symbol} ===\n")
        all_results: dict[str, list[dict]] = {}
        cached: dict[str, pd.DataFrame] = {}

        for tf in args.timeframes:
            try:
                limit = candles_for_timeframe(tf)
                print(f"  Baixando {args.symbol} {tf} ({limit} candles)...", flush=True)
                cached[tf] = fetch_ohlcv(symbol=args.symbol, timeframe=tf, limit=limit)
            except Exception as exc:
                print(f"  ✗ {tf}: erro download — {exc}")
                for mode in MACD_PRESETS:
                    all_results.setdefault(mode, []).append(
                        {"timeframe": tf, "error": str(exc)}
                    )

        for mode_name, cfg in MACD_PRESETS.items():
            mode_results: list[dict] = []
            for tf, df in cached.items():
                stats = run_single(args.symbol, tf, cfg, df=df)
                mode_results.append(stats)
            all_results[mode_name] = mode_results
            print(f"  [{mode_name}] 1h: {next((r for r in mode_results if r['timeframe']=='1h'), {}).get('total_return_pct', '?')}%")

        for mode_name, mode_results in all_results.items():
            print_results_table(
                [r for r in mode_results if "error" not in r],
                f"MACD: {mode_name}",
            )

        print_compare_macd_summary(all_results)

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"Resultados salvos em {out_path}")
        return

    macd_cfg = build_macd_config(args)
    label = f"EMA 20/50 + 2 retestes | MACD: {macd_cfg.label}"
    print(f"\n=== Backtest {label} — {args.symbol} ===\n")

    results: list[dict] = []
    baseline: list[dict] = []

    for tf in args.timeframes:
        try:
            limit = candles_for_timeframe(tf)
            print(f"  Baixando {args.symbol} {tf} ({limit} candles)...", flush=True)
            df = fetch_ohlcv(symbol=args.symbol, timeframe=tf, limit=limit)

            stats = run_single(args.symbol, tf, macd_cfg, df=df)
            results.append(stats)
            print(
                f"  ✓ {tf}: {stats['total_trades']} trades, "
                f"retorno {stats['total_return_pct']}%, win {stats['win_rate_pct']}%"
            )

            if args.compare:
                base = run_single(
                    args.symbol, tf, MacdFilterConfig(enabled=False), df=df
                )
                baseline.append(base)
        except Exception as exc:
            print(f"  ✗ {tf}: erro — {exc}")
            results.append({"timeframe": tf, "error": str(exc)})

    print_results_table([r for r in results if "error" not in r], label)
    if args.compare and baseline:
        print_results_table(baseline, "Baseline sem MACD")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"mode": macd_cfg.label, "results": results}
    if args.compare:
        payload["without_macd"] = baseline
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Resultados salvos em {out_path}")


if __name__ == "__main__":
    main()
