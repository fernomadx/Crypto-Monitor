"""Fetch OHLCV candles via ccxt (OKX/Kraken — Binance often geo-blocked)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

EXCHANGE_FALLBACKS = ("okx", "kraken", "kucoin", "bitget")


def _map_symbol(exchange_id: str, symbol: str) -> str:
    if exchange_id == "kraken" and symbol.endswith("/USDT"):
        return symbol.replace("/USDT", "/USD")
    return symbol


def _fetch_from_exchange(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int | None = None,
    max_candles: int = 50_000,
) -> pd.DataFrame:
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})
    pair = _map_symbol(exchange_id, symbol)

    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    since = since_ms
    all_ohlcv: list = []

    while since < (until_ms or exchange.milliseconds()):
        batch = exchange.fetch_ohlcv(pair, timeframe, since=since, limit=300)
        if not batch:
            break
        all_ohlcv.extend(batch)
        since = batch[-1][0] + tf_ms
        if len(batch) < 300:
            break
        if until_ms and batch[-1][0] >= until_ms:
            break
        if len(all_ohlcv) >= max_candles:
            break
        time.sleep(exchange.rateLimit / 1000)

    if until_ms:
        all_ohlcv = [c for c in all_ohlcv if c[0] <= until_ms]

    df = pd.DataFrame(
        all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    df.set_index("timestamp", inplace=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    df.attrs["exchange"] = exchange_id
    df.attrs["pair"] = pair
    return df


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = 1500,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    exchanges = [exchange_id] if exchange_id else list(EXCHANGE_FALLBACKS)
    last_error: Exception | None = None

    for ex_id in exchanges:
        if ex_id is None:
            continue
        try:
            exchange_class = getattr(ccxt, ex_id)
            exchange = exchange_class({"enableRateLimit": True})
            tf_ms = exchange.parse_timeframe(timeframe) * 1000
            since_ms = exchange.milliseconds() - limit * tf_ms
            return _fetch_from_exchange(ex_id, symbol, timeframe, since_ms)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Não foi possível baixar dados OHLCV: {last_error}")


def fetch_ohlcv_range(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    start: datetime | str = "2025-01-01",
    end: datetime | None = None,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV from start date until end (default: now)."""
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end is None:
        end = datetime.now(timezone.utc)
    elif end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    since_ms = int(start.timestamp() * 1000)
    until_ms = int(end.timestamp() * 1000)
    exchanges = [exchange_id] if exchange_id else list(EXCHANGE_FALLBACKS)
    last_error: Exception | None = None

    for ex_id in exchanges:
        if ex_id is None:
            continue
        try:
            df = _fetch_from_exchange(
                ex_id, symbol, timeframe, since_ms, until_ms=until_ms
            )
            t0 = pd.Timestamp(start); t1 = pd.Timestamp(end)
            if t0.tzinfo is None:
                t0 = t0.tz_localize("UTC")
            else:
                t0 = t0.tz_convert("UTC")
            if t1.tzinfo is None:
                t1 = t1.tz_localize("UTC")
            else:
                t1 = t1.tz_convert("UTC")
            df = df[(df.index >= t0) & (df.index <= t1)]
            return df
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Não foi possível baixar dados OHLCV: {last_error}")


def candles_for_timeframe(timeframe: str) -> int:
    mapping = {
        "5m": 8000,
        "15m": 6000,
        "1h": 4320,
        "4h": 1080,
        "1d": 730,
    }
    return mapping.get(timeframe, 1500)
