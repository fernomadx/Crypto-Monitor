"""Integration tests — health, persistence, analysis pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.collectors.btc import BtcMarketCollector
from app.core.enums import SpecialistName
from app.models import Candle, CouncilDecisionRecord
from app.schemas import MarketSnapshot
from app.services.analysis import AnalysisService
from tests.conftest import make_candles


@pytest.mark.asyncio
async def test_health_endpoint(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "components" in body
    assert body["version"]


@pytest.mark.asyncio
async def test_version_endpoint(client) -> None:
    response = await client.get("/version")
    assert response.status_code == 200
    assert response.json()["name"] == "ATLAS"


@pytest.mark.asyncio
async def test_ready_endpoint(client) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_persist_candles_dedupe(session) -> None:
    candles = make_candles(n=40)
    collector = BtcMarketCollector(session)

    async def fake_fetch(symbol: str, timeframe: str, limit: int = 200):
        return [c.model_copy(update={"timeframe": timeframe}) for c in candles]

    collector.provider.fetch_ohlcv = fake_fetch  # type: ignore[method-assign]
    collector.provider.name = "binance_public"
    snap = await collector.collect(timeframes=["1h"], limit=40)
    assert snap.price > 0

    # second collect should not duplicate
    await collector.collect(timeframes=["1h"], limit=40)
    result = await session.execute(select(Candle))
    rows = result.scalars().all()
    assert len(rows) == 40


@pytest.mark.asyncio
async def test_analysis_pipeline_persists_decision(session) -> None:
    candles = {
        "5m": make_candles(80, timeframe="5m"),
        "15m": make_candles(80, timeframe="15m"),
        "1h": make_candles(100, timeframe="1h"),
        "4h": make_candles(80, timeframe="4h"),
        "1d": make_candles(80, timeframe="1d"),
        "1w": make_candles(60, timeframe="1w"),
    }
    snapshot = MarketSnapshot(
        symbol="BTC/USDT",
        price=candles["1h"][-1].close,
        timestamp=datetime.now(UTC),
        timeframes=candles,
        data_quality=0.85,
        sources=["test"],
    )

    service = AnalysisService(session)

    async def fake_collect(timeframes=None, limit=200):
        return snapshot

    service.collector.collect = fake_collect  # type: ignore[method-assign]
    service.collector.latest_snapshot = AsyncMock(return_value=snapshot)

    with patch("app.services.analysis.load_macro_context", AsyncMock(return_value={})):
        # Avoid live news HTTP in integration
        for s in service.specialists:
            if s.name == SpecialistName.NEWS_EVENTS:
                s.collect_headlines = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        result = await service.run_btc_analysis(collect=True)

    assert result.decision_id is not None
    assert result.decision.decision.value in {"LONG", "SHORT", "NO_TRADE"}
    assert "ATLAS BTC ANALYSIS" in result.report_markdown

    db = await session.execute(select(CouncilDecisionRecord))
    assert db.scalar_one_or_none() is not None

    listed = await service.list_decisions()
    assert len(listed) >= 1


@pytest.mark.asyncio
async def test_specialists_status(client) -> None:
    response = await client.get("/specialists/status")
    assert response.status_code == 200
    names = {s["name"] for s in response.json()}
    assert "market_structure" in names
    assert "risk" in names
