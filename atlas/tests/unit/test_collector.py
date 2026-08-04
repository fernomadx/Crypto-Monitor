"""Collector unit tests with mocked HTTP."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.collectors.providers.binance import BinancePublicProvider
from app.config import Settings
from app.core.exceptions import DataUnavailableError


def _kline_row(ts_ms: int, price: float) -> list:
    return [
        ts_ms,
        str(price),
        str(price * 1.01),
        str(price * 0.99),
        str(price * 1.005),
        "12.5",
        ts_ms + 3600000,
        "100",
        10,
        "5",
        "50",
        "0",
    ]


@pytest.mark.asyncio
async def test_binance_provider_parses_klines() -> None:
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    payload = [_kline_row(now_ms - i * 3600000, 60000 + i) for i in range(50)][::-1]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v3/klines" in str(request.url)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.binance.com") as client:
        provider = BinancePublicProvider(Settings(env="test"), client=client)
        candles = await provider.fetch_ohlcv("BTC/USDT", "1h", limit=50)
        assert len(candles) == 50
        assert candles[0].symbol == "BTC/USDT"
        assert candles[0].source == "binance_public"
        assert candles[0].raw_payload_hash


@pytest.mark.asyncio
async def test_binance_provider_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.binance.com") as client:
        provider = BinancePublicProvider(
            Settings(env="test", http_retries=2),
            client=client,
        )
        with pytest.raises(DataUnavailableError):
            await provider.fetch_ohlcv("BTC/USDT", "1h")
