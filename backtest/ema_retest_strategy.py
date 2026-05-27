"""
EMA 20/50 crossover + double retest strategy (long & short).

Rules (long):
  1. Bullish trend: close above 20 and 50 EMA
  2. Confirmation: 20 EMA crosses above 50 EMA
  3. After crossover, price retests the zone between EMAs twice
     (low enters zone, close stays >= 50 EMA, then close reclaims 20 EMA)
  4. Enter long on confirmation after 2nd retest (close > 20 EMA)
  5. Stop: below 50 EMA (intrabar low breach)
  6. Exit: candle closes below 50 EMA
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
import pandas as pd


class Side(Enum):
    LONG = auto()
    SHORT = auto()


class SetupPhase(Enum):
    IDLE = auto()
    WATCHING_RETESTS = auto()


@dataclass
class Trade:
    side: Side
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    @property
    def pnl_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        if self.side == Side.LONG:
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - self.exit_price) / self.entry_price * 100


def compute_emas(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = out["close"].ewm(span=fast, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=slow, adjust=False).mean()
    return out


def _zone_bounds(row: pd.Series) -> tuple[float, float]:
    low_band = min(row["ema_fast"], row["ema_slow"])
    high_band = max(row["ema_fast"], row["ema_slow"])
    return low_band, high_band


def generate_signals(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Trade]]:
    """Run strategy bar-by-bar; returns annotated frame and completed trades."""
    data = compute_emas(df)
    trades: list[Trade] = []

    long_phase = SetupPhase.IDLE
    long_retest_active = False
    long_retest_count = 0

    short_phase = SetupPhase.IDLE
    short_retest_active = False
    short_retest_count = 0

    position: Trade | None = None

    signals: dict[str, list] = {
        "long_crossover": [],
        "short_crossover": [],
        "long_retest": [],
        "short_retest": [],
        "entry_long": [],
        "entry_short": [],
        "exit": [],
    }

    for i in range(1, len(data)):
        row = data.iloc[i]
        prev = data.iloc[i - 1]
        ts = data.index[i]

        bullish_trend = row["close"] > row["ema_fast"] and row["close"] > row["ema_slow"]
        bearish_trend = row["close"] < row["ema_fast"] and row["close"] < row["ema_slow"]

        bull_cross = (
            prev["ema_fast"] <= prev["ema_slow"]
            and row["ema_fast"] > row["ema_slow"]
        )
        bear_cross = (
            prev["ema_fast"] >= prev["ema_slow"]
            and row["ema_fast"] < row["ema_slow"]
        )

        zone_lo, zone_hi = _zone_bounds(row)

        if position is not None:
            if position.side == Side.LONG:
                stopped = row["low"] < row["ema_slow"]
                exit_signal = row["close"] < row["ema_slow"]
                if stopped or exit_signal:
                    reason = (
                        "stop_below_ema50"
                        if stopped and not exit_signal
                        else "close_below_ema50"
                    )
                    exit_px = float(row["ema_slow"]) if stopped else float(row["close"])
                    position.exit_time = ts
                    position.exit_price = exit_px
                    position.exit_reason = reason
                    trades.append(position)
                    position = None
                    signals["exit"].append(True)
                else:
                    signals["exit"].append(False)
            else:
                stopped = row["high"] > row["ema_slow"]
                exit_signal = row["close"] > row["ema_slow"]
                if stopped or exit_signal:
                    reason = (
                        "stop_above_ema50"
                        if stopped and not exit_signal
                        else "close_above_ema50"
                    )
                    exit_px = float(row["ema_slow"]) if stopped else float(row["close"])
                    position.exit_time = ts
                    position.exit_price = exit_px
                    position.exit_reason = reason
                    trades.append(position)
                    position = None
                    signals["exit"].append(True)
                else:
                    signals["exit"].append(False)

            for key in ("long_crossover", "short_crossover", "long_retest", "short_retest", "entry_long", "entry_short"):
                signals[key].append(False)
            continue

        signals["exit"].append(False)
        signals["long_crossover"].append(bull_cross)

        if bull_cross and bullish_trend:
            long_phase = SetupPhase.WATCHING_RETESTS
            long_retest_count = 0
            long_retest_active = False
        elif long_phase == SetupPhase.WATCHING_RETESTS:
            if not bullish_trend or row["close"] < row["ema_slow"]:
                long_phase = SetupPhase.IDLE
                long_retest_count = 0
                long_retest_active = False
            else:
                touched_zone = row["low"] <= zone_hi and row["low"] >= zone_lo
                if touched_zone and row["close"] >= row["ema_slow"]:
                    long_retest_active = True
                if long_retest_active and row["close"] > row["ema_fast"]:
                    long_retest_count += 1
                    long_retest_active = False

        entered_long = False
        if (
            long_phase == SetupPhase.WATCHING_RETESTS
            and long_retest_count >= 2
            and row["close"] > row["ema_fast"]
            and row["ema_fast"] > row["ema_slow"]
            and bullish_trend
        ):
            position = Trade(Side.LONG, ts, float(row["close"]))
            entered_long = True
            long_phase = SetupPhase.IDLE
            long_retest_count = 0

        signals["long_retest"].append(long_retest_active)
        signals["entry_long"].append(entered_long)

        signals["short_crossover"].append(bear_cross)
        if bear_cross and bearish_trend:
            short_phase = SetupPhase.WATCHING_RETESTS
            short_retest_count = 0
            short_retest_active = False
        elif short_phase == SetupPhase.WATCHING_RETESTS:
            if not bearish_trend or row["close"] > row["ema_slow"]:
                short_phase = SetupPhase.IDLE
                short_retest_count = 0
                short_retest_active = False
            else:
                touched_zone = row["high"] >= zone_lo and row["high"] <= zone_hi
                if touched_zone and row["close"] <= row["ema_slow"]:
                    short_retest_active = True
                if short_retest_active and row["close"] < row["ema_fast"]:
                    short_retest_count += 1
                    short_retest_active = False

        entered_short = False
        if (
            short_phase == SetupPhase.WATCHING_RETESTS
            and short_retest_count >= 2
            and row["close"] < row["ema_fast"]
            and row["ema_fast"] < row["ema_slow"]
            and bearish_trend
            and position is None
        ):
            position = Trade(Side.SHORT, ts, float(row["close"]))
            entered_short = True
            short_phase = SetupPhase.IDLE
            short_retest_count = 0

        signals["short_retest"].append(short_retest_active)
        signals["entry_short"].append(entered_short)

    for key in signals:
        signals[key].insert(0, False)

    for col, vals in signals.items():
        data[col] = vals

    return data, trades


def summarize_trades(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "total_return_pct": 0.0,
            "avg_return_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "long_trades": 0,
            "short_trades": 0,
        }

    pnls = [t.pnl_pct for t in trades if t.pnl_pct is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    equity = 100.0
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity *= 1 + p / 100
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    return {
        "total_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
        "total_return_pct": round(equity - 100, 2),
        "avg_return_pct": round(float(np.mean(pnls)), 2) if pnls else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_drawdown_pct": round(max_dd, 2),
        "long_trades": sum(1 for t in trades if t.side == Side.LONG),
        "short_trades": sum(1 for t in trades if t.side == Side.SHORT),
    }
