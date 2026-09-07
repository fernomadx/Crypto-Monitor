"""Coinbase Exchange public candles provider."""

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

PRODUCT_MAP = {
    "BTC/USDT": "BTC-USDT",
    "ETH/USDT": "ETH-USDT",
    "SOL/USDT": "SOL-USDT",
    "BTC/USD": "BTC-USD",
}

GRANULARITY = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400,
    # 4h/1w aggregated from lower TF
}


class CoinbasePublicProvider(MarketDataProvider):
    name = "coinbase_public"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.exchange.coinbase.com",
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
        if timeframe == "4h":
            hourly = await self.fetch_ohlcv(symbol, "1h", limit=max(limit * 4, 300))
            return self._aggregate_bars(hourly, hours=4, timeframe="4h")[-limit:]
        if timeframe == "1w":
            daily = await self.fetch_ohlcv(symbol, "1d", limit=max(limit * 7, 200))
            return self._aggregate_weekly(daily)[-limit:]

        granularity = GRANULARITY.get(timeframe)
        if granularity is None:
            raise DataUnavailableError(self.name, f"unsupported timeframe {timeframe}")

        # Prefer USD pair on Coinbase (USDT product often missing)
        candidates = []
        mapped = PRODUCT_MAP.get(symbol)
        if mapped:
            candidates.append(mapped)
        if symbol.endswith("/USDT"):
            candidates.append(symbol.replace("/USDT", "-USD"))
            candidates.append(symbol.replace("/", "-"))
        candidates.append(symbol.replace("/", "-"))
        # unique preserve order
        seen: set[str] = set()
        products: list[str] = []
        for product in candidates:
            if product not in seen:
                seen.add(product)
                products.append(product)

        client = await self._get_client()
        collected_at = now_utc()
        last_error: Exception | None = None

        for product in products:
            try:
                started = now_utc()
                response = await client.get(
                    f"/products/{product}/candles",
                    params={"granularity": granularity},
                )
                if response.status_code >= 400:
                    last_error = DataUnavailableError(self.name, f"{product} HTTP {response.status_code}")
                    continue
                rows = response.json()
                latency_ms = (now_utc() - started).total_seconds() * 1000
                if not rows:
                    last_error = DataUnavailableError(self.name, f"empty candles for {product}")
                    continue
                rows = list(reversed(rows))[-limit:]
                candles: list[CandleDTO] = []
                for row in rows:
                    open_time = datetime.fromtimestamp(int(row[0]), tz=UTC)
                    candles.append(
                        CandleDTO(
                            symbol=symbol,
                            timeframe=timeframe,
                            open_time=open_time,
                            open=float(row[3]),
                            high=float(row[2]),
                            low=float(row[1]),
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
                    "coinbase_fetch_failed",
                    product=product,
                    error=str(exc),
                    symbol=symbol,
                    timeframe=timeframe,
                )
        raise DataUnavailableError(self.name, str(last_error))

    def _aggregate_bars(self, candles: list[CandleDTO], hours: int, timeframe: str) -> list[CandleDTO]:
        if not candles:
            return []
        out: list[CandleDTO] = []
        bucket: list[CandleDTO] = []
        for candle in candles:
            hour_bucket = candle.open_time.replace(
                hour=(candle.open_time.hour // hours) * hours,
                minute=0,
                second=0,
                microsecond=0,
            )
            if bucket and bucket[0].open_time.replace(
                hour=(bucket[0].open_time.hour // hours) * hours,
                minute=0,
                second=0,
                microsecond=0,
            ) != hour_bucket:
                out.append(self._reduce_bucket(bucket, timeframe))
                bucket = []
            if not bucket:
                # normalize open_time to bucket start
                candle = candle.model_copy(update={"open_time": hour_bucket, "event_time": hour_bucket})
            bucket.append(candle)
        if bucket:
            out.append(self._reduce_bucket(bucket, timeframe))
        return out

    def _aggregate_weekly(self, daily: list[CandleDTO]) -> list[CandleDTO]:
        if not daily:
            return []
        weeks: list[CandleDTO] = []
        bucket: list[CandleDTO] = []
        current_key: tuple[int, int] | None = None
        for candle in daily:
            key = candle.open_time.isocalendar()[:2]
            if current_key is None:
                current_key = key
            if key != current_key:
                weeks.append(self._reduce_bucket(bucket, "1w"))
                bucket = []
                current_key = key
            bucket.append(candle)
        if bucket:
            weeks.append(self._reduce_bucket(bucket, "1w"))
        return weeks

    @staticmethod
    def _reduce_bucket(bucket: list[CandleDTO], timeframe: str) -> CandleDTO:
        first, last = bucket[0], bucket[-1]
        return CandleDTO(
            symbol=first.symbol,
            timeframe=timeframe,
            open_time=first.open_time,
            open=first.open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=last.close,
            volume=sum(c.volume for c in bucket),
            source=first.source,
            collected_at=last.collected_at,
            event_time=first.open_time,
            latency_ms=last.latency_ms,
            completeness=1.0,
            raw_payload_hash=hash_payload([c.raw_payload_hash for c in bucket]),
        )

    async def health_check(self) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get("/products/BTC-USD/ticker")
            response.raise_for_status()
            return {"name": self.name, "status": "ok", "detail": "ticker ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
