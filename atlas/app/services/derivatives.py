"""Persist derivatives snapshots and compute oi_change from history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.providers.okx_derivatives import OkxDerivativesProvider
from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.models import DerivativeObservation
from app.utils.jsonable import to_jsonable

logger = get_logger(__name__)


class DerivativesService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()

    async def collect_and_enrich(self, symbol: str) -> dict[str, Any] | None:
        provider = OkxDerivativesProvider(self.settings)
        try:
            snap = await provider.fetch_snapshot(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("derivatives_collect_failed", error=str(exc))
            return None
        finally:
            await provider.aclose()

        observed_at = datetime.fromisoformat(snap["collected_at"])
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)

        prev = await self._previous_observation(symbol, before=observed_at)
        oi_change = None
        oi_change_pct = None
        oi_change_window_sec = None
        if prev is not None and snap.get("open_interest") is not None and prev.open_interest is not None:
            oi_change = float(snap["open_interest"]) - float(prev.open_interest)
            if prev.open_interest != 0:
                oi_change_pct = oi_change / float(prev.open_interest)
            oi_change_window_sec = (observed_at - prev.observed_at).total_seconds()

        snap["oi_change"] = oi_change
        snap["oi_change_pct"] = oi_change_pct
        snap["oi_change_window_sec"] = oi_change_window_sec
        snap["previous_oi"] = prev.open_interest if prev else None
        snap["previous_observed_at"] = prev.observed_at.isoformat() if prev else None

        await self._persist(snap, observed_at)
        await self.session.commit()
        return to_jsonable(snap)

    async def _previous_observation(
        self,
        symbol: str,
        *,
        before: datetime,
        max_age: timedelta = timedelta(days=7),
    ) -> DerivativeObservation | None:
        result = await self.session.execute(
            select(DerivativeObservation)
            .where(
                DerivativeObservation.symbol == symbol,
                DerivativeObservation.observed_at < before,
                DerivativeObservation.observed_at >= before - max_age,
                DerivativeObservation.open_interest.is_not(None),
            )
            .order_by(DerivativeObservation.observed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _persist(self, snap: dict[str, Any], observed_at: datetime) -> DerivativeObservation:
        row = DerivativeObservation(
            symbol=snap["symbol"],
            source=snap.get("source", "okx_derivatives"),
            instrument=snap.get("instrument", ""),
            observed_at=observed_at,
            funding=snap.get("funding"),
            open_interest=snap.get("open_interest"),
            open_interest_usd=snap.get("open_interest_usd"),
            mark_price=snap.get("mark_price"),
            index_price=snap.get("index_price"),
            basis_bps=snap.get("basis_bps"),
            payload=to_jsonable(snap),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(DerivativeObservation)
            .where(DerivativeObservation.symbol == symbol)
            .order_by(DerivativeObservation.observed_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "observed_at": r.observed_at.isoformat(),
                "funding": r.funding,
                "open_interest": r.open_interest,
                "open_interest_usd": r.open_interest_usd,
                "basis_bps": r.basis_bps,
                "source": r.source,
            }
            for r in rows
        ]
