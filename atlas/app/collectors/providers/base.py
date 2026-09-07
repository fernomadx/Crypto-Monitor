"""Market data provider abstractions."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.schemas import CandleDTO


def hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class MarketDataProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[CandleDTO]:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError


class MacroDataProvider(ABC):
    name: str = "macro_base"

    @abstractmethod
    async def fetch_series(
        self,
        series_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError


def now_utc() -> datetime:
    return datetime.now(UTC)
