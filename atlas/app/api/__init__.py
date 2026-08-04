"""FastAPI routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.dashboard import DASHBOARD_HTML
from app.collectors.btc import BtcMarketCollector
from app.collectors.providers.fallback import FallbackMarketProvider
from app.config import get_settings
from app.core.exceptions import DataUnavailableError
from app.council.calibration import WeightCalibrator
from app.database import get_session
from app.schemas import (
    AnalysisRunResponse,
    DecisionSummary,
    HealthComponent,
    HealthResponse,
    MarketSnapshot,
)
from app.services.alerts import DecisionAlertService
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


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


@router.get("/alerts")
async def list_alerts(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await DecisionAlertService(session).list_alerts(limit=min(limit, 200))


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(
    alert_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    ok = await DecisionAlertService(session).acknowledge(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="alert not found")
    return {"status": "acknowledged"}


@router.get("/weights")
async def list_weights(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await WeightCalibrator(session).list_versions()


@router.post("/weights/propose")
async def propose_weights(
    min_evaluations: int = 20,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await WeightCalibrator(session).propose(min_evaluations=min_evaluations)


@router.post("/weights/{version_id}/activate")
async def activate_weights(
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await WeightCalibrator(session).activate(version_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="version not found")
    return result


@router.post("/weights/{version_id}/reject")
async def reject_weights(
    version_id: UUID,
    reason: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await WeightCalibrator(session).reject(version_id, reason=reason)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="version not found")
    return result


@router.post("/replay/walkforward/demo")
async def walkforward_demo() -> dict[str, Any]:
    """Deterministic demo of purged walk-forward without look-ahead."""
    from datetime import timedelta

    from app.replay import VirtualClock, WalkForwardConfig, WalkForwardReplay

    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(200):
        ts = start + timedelta(days=i)
        rows.append({"event_time": ts.isoformat(), "close": 40000 + i * 10, "i": i})

    def decision_fn(train, visible, clock: VirtualClock):
        # Only uses revealed data
        last = visible[-1]["close"] if visible else (train[-1]["close"] if train else 0)
        prior = visible[-2]["close"] if len(visible) > 1 else last
        bias = "LONG" if last >= prior else "SHORT"
        return {"decision": bias, "asof": clock.now.isoformat(), "n_visible": len(visible)}

    wf = WalkForwardReplay(
        WalkForwardConfig(
            train_size=timedelta(days=60),
            test_size=timedelta(days=10),
            step_size=timedelta(days=20),
            embargo=timedelta(days=2),
            purge=timedelta(days=1),
        )
    )
    result = wf.run(
        rows,
        start=start,
        end=start + timedelta(days=180),
        decision_fn=decision_fn,
        step=timedelta(days=2),
    )
    return {
        "n_folds": len(result.splits),
        "notes": result.notes,
        "folds": [
            {
                "fold": f["fold"],
                "embargo": f["embargo"],
                "n_train": f["n_train"],
                "n_decisions": f["n_decisions"],
                "first_decision": f["decisions"][0] if f["decisions"] else None,
            }
            for f in result.fold_results
        ],
    }
