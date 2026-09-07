"""Bybit public REST OHLCV provider (spot)."""

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

# Bybit interval codes for spot kline
INTERVAL_MAP = {
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    "1w": "W",
}


class BybitPublicProvider(MarketDataProvider):
    name = "bybit_public"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.bybit.com",
                timeout=self.settings.http_timeout_sec,
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[CandleDTO]:
        if timeframe not in INTERVAL_MAP and timeframe not in BINANCE_INTERVAL_MAP:
            raise DataUnavailableError(self.name, f"unsupported timeframe {timeframe}")
        interval = INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise DataUnavailableError(self.name, f"unsupported timeframe {timeframe}")

        client = await self._get_client()
        params: dict[str, str | int] = {
            "category": "spot",
            "symbol": SYMBOL_MAP.get(symbol, symbol.replace("/", "")),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        collected_at = now_utc()
        last_error: Exception | None = None
        for attempt in range(1, self.settings.http_retries + 1):
            try:
                started = now_utc()
                response = await client.get("/v5/market/kline", params=params)
                if response.status_code in {403, 451}:
                    raise DataUnavailableError(self.name, f"HTTP {response.status_code} geo/ban")
                response.raise_for_status()
                body = response.json()
                if body.get("retCode") != 0:
                    raise DataUnavailableError(self.name, str(body.get("retMsg")))
                rows = body.get("result", {}).get("list", [])
                # Bybit returns newest first
                rows = list(reversed(rows))
                latency_ms = (now_utc() - started).total_seconds() * 1000
                if not rows:
                    raise DataUnavailableError(self.name, "empty klines")
                candles: list[CandleDTO] = []
                for row in rows:
                    open_time = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
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
            except DataUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "bybit_fetch_retry",
                    attempt=attempt,
                    error=str(exc),
                    symbol=symbol,
                    timeframe=timeframe,
                )
        raise DataUnavailableError(self.name, str(last_error))

    async def health_check(self) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get("/v5/market/time")
            response.raise_for_status()
            return {"name": self.name, "status": "ok", "detail": "time ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
