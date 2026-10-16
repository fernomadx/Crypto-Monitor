"""OKX public candles provider."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.collectors.providers.base import MarketDataProvider, hash_payload, now_utc
from app.config import Settings, get_settings
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger
from app.schemas import CandleDTO

logger = get_logger(__name__)

INST_MAP = {
    "BTC/USDT": "BTC-USDT",
    "ETH/USDT": "ETH-USDT",
    "SOL/USDT": "SOL-USDT",
}

BAR_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
    "1w": "1W",
}


class OkxPublicProvider(MarketDataProvider):
    name = "okx_public"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://www.okx.com",
                timeout=self.settings.http_timeout_sec,
                headers={"User-Agent": "atlas/0.1"},
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
        bar = BAR_MAP.get(timeframe)
        if bar is None:
            raise DataUnavailableError(self.name, f"unsupported timeframe {timeframe}")
        inst = INST_MAP.get(symbol, symbol.replace("/", "-"))
        client = await self._get_client()
        collected_at = now_utc()
        last_error: Exception | None = None
        for attempt in range(1, self.settings.http_retries + 1):
            try:
                started = now_utc()
                response = await client.get(
                    "/api/v5/market/candles",
                    params={"instId": inst, "bar": bar, "limit": str(min(limit, 300))},
                )
                response.raise_for_status()
                body = response.json()
                if body.get("code") != "0":
                    raise DataUnavailableError(self.name, str(body.get("msg")))
                rows = body.get("data") or []
                latency_ms = (now_utc() - started).total_seconds() * 1000
                if not rows:
                    raise DataUnavailableError(self.name, "empty candles")
                # OKX newest first: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                rows = list(reversed(rows))
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
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "okx_fetch_retry",
                    attempt=attempt,
                    error=str(exc),
                    symbol=symbol,
                    timeframe=timeframe,
                )
        raise DataUnavailableError(self.name, str(last_error))

    async def health_check(self) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get("/api/v5/public/time")
            response.raise_for_status()
            return {"name": self.name, "status": "ok", "detail": "time ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
