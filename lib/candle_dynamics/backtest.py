"""
Simulador de backtest — Candle Dynamics.

Regras de proteção (seção 5):
  - v1/v2: move stop para BE após movimento a favor
  - v2-short: após 3R a favor, trava stop em +1R (profit-lock); hold até 36h
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
    stop: float = 0.0
    notional: float = 0.0
    leverage_used: float = 0.0
    equity_before: float = 0.0


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
    sizing: str = "fixed"
    risk_pct: float = 0.0
    max_leverage: float = 1.0

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
    def final_equity(self) -> float:
        return self.initial_capital + self.total_pnl

    @property
    def return_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return 100.0 * self.total_pnl / self.initial_capital

    @property
    def cagr_pct(self) -> float:
        """CAGR aproximado pelo horizonte calendário do backtest."""
        days = max((self.end - self.start).total_seconds() / 86400.0, 1.0)
        years = days / 365.25
        if years <= 0 or self.initial_capital <= 0 or self.final_equity <= 0:
            return 0.0
        return 100.0 * ((self.final_equity / self.initial_capital) ** (1.0 / years) - 1.0)

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

    @property
    def max_drawdown_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return 100.0 * self.max_drawdown_usdc / self.initial_capital

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
            year = t.entry_ts[:4] if t.entry_ts else "unknown"
            yslot = by_year.setdefault(year, {"n": 0, "pnl": 0.0})
            yslot["n"] = int(yslot["n"]) + 1
            yslot["pnl"] = float(yslot["pnl"]) + t.pnl_usdc

        avg_lev = 0.0
        if self.trades:
            avg_lev = sum(t.leverage_used for t in self.trades) / len(self.trades)

        return {
            "symbol": self.symbol,
            "period": f"{self.start.date()} → {self.end.date()}",
            "bars": self.bars,
            "trades": self.n,
            "gains": len(self.gains),
            "losses": len(self.losses),
            "win_rate_pct": round(self.win_rate, 1),
            "pnl_usdc": round(self.total_pnl, 2),
            "equity_final": round(self.final_equity, 2),
            "return_pct": round(self.return_pct, 1),
            "cagr_pct": round(self.cagr_pct, 1),
            "profit_factor": round(self.profit_factor, 2),
            "max_dd_usdc": round(self.max_drawdown_usdc, 2),
            "max_dd_pct": round(self.max_drawdown_pct, 1),
            "sizing": self.sizing,
            "risk_pct": self.risk_pct,
            "max_leverage": self.max_leverage,
            "avg_leverage": round(avg_lev, 2),
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
    initial_capital: float = 1000.0,
    sizing: str = "fixed",  # fixed | risk
    risk_pct: float = 2.0,  # % do equity arriscado no stop (sizing=risk)
    max_leverage: float = 8.0,
) -> list[Trade]:
    trades: list[Trade] = []
    occupied_until = -1
    equity = initial_capital

    highs = df_5m["high"].to_numpy(dtype=float)
    lows = df_5m["low"].to_numpy(dtype=float)
    closes = df_5m["close"].to_numpy(dtype=float)

    # Perfis de saída por versão
    max_stop_pct_filter: float | None = None
    # profit_lock: (activate_R, floor_R) — após activate_R a favor, stop trava +floor_R
    profit_lock: tuple[float, float] | None = None
    if version == "v2-short":
        # 36h hold + lock +1R após 3R (melhor CAGR/PF vs BE flat @2.5R)
        max_bars_hold = max(max_bars_hold, 432)
        min_be_profit_pct = fee_pct * 2.5
        short_be_r = 99.0  # desativa BE clássico; usa profit_lock
        profit_lock = (3.0, 1.0)
        max_stop_pct_filter = 1.0
    elif version == "v2":
        max_bars_hold = max(max_bars_hold, 144)
        min_be_profit_pct = fee_pct * 2.5
        short_be_r = 1.2
    else:
        min_be_profit_pct = 0.0
        short_be_r = max(be_trigger_r, 1.0)

    for sig in signals:
        i = sig.bar_idx
        if i <= occupied_until or i >= len(df_5m) - 2:
            continue
        if equity <= initial_capital * 0.05:
            break

        entry = sig.entry
        stop = sig.stop
        target = sig.target
        partial = sig.partial_target
        side = sig.side
        be_moved = False
        partial_taken = False
        realized = 0.0
        size = 1.0
        stop_price = stop

        risk = (entry - stop) if side == Side.LONG else (stop - entry)
        if risk <= 0:
            continue

        stop_pct = risk / entry * 100.0
        if max_stop_pct_filter is not None and stop_pct > max_stop_pct_filter:
            continue
        if version == "v2-short" and stop_pct < 0.05:
            continue

        if side == Side.SHORT and (entry - target) / risk < 2.0:
            target = entry - risk * 2.0
        if side == Side.LONG and (target - entry) / risk < 2.0:
            target = entry + risk * 2.0

        # --- Sizing ---
        equity_before = equity
        if sizing == "risk":
            # notional tal que perda no stop ≈ risk_pct% do equity
            notional = (equity * (risk_pct / 100.0)) / (stop_pct / 100.0)
            lev = notional / equity if equity > 0 else 0.0
            if lev > max_leverage:
                notional = equity * max_leverage
                lev = max_leverage
        else:
            notional = position_usdc
            lev = notional / equity if equity > 0 else 0.0

        if notional <= 0:
            continue

        exit_px = None
        exit_idx = i
        result = "timeout"

        end_j = min(i + max_bars_hold, len(df_5m) - 1)
        for j in range(i + 1, end_j + 1):
            hi, lo = float(highs[j]), float(lows[j])

            if version == "v2-short":
                be_r = short_be_r
            elif version == "v2":
                be_r = 0.8 if sig.is_counter_trend else short_be_r
            else:
                be_r = (
                    be_trigger_r
                    if sig.is_counter_trend or "zona_compra" in sig.reason
                    else max(be_trigger_r, 1.0)
                )

            favor_r = ((hi - entry) / risk) if side == Side.LONG else ((entry - lo) / risk)

            if profit_lock is not None:
                act_r, floor_r = profit_lock
                if favor_r >= act_r:
                    if side == Side.LONG:
                        stop = entry + floor_r * risk
                    else:
                        stop = entry - floor_r * risk
                    be_moved = True
            elif not be_moved:
                moved = False
                if side == Side.LONG and hi >= entry + be_r * risk:
                    moved = True
                elif side == Side.SHORT and lo <= entry - be_r * risk:
                    moved = True
                if moved:
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

            locked_gain = be_moved and (
                (side == Side.LONG and stop > entry + 1e-12)
                or (side == Side.SHORT and stop < entry - 1e-12)
            )
            if side == Side.LONG:
                if lo <= stop:
                    if locked_gain:
                        tag = "gain"
                    elif be_moved and abs(stop - entry) < 1e-9:
                        tag = "flat"
                    else:
                        tag = "loss"
                    exit_px, exit_idx, result = stop, j, tag
                    break
                if hi >= target:
                    exit_px, exit_idx, result = target, j, "gain"
                    break
            else:
                if hi >= stop:
                    if locked_gain:
                        tag = "gain"
                    elif be_moved and abs(stop - entry) < 1e-9:
                        tag = "flat"
                    else:
                        tag = "loss"
                    exit_px, exit_idx, result = stop, j, tag
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
        fee = notional * (fee_pct / 100.0) * (1.5 if partial_taken else 1.0)
        pnl_usdc = notional * (gross_pct / 100.0) - fee
        # Limita perda ao risco no stop (isolado)
        max_loss = notional * (stop_pct / 100.0)
        pnl_usdc = max(pnl_usdc, -max_loss)
        equity += pnl_usdc

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
                stop=float(stop_price),
                notional=round(notional, 2),
                leverage_used=round(lev, 2),
                equity_before=round(equity_before, 2),
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
    sizing: str = "fixed",
    risk_pct: float = 2.0,
    max_leverage: float = 8.0,
    **signal_kwargs: Any,
) -> BacktestResult:
    # Default realista para v2-short: sizing por risco (senão retorno absoluto fica irrelevante)
    if version == "v2-short" and sizing == "fixed" and "sizing" not in signal_kwargs:
        # Mantém fixed se caller passou explicitamente position-only compare;
        # CLI decide. Aqui respeita o parâmetro sizing.
        pass

    signal_kwargs = {**signal_kwargs, "version": version}
    signals = generate_signals(df_5m, df_30m, df_1h, df_1d, df_1w, **signal_kwargs)
    trades = simulate_trades(
        df_5m,
        signals,
        position_usdc=position_usdc,
        version=version,
        initial_capital=initial_capital,
        sizing=sizing,
        risk_pct=risk_pct,
        max_leverage=max_leverage,
    )
    result = BacktestResult(
        symbol=symbol,
        interval_confirm="5m",
        start=pd.Timestamp(df_5m["timestamps"].iloc[0]),
        end=pd.Timestamp(df_5m["timestamps"].iloc[-1]),
        bars=len(df_5m),
        trades=trades,
        initial_capital=initial_capital,
        position_usdc=position_usdc,
        sizing=sizing,
        risk_pct=risk_pct if sizing == "risk" else 0.0,
        max_leverage=max_leverage if sizing == "risk" else 1.0,
    )
    result._version = version  # type: ignore[attr-defined]
    return result
