"""Stooq public daily series provider (macro / equities)."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from typing import Any

import httpx
import polars as pl

from app.collectors.providers.base import MacroDataProvider, now_utc
from app.config import Settings, get_settings
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Stooq symbols — public CSV endpoints
STOOQ_SYMBOLS: dict[str, str] = {
    "NDX": "^ndx",  # Nasdaq 100
    "SPX": "^spx",  # S&P 500
    "DXY": "dx.f",  # Dollar index futures proxy
    "VIX": "^vix",
    "WTI": "cl.f",
    "BRENT": "brn.f",
    "GOLD": "gc.f",
    "SILVER": "si.f",
    "NVDA": "nvda.us",
    "COIN": "coin.us",
    "MSTR": "mstr.us",
    "ETH_USD": "ethusd",
    "SOL_USD": "solusd",
}


class StooqProvider(MacroDataProvider):
    name = "stooq_public"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.http_timeout_sec)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_series(self, series_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if not self.settings.stooq_enabled:
            raise DataUnavailableError(self.name, "disabled")

        symbol = STOOQ_SYMBOLS.get(series_id.upper(), series_id.lower())
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text.strip()
            if not text or "Date" not in text.splitlines()[0]:
                raise DataUnavailableError(self.name, f"invalid csv for {series_id}")
            frame = pl.read_csv(StringIO(text))
            if frame.is_empty():
                raise DataUnavailableError(self.name, f"empty series {series_id}")
            frame = frame.tail(limit)
            collected_at = now_utc()
            rows: list[dict[str, Any]] = []
            for row in frame.to_dicts():
                date_raw = row.get("Date")
                close = row.get("Close")
                if date_raw is None or close is None:
                    continue
                event_time = datetime.strptime(str(date_raw), "%Y-%m-%d").replace(tzinfo=UTC)
                rows.append(
                    {
                        "series_id": series_id.upper(),
                        "event_time": event_time.isoformat(),
                        "open": float(row.get("Open") or close),
                        "high": float(row.get("High") or close),
                        "low": float(row.get("Low") or close),
                        "close": float(close),
                        "volume": float(row.get("Volume") or 0.0),
                        "source": self.name,
                        "collected_at": collected_at.isoformat(),
                    }
                )
            if not rows:
                raise DataUnavailableError(self.name, f"no parseable rows for {series_id}")
            return rows
        except DataUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("stooq_fetch_failed", series=series_id, error=str(exc))
            raise DataUnavailableError(self.name, str(exc)) from exc

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.fetch_series("SPX", limit=5)
            return {"name": self.name, "status": "ok", "detail": "sample fetch ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
