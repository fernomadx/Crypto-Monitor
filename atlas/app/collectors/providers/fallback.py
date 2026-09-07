"""Fallback market data provider — tries providers in order."""

from __future__ import annotations

from typing import Any

from app.collectors.providers.base import MarketDataProvider
from app.collectors.providers.binance import BinancePublicProvider
from app.collectors.providers.bybit import BybitPublicProvider
from app.collectors.providers.coinbase import CoinbasePublicProvider
from app.collectors.providers.okx import OkxPublicProvider
from app.config import Settings, get_settings
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger
from app.schemas import CandleDTO

logger = get_logger(__name__)


class FallbackMarketProvider(MarketDataProvider):
    name = "fallback_market"

    def __init__(
        self,
        settings: Settings | None = None,
        providers: list[MarketDataProvider] | None = None,
    ):
        self.settings = settings or get_settings()
        self.providers = providers or [
            OkxPublicProvider(self.settings),
            CoinbasePublicProvider(self.settings),
            BinancePublicProvider(self.settings),
            BybitPublicProvider(self.settings),
        ]
        self.last_provider: str | None = None

    async def aclose(self) -> None:
        for provider in self.providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[CandleDTO]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                candles = await provider.fetch_ohlcv(symbol, timeframe, limit=limit)
                self.last_provider = provider.name
                self.name = provider.name
                logger.info(
                    "fallback_provider_used",
                    provider=provider.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=len(candles),
                )
                return candles
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider.name}: {exc}")
                logger.warning("fallback_provider_failed", provider=provider.name, error=str(exc))
        raise DataUnavailableError(self.name, "; ".join(errors))

    async def health_check(self) -> dict[str, Any]:
        details: list[dict[str, Any]] = []
        any_ok = False
        for provider in self.providers:
            result = await provider.health_check()
            details.append(result)
            if result.get("status") == "ok":
                any_ok = True
        return {
            "name": self.name,
            "status": "ok" if any_ok else "error",
            "detail": details,
        }
