"""Binance public REST OHLCV provider."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.collectors.providers.base import MarketDataProvider, hash_payload, now_utc
from app.config import Settings, get_settings
from app.core.enums import BINANCE_INTERVAL_MAP
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger
from app.schemas import CandleDTO

logger = get_logger(__name__)

SYMBOL_MAP = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "SOL/USDT": "SOLUSDT",
}


class BinancePublicProvider(MarketDataProvider):
    name = "binance_public"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.binance_base_url,
                timeout=self.settings.http_timeout_sec,
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _map_symbol(self, symbol: str) -> str:
        return SYMBOL_MAP.get(symbol, symbol.replace("/", ""))

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[CandleDTO]:
        interval = BINANCE_INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise DataUnavailableError(self.name, f"unsupported timeframe {timeframe}")

        client = await self._get_client()
        params: dict[str, str | int] = {
            "symbol": self._map_symbol(symbol),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        collected_at = now_utc()
        last_error: Exception | None = None

        for attempt in range(1, self.settings.http_retries + 1):
            try:
                started = now_utc()
                response = await client.get("/api/v3/klines", params=params)
                if response.status_code in {403, 418, 451}:
                    raise DataUnavailableError(self.name, f"HTTP {response.status_code} geo/ban")
                response.raise_for_status()
                payload = response.json()
                latency_ms = (now_utc() - started).total_seconds() * 1000
                return self._parse_klines(
                    payload=payload,
                    symbol=symbol,
                    timeframe=timeframe,
                    collected_at=collected_at,
                    latency_ms=latency_ms,
                )
            except DataUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "binance_fetch_retry",
                    attempt=attempt,
                    error=str(exc),
                    symbol=symbol,
                    timeframe=timeframe,
                )

        raise DataUnavailableError(self.name, str(last_error))

    def _parse_klines(
        self,
        payload: list[list[Any]],
        symbol: str,
        timeframe: str,
        collected_at: datetime,
        latency_ms: float,
    ) -> list[CandleDTO]:
        if not payload:
            raise DataUnavailableError(self.name, "empty klines")

        candles: list[CandleDTO] = []
        for row in payload:
            open_time = datetime.fromtimestamp(row[0] / 1000, tz=UTC)
            candles.append(
                CandleDTO(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=open_time,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    source=self.name,
                    collected_at=collected_at,
                    event_time=open_time,
                    latency_ms=latency_ms,
                    completeness=1.0,
                    raw_payload_hash=hash_payload(row),
                )
            )
        return candles

    async def health_check(self) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get("/api/v3/ping")
            response.raise_for_status()
            return {"name": self.name, "status": "ok", "detail": "ping ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
