"""Fetch OHLCV candles via ccxt (OKX/Kraken — Binance often geo-blocked)."""

from __future__ import annotations

import time

import ccxt
import pandas as pd

EXCHANGE_FALLBACKS = ("okx", "kraken", "kucoin", "bitget")


def _map_symbol(exchange_id: str, symbol: str) -> str:
    if exchange_id == "kraken" and symbol.endswith("/USDT"):
        return symbol.replace("/USDT", "/USD")
    return symbol


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
            return _fetch_from_exchange(ex_id, symbol, timeframe, limit)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Não foi possível baixar dados OHLCV: {last_error}")


def _fetch_from_exchange(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    limit: int,
) -> pd.DataFrame:
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})
    pair = _map_symbol(exchange_id, symbol)

    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - limit * tf_ms

    all_ohlcv: list = []
    while True:
        batch = exchange.fetch_ohlcv(pair, timeframe, since=since, limit=300)
        if not batch:
            break
        all_ohlcv.extend(batch)
        since = batch[-1][0] + tf_ms
        if len(batch) < 300 or len(all_ohlcv) >= limit:
            break
        time.sleep(exchange.rateLimit / 1000)

    all_ohlcv = all_ohlcv[-limit:]

    df = pd.DataFrame(
        all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    df.attrs["exchange"] = exchange_id
    df.attrs["pair"] = pair
    return df


def candles_for_timeframe(timeframe: str) -> int:
    """Candle count per timeframe (balanced history vs. fetch time)."""
    mapping = {
        "5m": 8000,
        "15m": 6000,
        "1h": 4320,
        "4h": 1080,
        "1d": 730,
    }
    return mapping.get(timeframe, 1500)
