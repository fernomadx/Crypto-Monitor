"""Candles OHLCV públicos da MEXC (compartilhado por Kronos e scorecard)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import requests

MEXC_BASE = "https://api.mexc.com"
MEXC_INTERVAL_MAP = {"1h": "60m", "1H": "60m"}
MEXC_KLINES_MAX_LIMIT = 500

INTERVAL_DELTAS = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "60m": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def mexc_interval(interval: str) -> str:
    return MEXC_INTERVAL_MAP.get(interval, interval)


def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    api_interval = mexc_interval(interval)
    safe_limit = min(max(int(limit), 1), MEXC_KLINES_MAX_LIMIT)
    resp = requests.get(
        f"{MEXC_BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": api_interval, "limit": safe_limit},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise ValueError(f"Sem candles para {symbol}")

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume",
        ],
    )
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["amount"] = df["quote_volume"].astype(float)
    return df


def fetch_close_at(symbol: str, interval: str, candle_open: pd.Timestamp) -> float | None:
    """Close do candle MEXC com open_time = candle_open (UTC)."""
    api_interval = mexc_interval(interval)
    ts = pd.Timestamp(candle_open)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    delta = INTERVAL_DELTAS.get(interval, timedelta(hours=1))
    margin = delta * 3
    start_ms = int((ts - margin).timestamp() * 1000)
    end_ms = int((ts + margin).timestamp() * 1000)
    resp = requests.get(
        f"{MEXC_BASE}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": api_interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 20,
        },
        timeout=30,
    )
    if not resp.ok:
        return None
    rows = resp.json()
    target_ms = int(ts.timestamp() * 1000)
    for row in rows:
        if int(row[0]) == target_ms:
            return float(row[4])
    return None


def bars_to_timedelta(interval: str, bars: int) -> timedelta:
    delta = INTERVAL_DELTAS.get(interval)
    if not delta:
        raise ValueError(f"Intervalo inválido: {interval}")
    return delta * bars
