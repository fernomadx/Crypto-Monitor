"""Yahoo Finance public chart API — macro fallback (not sole production source)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.collectors.providers.base import MacroDataProvider, now_utc
from app.config import Settings, get_settings
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

YAHOO_SYMBOLS: dict[str, str] = {
    "NDX": "^NDX",
    "SPX": "^GSPC",
    "DXY": "DX-Y.NYB",
    "VIX": "^VIX",
    "WTI": "CL=F",
    "BRENT": "BZ=F",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "NVDA": "NVDA",
    "COIN": "COIN",
    "MSTR": "MSTR",
    "ETH_USD": "ETH-USD",
    "SOL_USD": "SOL-USD",
    "US2Y": "^IRX",  # proxy — 13-week bill; not perfect 2Y
    "US10Y": "^TNX",
}


class YahooMacroProvider(MacroDataProvider):
    name = "yahoo_public"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.http_timeout_sec,
                headers={"User-Agent": "atlas/0.1"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_series(self, series_id: str, limit: int = 200) -> list[dict[str, Any]]:
        symbol = YAHOO_SYMBOLS.get(series_id.upper(), series_id)
        client = await self._get_client()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params: dict[str, str] = {"interval": "1d", "range": "1y"}
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            result = response.json().get("chart", {}).get("result")
            if not result:
                raise DataUnavailableError(self.name, f"empty chart for {series_id}")
            chart = result[0]
            timestamps = chart.get("timestamp") or []
            quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
            closes = quote.get("close") or []
            opens = quote.get("open") or closes
            highs = quote.get("high") or closes
            lows = quote.get("low") or closes
            volumes = quote.get("volume") or [0] * len(closes)
            collected_at = now_utc()
            rows: list[dict[str, Any]] = []
            for ts, o, h, low, c, v in zip(timestamps, opens, highs, lows, closes, volumes, strict=False):
                if c is None:
                    continue
                event_time = datetime.fromtimestamp(int(ts), tz=UTC)
                rows.append(
                    {
                        "series_id": series_id.upper(),
                        "event_time": event_time.isoformat(),
                        "open": float(o if o is not None else c),
                        "high": float(h if h is not None else c),
                        "low": float(low if low is not None else c),
                        "close": float(c),
                        "volume": float(v or 0.0),
                        "source": self.name,
                        "collected_at": collected_at.isoformat(),
                    }
                )
            rows = rows[-limit:]
            if not rows:
                raise DataUnavailableError(self.name, f"no parseable rows for {series_id}")
            return rows
        except DataUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("yahoo_fetch_failed", series=series_id, error=str(exc))
            raise DataUnavailableError(self.name, str(exc)) from exc

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.fetch_series("SPX", limit=5)
            return {"name": self.name, "status": "ok", "detail": "sample fetch ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
