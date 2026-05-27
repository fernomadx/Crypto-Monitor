#!/usr/bin/env python3
"""
Backtest EMA 20/50 crossover + double retest across multiple timeframes.
Filtros de entrada: MACD ou RSI (sem usar os dois ao mesmo tempo).

Usage:
    python3 backtest/run_backtest.py --compare-rsi
    python3 backtest/run_backtest.py --rsi
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
    RSI_PRESETS,
    EntryFilterConfig,
    MacdFilterConfig,
    RsiFilterConfig,
    generate_signals,
    summarize_trades,
)


DEFAULT_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def build_macd_config(args: argparse.Namespace) -> MacdFilterConfig:
    if args.no_macd or args.rsi:
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


def build_rsi_config(args: argparse.Namespace) -> RsiFilterConfig:
    if args.rsi_cross_50:
        return RsiFilterConfig(
            enabled=True,
            require_above_50=False,
            require_cross_50=True,
        )
    if args.rsi_not_extreme:
        return RsiFilterConfig(
            enabled=True,
            require_above_50=True,
            require_not_overbought=True,
            require_not_oversold=True,
        )
    return RsiFilterConfig(
        enabled=True,
        require_above_50=True,
        require_rising=args.rsi_rising,
    )


def build_entry_config(args: argparse.Namespace) -> EntryFilterConfig:
    if args.rsi:
        return EntryFilterConfig.rsi_only(build_rsi_config(args))
    macd_cfg = build_macd_config(args)
    if macd_cfg.enabled:
        return EntryFilterConfig.macd_only(macd_cfg)
    return EntryFilterConfig.none()


def run_single(
    symbol: str,
    timeframe: str,
    entry_cfg: EntryFilterConfig,
    df: pd.DataFrame | None = None,
) -> dict:
    if df is None:
        limit = candles_for_timeframe(timeframe)
        print(f"  Baixando {symbol} {timeframe} ({limit} candles)...", flush=True)
        df = fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    _, trades = generate_signals(df, entry_filter=entry_cfg)
    stats = summarize_trades(trades)
    stats["timeframe"] = timeframe
    stats["symbol"] = symbol
    stats["candles"] = len(df)
    stats["period_start"] = str(df.index[0])
    stats["period_end"] = str(df.index[-1])
    stats["exchange"] = df.attrs.get("exchange", "unknown")
    stats["pair"] = df.attrs.get("pair", symbol)
    stats["filter_mode"] = entry_cfg.label
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


def print_compare_summary(
    all_results: dict[str, list[dict]],
    title: str,
    reference_mode: str,
) -> None:
    ref = all_results.get(reference_mode, [])
    timeframes = [r["timeframe"] for r in ref if "error" not in r]
    modes = list(all_results.keys())

    col_w = max(12, max(len(m) for m in modes))
    header = "Modo".ljust(col_w) + " | " + " | ".join(tf.ljust(8) for tf in timeframes)
    print(f"\n=== {title} ===\n")
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


def run_compare_presets(
    args: argparse.Namespace,
    presets: dict[str, EntryFilterConfig],
    label: str,
    reference_mode: str,
) -> dict[str, list[dict]]:
    print(f"\n=== {label} — {args.symbol} ===\n")
    all_results: dict[str, list[dict]] = {}
    cached: dict[str, pd.DataFrame] = {}

    for tf in args.timeframes:
        try:
            limit = candles_for_timeframe(tf)
            print(f"  Baixando {args.symbol} {tf} ({limit} candles)...", flush=True)
            cached[tf] = fetch_ohlcv(symbol=args.symbol, timeframe=tf, limit=limit)
        except Exception as exc:
            print(f"  ✗ {tf}: erro download — {exc}")
            for mode in presets:
                all_results.setdefault(mode, []).append(
                    {"timeframe": tf, "error": str(exc)}
                )

    for mode_name, cfg in presets.items():
        mode_results: list[dict] = []
        for tf, df in cached.items():
            mode_results.append(run_single(args.symbol, tf, cfg, df=df))
        all_results[mode_name] = mode_results
        r1h = next((r for r in mode_results if r["timeframe"] == "1h"), {})
        print(
            f"  [{mode_name}] 1h: {r1h.get('total_return_pct', '?')}% "
            f"({r1h.get('total_trades', '?')} trades)"
        )

    for mode_name, mode_results in all_results.items():
        print_results_table(
            [r for r in mode_results if "error" not in r],
            mode_name,
        )

    print_compare_summary(all_results, f"Retorno composto (%) — {label}", reference_mode)
    return all_results


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
    # MACD
    parser.add_argument("--no-macd", action="store_true", help="Sem filtro MACD")
    parser.add_argument("--macd-above-zero", action="store_true")
    parser.add_argument("--macd-above-zero-only", action="store_true")
    parser.add_argument("--macd-hist-rising", action="store_true")
    parser.add_argument("--compare-macd", action="store_true")
    # RSI
    parser.add_argument(
        "--rsi",
        action="store_true",
        help="Usa filtro RSI (sem MACD). Padrão: RSI > 50 long / < 50 short",
    )
    parser.add_argument("--rsi-not-extreme", action="store_true", help="Long 50-70, short 30-50")
    parser.add_argument("--rsi-cross-50", action="store_true", help="Cruzamento da linha 50")
    parser.add_argument("--rsi-rising", action="store_true", help="RSI crescente/decrescente")
    parser.add_argument("--compare-rsi", action="store_true", help="Compara todos modos RSI")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compara config atual vs sem filtro",
    )
    args = parser.parse_args()

    if args.compare_macd and args.compare_rsi:
        parser.error("Use apenas --compare-macd ou --compare-rsi por vez.")

    if args.compare_rsi:
        all_results = run_compare_presets(
            args,
            RSI_PRESETS,
            "Comparação modos RSI (sem MACD)",
            "sem_rsi",
        )
        out_path = Path(args.output)
        if str(out_path) == "backtest/results.json":
            out_path = Path("backtest/results_rsi.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"Resultados salvos em {out_path}")
        return

    if args.compare_macd:
        all_results = run_compare_presets(
            args,
            MACD_PRESETS,
            "Comparação modos MACD (sem RSI)",
            "sem_macd",
        )
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"Resultados salvos em {out_path}")
        return

    entry_cfg = build_entry_config(args)
    if not args.rsi and not args.no_macd and not any(
        [args.macd_above_zero, args.macd_above_zero_only, args.macd_hist_rising]
    ):
        # Comportamento legado: MACD cross ativo por padrão
        entry_cfg = EntryFilterConfig.macd_only(
            MacdFilterConfig(enabled=True, require_cross=True)
        )

    if args.rsi:
        entry_cfg = EntryFilterConfig.rsi_only(build_rsi_config(args))

    label = f"EMA 20/50 + 2 retestes | {entry_cfg.label}"
    print(f"\n=== Backtest {label} — {args.symbol} ===\n")

    results: list[dict] = []
    baseline: list[dict] = []

    for tf in args.timeframes:
        try:
            limit = candles_for_timeframe(tf)
            print(f"  Baixando {args.symbol} {tf} ({limit} candles)...", flush=True)
            df = fetch_ohlcv(symbol=args.symbol, timeframe=tf, limit=limit)

            stats = run_single(args.symbol, tf, entry_cfg, df=df)
            results.append(stats)
            print(
                f"  ✓ {tf}: {stats['total_trades']} trades, "
                f"retorno {stats['total_return_pct']}%, win {stats['win_rate_pct']}%"
            )

            if args.compare:
                base = run_single(args.symbol, tf, EntryFilterConfig.none(), df=df)
                baseline.append(base)
        except Exception as exc:
            print(f"  ✗ {tf}: erro — {exc}")
            results.append({"timeframe": tf, "error": str(exc)})

    print_results_table([r for r in results if "error" not in r], label)
    if args.compare and baseline:
        print_results_table(baseline, "Baseline sem filtro")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"mode": entry_cfg.label, "results": results}
    if args.compare:
        payload["sem_filtro"] = baseline
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Resultados salvos em {out_path}")


if __name__ == "__main__":
    main()
