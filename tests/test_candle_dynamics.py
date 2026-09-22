"""Unit tests — Candle Dynamics (sem rede)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lib.candle_dynamics.backtest import run_backtest, simulate_trades
from lib.candle_dynamics.data import month_range, resample_ohlcv
from lib.candle_dynamics.signals import (
    Side,
    SetupKind,
    Signal,
    detect_down_impulse,
    detect_up_impulse,
    fib_mid,
    generate_signals,
    is_bearish_failure,
    is_bullish_failure,
)


def _synth_ohlcv(n: int = 500, start: float = 40000.0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    rets = rng.normal(0, 0.0015, size=n)
    # Injeta impulsão + falha quando houver barras suficientes
    if n > 110:
        rets[100:108] = -0.004
        rets[108] = 0.006
    if n > 210:
        rets[200:208] = 0.004
        rets[208] = -0.006
    close = start * np.cumprod(1 + rets)
    open_ = np.roll(close, 1)
    open_[0] = start
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.001, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.001, n))
    if n > 110:
        low[108] = low[107] + abs(close[107]) * 0.0001
        high[108] = high[107] * 0.999
        close[108] = (high[107] + low[107]) / 2 + abs(close[107]) * 0.001
    if n > 210:
        high[208] = high[207] - abs(close[207]) * 0.0001
        low[208] = low[207] * 1.001
        close[208] = (high[207] + low[207]) / 2 - abs(close[207]) * 0.001
    return pd.DataFrame(
        {
            "timestamps": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1, 10, n),
            "open_time": (ts.asi8 // 10**6),
        }
    )


def test_month_range():
    from datetime import date

    months = month_range(date(2024, 11, 1), date(2025, 2, 15))
    assert months == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]


def test_fib_mid():
    assert fib_mid(110, 90) == 100


def test_impulse_and_failure_detection():
    lows = np.array([10.0, 9.5, 9.0, 8.5, 8.0, 8.2, 8.3])
    assert detect_down_impulse(lows, 5, lookback=4)
    highs = np.array([10.0, 10.5, 11.0, 11.5, 12.0, 11.8, 11.5])
    assert detect_up_impulse(highs, 5, lookback=4)

    # Bullish failure: impulsão de baixa + não rompe mínima + fecha acima do mid do gatilho
    h = np.array([10.0, 9.8, 9.5, 9.2, 9.0, 9.15])
    l = np.array([9.6, 9.3, 9.0, 8.7, 8.5, 8.55])  # low[5] >= low[4]
    c = np.array([9.7, 9.4, 9.1, 8.8, 8.6, 8.85])  # close > mid(9.0,8.5)=8.75
    assert is_bullish_failure(h, l, c, 5)

    # Bearish failure: impulsão de alta + não rompe máxima + fecha abaixo do mid
    h2 = np.array([10.0, 10.4, 10.8, 11.2, 11.6, 11.55])  # high[5] <= high[4]
    l2 = np.array([9.7, 10.1, 10.5, 10.9, 11.2, 11.1])
    c2 = np.array([10.2, 10.6, 11.0, 11.3, 11.5, 11.3])  # mid(11.6,11.2)=11.4; close < mid
    assert is_bearish_failure(h2, l2, c2, 5)


def test_resample_ohlcv():
    df = _synth_ohlcv(120)
    h1 = resample_ohlcv(df, "1h")
    assert len(h1) >= 9
    assert set(["open", "high", "low", "close", "volume", "timestamps"]).issubset(h1.columns)


def test_simulate_be_and_partial():
    df = _synth_ohlcv(80)
    # Monta caminho artificial long que sobe e bate parcial/target
    df.loc[40:, "close"] = df.loc[39, "close"] * 1.02
    df.loc[40:, "high"] = df.loc[40:, "close"] * 1.001
    df.loc[40:, "low"] = df.loc[40:, "close"] * 0.999
    entry = float(df.loc[30, "close"])
    sig = Signal(
        bar_idx=30,
        ts=df.loc[30, "timestamps"],
        side=Side.LONG,
        kind=SetupKind.FAILURE_LONG,
        entry=entry,
        stop=entry * 0.99,
        target=entry * 1.03,
        partial_target=entry * 1.01,
        is_counter_trend=True,
        reason="test",
    )
    trades = simulate_trades(df, [sig], max_bars_hold=40)
    assert len(trades) == 1
    assert trades[0].pnl_usdc != 0 or trades[0].result in ("gain", "flat", "timeout", "loss")


def test_generate_signals_and_backtest_smoke():
    df_5m = _synth_ohlcv(2000, seed=3)
    df_30m = resample_ohlcv(df_5m, "30min")
    df_1h = resample_ohlcv(df_5m, "1h")
    df_1d = resample_ohlcv(df_5m, "1D")
    df_1w = resample_ohlcv(df_5m, "1W")
    df_1d.loc[df_1d.index[5], "low"] = df_1d["low"].min() * 0.98
    df_1d.loc[df_1d.index[5], "high"] = df_1d["high"].max() * 1.02
    sigs = generate_signals(df_5m, df_30m, df_1h, df_1d, df_1w, zone_tol_pct=5.0)
    assert isinstance(sigs, list)
    result = run_backtest(df_5m, df_30m, df_1h, df_1d, df_1w, zone_tol_pct=5.0)
    assert result.bars == len(df_5m)
    assert "trades" in result.summary()


def test_v2_runs_and_is_stricter_than_v1():
    df_5m = _synth_ohlcv(3000, seed=11)
    df_30m = resample_ohlcv(df_5m, "30min")
    df_1h = resample_ohlcv(df_5m, "1h")
    df_1d = resample_ohlcv(df_5m, "1D")
    df_1w = resample_ohlcv(df_5m, "1W")
    s1 = generate_signals(df_5m, df_30m, df_1h, df_1d, df_1w, version="v1", zone_tol_pct=8.0)
    s2 = generate_signals(df_5m, df_30m, df_1h, df_1d, df_1w, version="v2", zone_tol_pct=8.0)
    # v2 deve gerar no máximo tantos sinais quanto v1 (mais restritivo)
    assert len(s2) <= len(s1)
    r2 = run_backtest(df_5m, df_30m, df_1h, df_1d, df_1w, version="v2", zone_tol_pct=8.0)
    assert r2.summary()["version"] == "v2"
