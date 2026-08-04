"""FastAPI routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.collectors.btc import BtcMarketCollector
from app.collectors.providers.fallback import FallbackMarketProvider
from app.config import get_settings
from app.core.exceptions import DataUnavailableError
from app.database import get_session
from app.schemas import (
    AnalysisRunResponse,
    DecisionSummary,
    HealthComponent,
    HealthResponse,
    MarketSnapshot,
)
from app.services.analysis import AnalysisService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    from sqlalchemy import text

    settings = get_settings()
    components: list[HealthComponent] = [
        HealthComponent(name="application", status="ok", detail="running"),
    ]

    # Database
    try:
        await session.execute(text("SELECT 1"))
        components.append(HealthComponent(name="database", status="ok"))
    except Exception as exc:  # noqa: BLE001
        components.append(HealthComponent(name="database", status="error", detail=str(exc)))

    # Essential collectors (with fallback)
    provider = FallbackMarketProvider(settings)
    try:
        ping = await provider.health_check()
        detail = ping.get("detail", "")
        detail_str = detail if isinstance(detail, str) else str(detail)
        components.append(
            HealthComponent(
                name="collector_market",
                status=str(ping.get("status", "error")),
                detail=detail_str[:500],
            )
        )
    finally:
        await provider.aclose()

    collector = BtcMarketCollector(session, settings=settings)
    status = await collector.collection_status()
    lag_detail = ""
    collect_status = status.get("status", "unknown")
    if status.get("last_success_at"):
        last = datetime.fromisoformat(status["last_success_at"])
        lag = (datetime.now(UTC) - last).total_seconds()
        lag_detail = f"lag_sec={lag:.0f}"
        if lag > settings.max_data_lag_sec:
            collect_status = "stale"
    components.append(
        HealthComponent(
            name="last_collection",
            status=collect_status,
            detail=lag_detail or status.get("last_error") or "",
        )
    )

    # Redis not used in v0.1 — omit intentionally
    overall = "ok"
    if any(c.status == "error" for c in components if c.name in {"application", "database", "collector_market"}):
        overall = "error"
    elif any(c.status == "stale" for c in components):
        overall = "degraded"
    return HealthResponse(status=overall, version=settings.version, components=components)


@router.get("/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    from sqlalchemy import text

    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"not ready: {exc}") from exc


@router.get("/version")
async def version() -> dict[str, str]:
    settings = get_settings()
    return {"name": settings.app_name, "version": settings.version, "package": __version__}


@router.get("/market/btc/snapshot", response_model=MarketSnapshot)
async def btc_snapshot(
    refresh: bool = False,
    session: AsyncSession = Depends(get_session),
) -> MarketSnapshot:
    collector = BtcMarketCollector(session)
    try:
        if refresh:
            return await collector.collect()
        snap = await collector.latest_snapshot()
        if snap is None:
            return await collector.collect()
        return snap
    except DataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/analysis/btc/latest", response_model=AnalysisRunResponse)
async def analysis_latest(session: AsyncSession = Depends(get_session)) -> AnalysisRunResponse:
    service = AnalysisService(session)
    latest = await service.latest_decision()
    if latest is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    return latest


@router.post("/analysis/btc/run", response_model=AnalysisRunResponse)
async def analysis_run(
    collect: bool = True,
    session: AsyncSession = Depends(get_session),
) -> AnalysisRunResponse:
    service = AnalysisService(session)
    try:
        return await service.run_btc_analysis(collect=collect)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/specialists/status")
async def specialists_status(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    service = AnalysisService(session)
    return service.specialists_status()


@router.get("/decisions", response_model=list[DecisionSummary])
async def list_decisions(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list[DecisionSummary]:
    service = AnalysisService(session)
    return await service.list_decisions(limit=min(limit, 100))


@router.get("/decisions/{decision_id}", response_model=AnalysisRunResponse)
async def get_decision(
    decision_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AnalysisRunResponse:
    service = AnalysisService(session)
    row = await service.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return row
