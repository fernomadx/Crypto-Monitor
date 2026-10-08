"""Market structure feature engineering with Polars/NumPy."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from app.schemas import CandleDTO


def candles_to_frame(candles: list[CandleDTO]) -> pl.DataFrame:
    if not candles:
        return pl.DataFrame(
            schema={
                "open_time": pl.Datetime(time_zone="UTC"),
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            }
        )
    return pl.DataFrame(
        {
            "open_time": [c.open_time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    ).sort("open_time")


def ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2 / (period + 1)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    if len(close) < 2:
        return np.zeros_like(close)
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return ema(tr, period)


def swing_points(high: np.ndarray, low: np.ndarray, left: int = 2, right: int = 2) -> dict[str, list[int]]:
    highs: list[int] = []
    lows: list[int] = []
    n = len(high)
    for i in range(left, n - right):
        window_h = high[i - left : i + right + 1]
        window_l = low[i - left : i + right + 1]
        if high[i] == window_h.max() and np.sum(window_h == high[i]) == 1:
            highs.append(i)
        if low[i] == window_l.min() and np.sum(window_l == low[i]) == 1:
            lows.append(i)
    return {"swing_highs": highs, "swing_lows": lows}


def compute_structure_features(candles: list[CandleDTO]) -> dict[str, Any]:
    frame = candles_to_frame(candles)
    if frame.height < 30:
        return {
            "sample_size": frame.height,
            "insufficient": True,
            "trend": "unknown",
            "regime": "uncertain",
        }

    close = frame["close"].to_numpy()
    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    volume = frame["volume"].to_numpy()

    ema20 = ema(close, 20)
    ema50 = ema(close, 50) if len(close) >= 50 else ema(close, max(10, len(close) // 2))
    atr14 = atr(high, low, close, 14)
    returns = np.diff(close) / close[:-1]
    vol = float(np.std(returns[-20:])) if len(returns) >= 20 else float(np.std(returns)) if len(returns) else 0.0

    last = float(close[-1])
    dist_ema20 = (last - float(ema20[-1])) / last
    dist_ema50 = (last - float(ema50[-1])) / last

    lookback = min(48, len(close) - 1)
    range_high = float(np.max(high[-lookback:]))
    range_low = float(np.min(low[-lookback:]))
    range_width = (range_high - range_low) / last if last else 0.0
    position_in_range = (last - range_low) / max(range_high - range_low, 1e-12)

    atr_pct = float(atr14[-1] / last) if last else 0.0
    atr_median = float(np.median(atr14[-50:])) if len(atr14) >= 10 else float(atr14[-1])
    compression = atr_pct < 0.7 * (atr_median / last) if last and atr_median else False
    expansion = atr_pct > 1.3 * (atr_median / last) if last and atr_median else False

    swings = swing_points(high, low)
    hh = hl = lh = ll = False
    sh = swings["swing_highs"]
    sl = swings["swing_lows"]
    if len(sh) >= 2:
        hh = high[sh[-1]] > high[sh[-2]]
        lh = high[sh[-1]] < high[sh[-2]]
    if len(sl) >= 2:
        hl = low[sl[-1]] > low[sl[-2]]
        ll = low[sl[-1]] < low[sl[-2]]

    if hh and hl:
        trend = "uptrend"
    elif lh and ll:
        trend = "downtrend"
    elif range_width < 0.03:
        trend = "range"
    else:
        trend = "transition"

    # Breakout / false breakout heuristics
    breakout_up = last > range_high * 0.999 and close[-2] <= range_high
    breakout_down = last < range_low * 1.001 and close[-2] >= range_low
    vol_avg = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
    vol_confirm = float(volume[-1]) > 1.2 * vol_avg if vol_avg else False
    false_breakout_risk = False
    if breakout_up and not vol_confirm:
        false_breakout_risk = True
    if breakout_down and not vol_confirm:
        false_breakout_risk = True

    impulse = float((close[-1] / close[-5] - 1) if len(close) >= 5 else 0.0)

    regime = "trending" if trend in {"uptrend", "downtrend"} and not compression else (
        "compression" if compression else "expansion" if expansion else "range"
    )

    return {
        "sample_size": int(frame.height),
        "insufficient": False,
        "last_price": last,
        "ema20": float(ema20[-1]),
        "ema50": float(ema50[-1]),
        "dist_ema20_pct": round(dist_ema20 * 100, 4),
        "dist_ema50_pct": round(dist_ema50 * 100, 4),
        "atr14": float(atr14[-1]),
        "atr_pct": round(atr_pct * 100, 4),
        "realized_vol_20": round(vol, 6),
        "range_high": range_high,
        "range_low": range_low,
        "range_width_pct": round(range_width * 100, 4),
        "position_in_range": round(float(position_in_range), 4),
        "trend": trend,
        "regime": regime,
        "compression": compression,
        "expansion": expansion,
        "breakout_up": bool(breakout_up),
        "breakout_down": bool(breakout_down),
        "volume_confirmation": vol_confirm,
        "false_breakout_risk": false_breakout_risk,
        "impulse_5bar_pct": round(impulse * 100, 4),
        "higher_highs": hh,
        "higher_lows": hl,
        "lower_highs": lh,
        "lower_lows": ll,
        "swing_high_count": len(sh),
        "swing_low_count": len(sl),
    }
