"""FRED macro provider — requires ATLAS_FRED_API_KEY."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.collectors.providers.base import MacroDataProvider, now_utc
from app.config import Settings, get_settings
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

FRED_SERIES: dict[str, str] = {
    "DXY": "DTWEXBGS",
    "VIX": "VIXCLS",
    "US2Y": "DGS2",
    "US10Y": "DGS10",
    "WTI": "DCOILWTICO",
    "BRENT": "DCOILBRENTEU",
    "GOLD": "GOLDAMGBD228NLBM",
}


class FredProvider(MacroDataProvider):
    name = "fred"

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
        if not self.settings.fred_api_key:
            raise DataUnavailableError(self.name, "ATLAS_FRED_API_KEY not configured")

        fred_id = FRED_SERIES.get(series_id.upper(), series_id)
        client = await self._get_client()
        params: dict[str, str | int] = {
            "series_id": fred_id,
            "api_key": self.settings.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        try:
            response = await client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params=params,
            )
            response.raise_for_status()
            observations = response.json().get("observations", [])
            collected_at = now_utc()
            rows: list[dict[str, Any]] = []
            for obs in reversed(observations):
                value = obs.get("value")
                if value in (None, "."):
                    continue
                event_time = datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=UTC)
                close = float(value)
                rows.append(
                    {
                        "series_id": series_id.upper(),
                        "event_time": event_time.isoformat(),
                        "close": close,
                        "source": self.name,
                        "collected_at": collected_at.isoformat(),
                    }
                )
            if not rows:
                raise DataUnavailableError(self.name, f"empty observations for {series_id}")
            return rows
        except DataUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("fred_fetch_failed", series=series_id, error=str(exc))
            raise DataUnavailableError(self.name, str(exc)) from exc

    async def health_check(self) -> dict[str, Any]:
        if not self.settings.fred_api_key:
            return {
                "name": self.name,
                "status": "DATA_UNAVAILABLE",
                "detail": "ATLAS_FRED_API_KEY not configured",
            }
        try:
            await self.fetch_series("VIX", limit=5)
            return {"name": self.name, "status": "ok", "detail": "sample fetch ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
