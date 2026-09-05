"""OKX public derivatives data (funding, OI, basis, liquidations)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.collectors.providers.base import now_utc
from app.config import Settings, get_settings
from app.core.exceptions import DataUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

SWAP_MAP = {
    "BTC/USDT": "BTC-USDT-SWAP",
    "ETH/USDT": "ETH-USDT-SWAP",
    "SOL/USDT": "SOL-USDT-SWAP",
}

SPOT_INDEX_MAP = {
    "BTC/USDT": "BTC-USDT",
    "ETH/USDT": "ETH-USDT",
    "SOL/USDT": "SOL-USDT",
}


class OkxDerivativesProvider:
    name = "okx_derivatives"

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

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        body = response.json()
        if body.get("code") not in (None, "0"):
            raise DataUnavailableError(self.name, str(body.get("msg") or body))
        return body

    async def fetch_snapshot(self, symbol: str = "BTC/USDT") -> dict[str, Any]:
        swap = SWAP_MAP.get(symbol, symbol.replace("/", "-") + "-SWAP")
        index_id = SPOT_INDEX_MAP.get(symbol, symbol.replace("/", "-"))
        collected_at = now_utc()
        errors: list[str] = []

        funding = None
        funding_hist: list[dict[str, Any]] = []
        open_interest = None
        oi_usd = None
        mark_price = None
        index_price = None
        liquidations: list[dict[str, Any]] = []

        try:
            body = await self._get_json("/api/v5/public/funding-rate", {"instId": swap})
            row = (body.get("data") or [{}])[0]
            funding = float(row.get("fundingRate") or 0.0)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"funding:{exc}")

        try:
            body = await self._get_json(
                "/api/v5/public/funding-rate-history",
                {"instId": swap, "limit": "20"},
            )
            for row in reversed(body.get("data") or []):
                funding_hist.append(
                    {
                        "funding_rate": float(row.get("fundingRate") or 0.0),
                        "funding_time": datetime.fromtimestamp(
                            int(row["fundingTime"]) / 1000, tz=UTC
                        ).isoformat(),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"funding_hist:{exc}")

        try:
            body = await self._get_json("/api/v5/public/open-interest", {"instId": swap})
            row = (body.get("data") or [{}])[0]
            open_interest = float(row.get("oi") or 0.0)
            oi_usd = float(row.get("oiUsd") or 0.0)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"oi:{exc}")

        try:
            body = await self._get_json("/api/v5/public/mark-price", {"instId": swap})
            row = (body.get("data") or [{}])[0]
            mark_price = float(row.get("markPx") or 0.0)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mark:{exc}")

        try:
            body = await self._get_json("/api/v5/market/index-tickers", {"instId": index_id})
            row = (body.get("data") or [{}])[0]
            index_price = float(row.get("idxPx") or 0.0)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"index:{exc}")

        try:
            uly = index_id
            body = await self._get_json(
                "/api/v5/public/liquidation-orders",
                {"instType": "SWAP", "uly": uly, "state": "filled", "limit": "20"},
            )
            for block in body.get("data") or []:
                for detail in block.get("details") or []:
                    liquidations.append(
                        {
                            "side": detail.get("side"),
                            "pos_side": detail.get("posSide"),
                            "size": float(detail.get("sz") or 0.0),
                            "price": float(detail.get("bkPx") or 0.0),
                            "time": datetime.fromtimestamp(
                                int(detail.get("ts") or detail.get("time")) / 1000, tz=UTC
                            ).isoformat(),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"liquidations:{exc}")

        if funding is None and open_interest is None:
            raise DataUnavailableError(self.name, "; ".join(errors) or "no derivatives data")

        basis = None
        basis_bps = None
        if mark_price and index_price and index_price > 0:
            basis = mark_price - index_price
            basis_bps = (basis / index_price) * 10000

        oi_change = None
        # Without historical OI store, approximate change unavailable → explicit null
        funding_mean = (
            sum(x["funding_rate"] for x in funding_hist) / len(funding_hist) if funding_hist else None
        )

        return {
            "source": self.name,
            "symbol": symbol,
            "instrument": swap,
            "collected_at": collected_at.isoformat(),
            "funding": funding,
            "funding_mean_hist": funding_mean,
            "funding_history": funding_hist[-10:],
            "open_interest": open_interest,
            "open_interest_usd": oi_usd,
            "oi_change": oi_change,
            "mark_price": mark_price,
            "index_price": index_price,
            "basis": basis,
            "basis_bps": basis_bps,
            "liquidations": liquidations[:20],
            "liquidation_count": len(liquidations),
            "errors": errors,
            "availability": "AVAILABLE" if not errors else "PARTIAL",
        }

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.fetch_snapshot("BTC/USDT")
            return {"name": self.name, "status": "ok", "detail": "funding/oi ok"}
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "status": "error", "detail": str(exc)}
