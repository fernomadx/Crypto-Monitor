"""
EMA 20/50 crossover + double retest strategy (long & short).
Configurable MACD and/or RSI filters on entry (use one at a time).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np
import pandas as pd

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14


class Side(Enum):
    LONG = auto()
    SHORT = auto()


class SetupPhase(Enum):
    IDLE = auto()
    WATCHING_RETESTS = auto()


@dataclass(frozen=True)
class MacdFilterConfig:
    enabled: bool = True
    require_cross: bool = True
    require_above_zero: bool = False
    require_hist_rising: bool = False

    @property
    def label(self) -> str:
        if not self.enabled:
            return "off"
        parts = []
        if self.require_cross:
            parts.append("cross")
        if self.require_above_zero:
            parts.append("zero")
        if self.require_hist_rising:
            parts.append("hist")
        return "+".join(parts) if parts else "macd"


@dataclass(frozen=True)
class RsiFilterConfig:
    enabled: bool = True
    period: int = RSI_PERIOD
    require_above_50: bool = True
    require_not_overbought: bool = False
    require_not_oversold: bool = False
    require_cross_50: bool = False
    require_rising: bool = False

    @property
    def label(self) -> str:
        if not self.enabled:
            return "off"
        parts = []
        if self.require_cross_50:
            parts.append("cross50")
        elif self.require_above_50:
            parts.append("above50")
        if self.require_not_overbought:
            parts.append("lt70")
        if self.require_not_oversold:
            parts.append("gt30")
        if self.require_rising:
            parts.append("rising")
        return "+".join(parts) if parts else "rsi"


@dataclass(frozen=True)
class EntryFilterConfig:
    macd: MacdFilterConfig = field(default_factory=lambda: MacdFilterConfig(enabled=False))
    rsi: RsiFilterConfig = field(default_factory=lambda: RsiFilterConfig(enabled=False))

    @property
    def label(self) -> str:
        if self.rsi.enabled:
            return f"rsi_{self.rsi.label}"
        if self.macd.enabled:
            return f"macd_{self.macd.label}"
        return "sem_filtro"

    @staticmethod
    def none() -> EntryFilterConfig:
        return EntryFilterConfig()

    @staticmethod
    def macd_only(cfg: MacdFilterConfig) -> EntryFilterConfig:
        return EntryFilterConfig(macd=cfg, rsi=RsiFilterConfig(enabled=False))

    @staticmethod
    def rsi_only(cfg: RsiFilterConfig) -> EntryFilterConfig:
        return EntryFilterConfig(
            macd=MacdFilterConfig(enabled=False),
            rsi=cfg,
        )


MACD_PRESETS: dict[str, EntryFilterConfig] = {
    "sem_macd": EntryFilterConfig.none(),
    "cross": EntryFilterConfig.macd_only(
        MacdFilterConfig(enabled=True, require_cross=True)
    ),
    "cross_zero": EntryFilterConfig.macd_only(
        MacdFilterConfig(
            enabled=True, require_cross=True, require_above_zero=True
        )
    ),
    "cross_hist": EntryFilterConfig.macd_only(
        MacdFilterConfig(
            enabled=True, require_cross=True, require_hist_rising=True
        )
    ),
    "full": EntryFilterConfig.macd_only(
        MacdFilterConfig(
            enabled=True,
            require_cross=True,
            require_above_zero=True,
            require_hist_rising=True,
        )
    ),
}

RSI_PRESETS: dict[str, EntryFilterConfig] = {
    "sem_rsi": EntryFilterConfig.none(),
    "above_50": EntryFilterConfig.rsi_only(
        RsiFilterConfig(enabled=True, require_above_50=True)
    ),
    "not_extreme": EntryFilterConfig.rsi_only(
        RsiFilterConfig(
            enabled=True,
            require_above_50=True,
            require_not_overbought=True,
            require_not_oversold=True,
        )
    ),
    "cross_50": EntryFilterConfig.rsi_only(
        RsiFilterConfig(
            enabled=True,
            require_above_50=False,
            require_cross_50=True,
        )
    ),
    "rising": EntryFilterConfig.rsi_only(
        RsiFilterConfig(
            enabled=True,
            require_above_50=True,
            require_rising=True,
        )
    ),
}


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


def compute_macd(
    close: pd.Series,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_indicators(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_period: int = RSI_PERIOD,
) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = out["close"].ewm(span=ema_fast, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=ema_slow, adjust=False).mean()
    macd_line, signal_line, histogram = compute_macd(out["close"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = histogram
    out["rsi"] = compute_rsi(out["close"], period=rsi_period)
    return out


def _zone_bounds(row: pd.Series) -> tuple[float, float]:
    low_band = min(row["ema_fast"], row["ema_slow"])
    high_band = max(row["ema_fast"], row["ema_slow"])
    return low_band, high_band


def macd_allows_long(row: pd.Series, prev: pd.Series, cfg: MacdFilterConfig) -> bool:
    if not cfg.enabled:
        return True
    if cfg.require_cross and not (row["macd"] > row["macd_signal"]):
        return False
    if cfg.require_above_zero and not (row["macd"] > 0):
        return False
    if cfg.require_hist_rising and not (row["macd_hist"] > prev["macd_hist"]):
        return False
    return True


def macd_allows_short(row: pd.Series, prev: pd.Series, cfg: MacdFilterConfig) -> bool:
    if not cfg.enabled:
        return True
    if cfg.require_cross and not (row["macd"] < row["macd_signal"]):
        return False
    if cfg.require_above_zero and not (row["macd"] < 0):
        return False
    if cfg.require_hist_rising and not (row["macd_hist"] < prev["macd_hist"]):
        return False
    return True


def rsi_allows_long(row: pd.Series, prev: pd.Series, cfg: RsiFilterConfig) -> bool:
    if not cfg.enabled:
        return True
    rsi = row["rsi"]
    prev_rsi = prev["rsi"]
    if np.isnan(rsi) or np.isnan(prev_rsi):
        return False
    if cfg.require_cross_50:
        if not (prev_rsi <= 50 < rsi):
            return False
    elif cfg.require_above_50 and not (rsi > 50):
        return False
    if cfg.require_not_overbought and not (rsi < 70):
        return False
    if cfg.require_rising and not (rsi > prev_rsi):
        return False
    return True


def rsi_allows_short(row: pd.Series, prev: pd.Series, cfg: RsiFilterConfig) -> bool:
    if not cfg.enabled:
        return True
    rsi = row["rsi"]
    prev_rsi = prev["rsi"]
    if np.isnan(rsi) or np.isnan(prev_rsi):
        return False
    if cfg.require_cross_50:
        if not (prev_rsi >= 50 > rsi):
            return False
    elif cfg.require_above_50 and not (rsi < 50):
        return False
    if cfg.require_not_oversold and not (rsi > 30):
        return False
    if cfg.require_rising and not (rsi < prev_rsi):
        return False
    return True


def entry_allows_long(row: pd.Series, prev: pd.Series, entry: EntryFilterConfig) -> bool:
    return macd_allows_long(row, prev, entry.macd) and rsi_allows_long(
        row, prev, entry.rsi
    )


def entry_allows_short(row: pd.Series, prev: pd.Series, entry: EntryFilterConfig) -> bool:
    return macd_allows_short(row, prev, entry.macd) and rsi_allows_short(
        row, prev, entry.rsi
    )


def _resolve_entry_filter(
    macd_filter: bool | MacdFilterConfig | None,
    rsi_filter: RsiFilterConfig | None,
    entry_filter: EntryFilterConfig | None,
) -> EntryFilterConfig:
    if entry_filter is not None:
        return entry_filter
    macd_cfg = MacdFilterConfig(enabled=False)
    rsi_cfg = RsiFilterConfig(enabled=False)
    if rsi_filter is not None:
        rsi_cfg = rsi_filter
    if macd_filter is not None:
        if isinstance(macd_filter, bool):
            macd_cfg = MacdFilterConfig(enabled=macd_filter, require_cross=True)
        else:
            macd_cfg = macd_filter
    return EntryFilterConfig(macd=macd_cfg, rsi=rsi_cfg)


def generate_signals(
    df: pd.DataFrame,
    macd_filter: bool | MacdFilterConfig | None = None,
    rsi_filter: RsiFilterConfig | None = None,
    entry_filter: EntryFilterConfig | None = None,
) -> tuple[pd.DataFrame, list[Trade]]:
    entry = _resolve_entry_filter(macd_filter, rsi_filter, entry_filter)
    data = compute_indicators(df, rsi_period=entry.rsi.period)
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
        entry_ok_long = entry_allows_long(row, prev, entry)
        entry_ok_short = entry_allows_short(row, prev, entry)

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

            for key in (
                "long_crossover",
                "short_crossover",
                "long_retest",
                "short_retest",
                "entry_long",
                "entry_short",
            ):
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
            and entry_ok_long
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
            and entry_ok_short
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
