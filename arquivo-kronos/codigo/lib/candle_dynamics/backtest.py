"""
Simulador de backtest — Candle Dynamics.

Regras de proteção (seção 5):
  - Move stop para zero-a-zero assim que a operação anda a favor (BE)
  - Em retração contra a tendência: parcial na região de 50%
  - Só opera em zona (já filtrado nos sinais)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from lib.candle_dynamics.signals import Side, Signal, generate_signals


@dataclass
class Trade:
    side: str
    kind: str
    entry_idx: int
    exit_idx: int
    entry: float
    exit: float
    pnl_pct: float
    pnl_usdc: float
    result: str
    reason: str
    be_moved: bool = False
    partial_taken: bool = False
    entry_ts: str = ""


@dataclass
class BacktestResult:
    symbol: str
    interval_confirm: str
    start: pd.Timestamp
    end: pd.Timestamp
    bars: int
    trades: list[Trade] = field(default_factory=list)
    initial_capital: float = 1000.0
    position_usdc: float = 100.0

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def gains(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl_usdc > 0.05]

    @property
    def losses(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl_usdc < -0.05]

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_usdc for t in self.trades)

    @property
    def win_rate(self) -> float:
        decided = len(self.gains) + len(self.losses)
        if decided == 0:
            return 0.0
        return 100.0 * len(self.gains) / decided

    @property
    def profit_factor(self) -> float:
        gw = sum(t.pnl_usdc for t in self.gains)
        gl = abs(sum(t.pnl_usdc for t in self.losses))
        if gl <= 0:
            return 999.0 if gw > 0 else 0.0
        return gw / gl

    @property
    def max_drawdown_usdc(self) -> float:
        equity = self.initial_capital
        peak = equity
        max_dd = 0.0
        for t in self.trades:
            equity += t.pnl_usdc
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return max_dd

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, dict[str, float | int]] = {}
        for t in self.trades:
            slot = by_kind.setdefault(t.kind, {"n": 0, "pnl": 0.0, "gains": 0, "losses": 0})
            slot["n"] = int(slot["n"]) + 1
            slot["pnl"] = float(slot["pnl"]) + t.pnl_usdc
            if t.pnl_usdc > 0.05:
                slot["gains"] = int(slot["gains"]) + 1
            elif t.pnl_usdc < -0.05:
                slot["losses"] = int(slot["losses"]) + 1

        by_year: dict[str, dict[str, float | int]] = {}
        for t in self.trades:
            year = (t.entry_ts[:4] if t.entry_ts else "unknown")
            yslot = by_year.setdefault(year, {"n": 0, "pnl": 0.0})
            yslot["n"] = int(yslot["n"]) + 1
            yslot["pnl"] = float(yslot["pnl"]) + t.pnl_usdc

        return {
            "symbol": self.symbol,
            "period": f"{self.start.date()} → {self.end.date()}",
            "bars": self.bars,
            "trades": self.n,
            "gains": len(self.gains),
            "losses": len(self.losses),
            "win_rate_pct": round(self.win_rate, 1),
            "pnl_usdc": round(self.total_pnl, 2),
            "equity_final": round(self.initial_capital + self.total_pnl, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_dd_usdc": round(self.max_drawdown_usdc, 2),
            "by_kind": {
                k: {
                    "n": v["n"],
                    "pnl": round(float(v["pnl"]), 2),
                    "win_rate_pct": round(
                        100 * int(v["gains"]) / max(1, int(v["gains"]) + int(v["losses"])),
                        1,
                    ),
                }
                for k, v in by_kind.items()
            },
            "by_year": {
                k: {"n": v["n"], "pnl": round(float(v["pnl"]), 2)} for k, v in sorted(by_year.items())
            },
            "verdict": (
                "INVALIDATED"
                if self.n >= 30 and (self.profit_factor < 1.0 or self.total_pnl < 0)
                else "INCONCLUSIVE"
                if self.n < 30
                else "PROMISING"
            ),
            "version": getattr(self, "_version", "v1"),
        }


def simulate_trades(
    df_5m: pd.DataFrame,
    signals: list[Signal],
    *,
    position_usdc: float = 100.0,
    fee_pct: float = 0.04,  # round-trip approx taker+taker spot
    be_trigger_r: float = 0.6,  # move BE após 0.6R a favor
    max_bars_hold: int = 96,  # 96 * 5m = 8h
    partial_frac: float = 0.5,
    version: str = "v1",
) -> list[Trade]:
    trades: list[Trade] = []
    occupied_until = -1

    highs = df_5m["high"].to_numpy(dtype=float)
    lows = df_5m["low"].to_numpy(dtype=float)
    closes = df_5m["close"].to_numpy(dtype=float)

    # v2 / v2-short: hold mais longo; BE fee-aware
    if version in ("v2", "v2-short"):
        max_bars_hold = max(max_bars_hold, 144)  # 12h
        min_be_profit_pct = fee_pct * 2.5
    else:
        min_be_profit_pct = 0.0

    for sig in signals:
        i = sig.bar_idx
        if i <= occupied_until or i >= len(df_5m) - 2:
            continue

        entry = sig.entry
        stop = sig.stop
        target = sig.target
        partial = sig.partial_target
        side = sig.side
        be_moved = False
        partial_taken = False
        realized = 0.0
        size = 1.0

        risk = (entry - stop) if side == Side.LONG else (stop - entry)
        if risk <= 0:
            continue

        exit_px = None
        exit_idx = i
        result = "timeout"

        end_j = min(i + max_bars_hold, len(df_5m) - 1)
        for j in range(i + 1, end_j + 1):
            hi, lo = float(highs[j]), float(lows[j])

            # BE: v1 rápido em retração; v2 seletivo + fee-aware
            if version in ("v2", "v2-short"):
                if sig.is_counter_trend:
                    be_r = max(be_trigger_r, 0.8)
                else:
                    be_r = max(be_trigger_r, 1.2)
            else:
                be_r = (
                    be_trigger_r
                    if sig.is_counter_trend or "zona_compra" in sig.reason
                    else max(be_trigger_r, 1.0)
                )

            if not be_moved:
                moved = False
                if side == Side.LONG and hi >= entry + be_r * risk:
                    moved = True
                elif side == Side.SHORT and lo <= entry - be_r * risk:
                    moved = True
                if moved:
                    # Só BE se o movimento a favor já cobrir taxa (evita flat-$0.04)
                    favor_pct = be_r * risk / entry * 100.0
                    if favor_pct >= min_be_profit_pct:
                        stop = entry
                        be_moved = True

            if (
                partial is not None
                and not partial_taken
                and sig.is_counter_trend
                and size > partial_frac
            ):
                if side == Side.LONG and hi >= partial:
                    part_pnl = (partial - entry) / entry
                    realized += part_pnl * partial_frac
                    size -= partial_frac
                    partial_taken = True
                elif side == Side.SHORT and lo <= partial:
                    part_pnl = (entry - partial) / entry
                    realized += part_pnl * partial_frac
                    size -= partial_frac
                    partial_taken = True

            if side == Side.LONG:
                if lo <= stop:
                    exit_px, exit_idx, result = stop, j, (
                        "flat" if be_moved and abs(stop - entry) < 1e-9 else "loss"
                    )
                    break
                if hi >= target:
                    exit_px, exit_idx, result = target, j, "gain"
                    break
            else:
                if hi >= stop:
                    exit_px, exit_idx, result = stop, j, (
                        "flat" if be_moved and abs(stop - entry) < 1e-9 else "loss"
                    )
                    break
                if lo <= target:
                    exit_px, exit_idx, result = target, j, "gain"
                    break

        if exit_px is None:
            exit_idx = end_j
            exit_px = float(closes[exit_idx])
            result = "timeout"

        if side == Side.LONG:
            rest_pnl = (exit_px - entry) / entry
        else:
            rest_pnl = (entry - exit_px) / entry

        gross_pct = (realized + rest_pnl * size) * 100.0
        fee = position_usdc * (fee_pct / 100.0) * (1.5 if partial_taken else 1.0)
        pnl_usdc = position_usdc * (gross_pct / 100.0) - fee

        if abs(pnl_usdc) < 0.05 and result in ("loss", "gain", "timeout"):
            result = "flat"

        trades.append(
            Trade(
                side=side.value,
                kind=sig.kind.value,
                entry_idx=i,
                exit_idx=exit_idx,
                entry=entry,
                exit=float(exit_px),
                pnl_pct=round(gross_pct, 4),
                pnl_usdc=round(pnl_usdc, 2),
                result=result,
                reason=sig.reason,
                be_moved=be_moved,
                partial_taken=partial_taken,
                entry_ts=str(sig.ts),
            )
        )
        occupied_until = exit_idx

    return trades


def run_backtest(
    df_5m: pd.DataFrame,
    df_30m: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    df_1w: pd.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    initial_capital: float = 1000.0,
    position_usdc: float = 100.0,
    version: str = "v1",
    **signal_kwargs: Any,
) -> BacktestResult:
    signal_kwargs = {**signal_kwargs, "version": version}
    signals = generate_signals(df_5m, df_30m, df_1h, df_1d, df_1w, **signal_kwargs)
    trades = simulate_trades(df_5m, signals, position_usdc=position_usdc, version=version)
    result = BacktestResult(
        symbol=symbol,
        interval_confirm="5m",
        start=pd.Timestamp(df_5m["timestamps"].iloc[0]),
        end=pd.Timestamp(df_5m["timestamps"].iloc[-1]),
        bars=len(df_5m),
        trades=trades,
        initial_capital=initial_capital,
        position_usdc=position_usdc,
    )
    # anexa versão no summary via monkey patch leve
    result._version = version  # type: ignore[attr-defined]
    return result
