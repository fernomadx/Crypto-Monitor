#!/usr/bin/env python3
"""
Backtest SMC simplificado (FVG + CHoCH) com candles MEXC.

Uso:
  python vps/smc_backtest.py --symbol BTCUSDT --interval 4h --limit 500
  python vps/smc_backtest.py --symbol ETHUSDT --interval 1d --rr 2.5
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.mexc_klines import fetch_klines  # noqa: E402
from lib.smc_strategy import SignalType, generate_signals  # noqa: E402

POSITION_USDC = float(os.environ.get("KRONOS_POSITION_USDC", "100"))
INITIAL_CAPITAL = float(os.environ.get("KRONOS_INITIAL_CAPITAL", "1000"))
FEE_MAKER = float(os.environ.get("KRONOS_FEE_MAKER_PCT", "0.02")) / 100
FEE_TAKER = float(os.environ.get("KRONOS_FEE_TAKER_PCT", "0.05")) / 100


@dataclass
class Trade:
    side: str
    entry_idx: int
    exit_idx: int
    entry: float
    exit: float
    pnl_usdc: float
    result: str
    reason: str


def simulate_trades(
    df: pd.DataFrame,
    signals: list,
    max_bars_hold: int = 48,
) -> list[Trade]:
    trades: list[Trade] = []
    occupied_until = -1

    for sig in signals:
        i = sig.bar_idx
        if i <= occupied_until:
            continue

        filled = False
        entry_px = sig.entry
        entry_bar = i

        for j in range(i, min(i + 6, len(df))):
            bar = df.iloc[j]
            if sig.side == SignalType.LONG and float(bar["low"]) <= sig.entry:
                filled = True
                entry_bar = j
                break
            if sig.side == SignalType.SHORT and float(bar["high"]) >= sig.entry:
                filled = True
                entry_bar = j
                break

        if not filled:
            continue

        exit_px = None
        exit_bar = entry_bar
        result = "open"

        for j in range(entry_bar + 1, min(entry_bar + max_bars_hold, len(df))):
            bar = df.iloc[j]
            hi, lo = float(bar["high"]), float(bar["low"])
            if sig.side == SignalType.LONG:
                if lo <= sig.stop:
                    exit_px, exit_bar, result = sig.stop, j, "loss"
                    break
                if hi >= sig.target:
                    exit_px, exit_bar, result = sig.target, j, "gain"
                    break
            else:
                if hi >= sig.stop:
                    exit_px, exit_bar, result = sig.stop, j, "loss"
                    break
                if lo <= sig.target:
                    exit_px, exit_bar, result = sig.target, j, "gain"
                    break

        if exit_px is None:
            j = min(entry_bar + max_bars_hold - 1, len(df) - 1)
            exit_px = float(df.iloc[j]["close"])
            exit_bar = j
            result = "timeout"

        if sig.side == SignalType.LONG:
            gross_pct = (exit_px - entry_px) / entry_px
        else:
            gross_pct = (entry_px - exit_px) / entry_px

        fee = POSITION_USDC * (FEE_MAKER * 2 if result in ("gain", "loss") else FEE_MAKER + FEE_TAKER)
        pnl = POSITION_USDC * gross_pct - fee
        if abs(pnl) < 0.05:
            result = "flat"

        trades.append(
            Trade(
                side=sig.side.value,
                entry_idx=entry_bar,
                exit_idx=exit_bar,
                entry=entry_px,
                exit=exit_px,
                pnl_usdc=round(pnl, 2),
                result=result,
                reason=sig.reason,
            )
        )
        occupied_until = exit_bar

    return trades


def print_report(symbol: str, interval: str, trades: list[Trade], df: pd.DataFrame) -> None:
    print(f"\n{'='*60}")
    print(f"SMC Backtest — {symbol} {interval}")
    print(f"Barras: {len(df)} | {df['timestamps'].iloc[0]} → {df['timestamps'].iloc[-1]}")
    print(f"Capital sim: ${INITIAL_CAPITAL:.0f} | Posição: ${POSITION_USDC:.0f} | Ordens limite")
    print(f"{'='*60}")

    if not trades:
        print("Nenhum trade gerado (regras rígidas ou poucos candles).")
        print("Tente --interval 4h ou 1d com --limit 500.")
        return

    gains = [t for t in trades if t.pnl_usdc > 0.05]
    losses = [t for t in trades if t.pnl_usdc < -0.05]
    total_pnl = sum(t.pnl_usdc for t in trades)
    acc = len(gains) / (len(gains) + len(losses)) * 100 if gains or losses else 0

    print(f"Trades: {len(trades)} | Gain: {len(gains)} | Loss: {len(losses)}")
    print(f"Acertividade (PnL): {acc:.1f}%")
    print(f"PnL total: ${total_pnl:+.2f} ({total_pnl/INITIAL_CAPITAL*100:+.2f}% s/ capital)")
    print(f"Equity final sim: ${INITIAL_CAPITAL + total_pnl:.2f}")
    print("\nÚltimos trades:")
    for t in trades[-8:]:
        icon = "✅" if t.pnl_usdc > 0 else "❌" if t.pnl_usdc < 0 else "➖"
        print(
            f"  {icon} {t.side.upper()} {t.reason} | "
            f"entry {t.entry:.4f} → exit {t.exit:.4f} | ${t.pnl_usdc:+.2f} ({t.result})"
        )
    print(f"\n<i>Backtest educacional — SMC simplificado; não é o mesmo que desenho manual ICT.</i>")


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest SMC (FVG + CHoCH) — MEXC")
    default_sym = os.environ.get("KRONOS_TICKERS", "BTCUSDT").split(",")[0].strip().upper()
    p.add_argument("--symbol", default=default_sym)
    p.add_argument("--interval", default="4h", help="1h, 4h, 1d")
    p.add_argument("--limit", type=int, default=500, help="Candles (máx 500 por request MEXC)")
    p.add_argument("--rr", type=float, default=2.0, help="Risk:reward para o alvo")
    p.add_argument("--max-hold", type=int, default=48, help="Barras máximas em posição")
    args = p.parse_args()

    sym = args.symbol.upper()
    if not sym.endswith("USDT"):
        sym = f"{sym}USDT"

    df = fetch_klines(sym, args.interval, args.limit)
    signals = generate_signals(df, rr=args.rr)
    trades = simulate_trades(df, signals, max_bars_hold=args.max_hold)
    print_report(sym, args.interval, trades, df)


if __name__ == "__main__":
    main()
