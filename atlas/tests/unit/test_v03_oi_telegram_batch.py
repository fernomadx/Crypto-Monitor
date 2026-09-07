"""v0.3: OI series, Telegram optional, batch evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.evaluation import BatchEvaluationService, DecisionEvaluator
from app.models import Candle, CouncilDecisionRecord, DerivativeObservation, EvaluationRecord
from app.services.derivatives import DerivativesService
from app.services.telegram import TelegramNotifier
from app.specialists.liquidity import LiquidityDerivativesSpecialist
from tests.conftest import make_candles


@pytest.mark.asyncio
async def test_oi_change_from_previous_observation(session: AsyncSession, settings: Settings) -> None:
    now = datetime.now(UTC)
    session.add(
        DerivativeObservation(
            symbol="BTC/USDT",
            source="okx_derivatives",
            instrument="BTC-USDT-SWAP",
            observed_at=now - timedelta(hours=2),
            funding=0.0001,
            open_interest=1_000_000.0,
            open_interest_usd=50_000_000_000.0,
            mark_price=65000.0,
            index_price=64990.0,
            basis_bps=1.5,
            payload={},
        )
    )
    await session.commit()

    fake_snap = {
        "symbol": "BTC/USDT",
        "source": "okx_derivatives",
        "instrument": "BTC-USDT-SWAP",
        "collected_at": now.isoformat(),
        "funding": 0.0002,
        "open_interest": 1_050_000.0,
        "open_interest_usd": 52_000_000_000.0,
        "mark_price": 65100.0,
        "index_price": 65080.0,
        "basis_bps": 3.0,
        "liquidations": [],
        "availability": "AVAILABLE",
        "errors": [],
    }

    service = DerivativesService(session, settings)
    with patch("app.services.derivatives.OkxDerivativesProvider") as provider_cls:
        provider = provider_cls.return_value
        provider.fetch_snapshot = AsyncMock(return_value=fake_snap)
        provider.aclose = AsyncMock()
        enriched = await service.collect_and_enrich("BTC/USDT")

    assert enriched is not None
    assert enriched["oi_change"] == pytest.approx(50_000.0)
    assert enriched["oi_change_pct"] == pytest.approx(0.05)
    assert enriched["previous_oi"] == pytest.approx(1_000_000.0)

    recent = await service.recent("BTC/USDT", limit=10)
    assert len(recent) >= 2


@pytest.mark.asyncio
async def test_liquidity_mentions_oi_change_pct() -> None:
    candles = make_candles(n=40, trend=0.001)
    from app.schemas import MarketSnapshot

    snap = MarketSnapshot(
        symbol="BTC/USDT",
        price=candles[-1].close,
        timestamp=datetime.now(UTC),
        timeframes={"1h": candles},
        data_quality=0.9,
        sources=["test"],
    )
    derivatives = {
        "funding": 0.0001,
        "open_interest": 1.05e6,
        "oi_change": 50_000.0,
        "oi_change_pct": 0.05,
        "oi_change_window_sec": 7200.0,
        "basis_bps": 5.0,
        "liquidations": [],
        "availability": "AVAILABLE",
        "errors": [],
    }
    result = await LiquidityDerivativesSpecialist().analyze(snap, {"derivatives": derivatives})
    assert result.availability == "AVAILABLE"
    texts = " ".join(e.claim for e in result.evidence)
    assert "ΔOI" in texts or "OI↑" in texts


@pytest.mark.asyncio
async def test_telegram_disabled_without_credentials(settings: Settings) -> None:
    s = settings.model_copy(
        update={"telegram_bot_token": "", "telegram_chat_id": "", "telegram_alerts_enabled": True}
    )
    notifier = TelegramNotifier(s)
    assert not notifier.enabled
    out = await notifier.send("hello")
    assert out["status"] == "disabled"


@pytest.mark.asyncio
async def test_batch_eval_waiting_then_evaluates(session: AsyncSession, settings: Settings) -> None:
    now = datetime.now(UTC)
    decision = CouncilDecisionRecord(
        id=uuid4(),
        symbol="BTC/USDT",
        decision="LONG",
        confidence=0.6,
        market_regime="test",
        primary_hypothesis="test hyp",
        data_quality=0.8,
        price=50_000.0,
        payload={
            "supporting_evidence": [{"detail": "x"}],
            "invalidation": ["y"],
            "specialist_votes": [],
        },
        report_markdown="",
        model_version="0.3.0",
        created_at=now - timedelta(hours=3),
    )
    session.add(decision)
    await session.commit()

    # No candles yet → waiting
    waiting = await DecisionEvaluator(session).evaluate_decision(decision.id)
    assert waiting["status"] == "waiting_for_outcome_data"
    await session.refresh(decision)
    assert decision.evaluated_at is None

    # Seed outcome candles
    for i in range(5):
        ts = decision.created_at + timedelta(hours=i + 1)
        session.add(
            Candle(
                symbol="BTC/USDT",
                timeframe="1h",
                open_time=ts,
                open=50_000 + i * 100,
                high=50_100 + i * 100,
                low=49_900 + i * 100,
                close=50_050 + i * 100,
                volume=1000,
                source="test",
                collected_at=now,
                event_time=ts,
                latency_ms=1.0,
                completeness=1.0,
                raw_payload_hash=f"t{i}",
            )
        )
    await session.commit()

    batch = await BatchEvaluationService(session, settings).run(
        limit=10,
        min_age=timedelta(hours=0),
        auto_propose=True,
        min_evaluations_for_propose=20,
    )
    assert batch["n_evaluated"] >= 1
    assert batch["production_weights_unchanged"] is True
    assert batch["weight_proposal"]["status"] == "insufficient_sample"

    await session.refresh(decision)
    assert decision.evaluated_at is not None
    evals = (
        await session.execute(
            select(EvaluationRecord).where(EvaluationRecord.decision_id == decision.id)
        )
    ).scalars().all()
    assert len(evals) == 1


@pytest.mark.asyncio
async def test_evaluation_batch_endpoint(client, session: AsyncSession) -> None:
    response = await client.post("/evaluation/batch?limit=5&min_age_hours=0&auto_propose=false")
    assert response.status_code == 200
    body = response.json()
    assert body["production_weights_unchanged"] is True
    assert "n_evaluated" in body


@pytest.mark.asyncio
async def test_derivatives_recent_endpoint(client) -> None:
    response = await client.get("/derivatives/btc/recent?limit=5")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
