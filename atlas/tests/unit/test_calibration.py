"""Weight calibrator unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.council.calibration import WeightCalibrator
from app.models import CouncilDecisionRecord, EvaluationRecord


@pytest.mark.asyncio
async def test_propose_insufficient_sample(session) -> None:
    cal = WeightCalibrator(session)
    out = await cal.propose(min_evaluations=20)
    assert out["status"] == "insufficient_sample"


@pytest.mark.asyncio
async def test_propose_and_activate(session) -> None:
    for i in range(25):
        dec = CouncilDecisionRecord(
            id=uuid4(),
            symbol="BTC/USDT",
            decision="LONG" if i % 2 == 0 else "NO_TRADE",
            confidence=0.6,
            market_regime="test",
            primary_hypothesis="h",
            data_quality=0.8,
            price=60000.0,
            payload={
                "specialist_votes": [
                    {"specialist": "market_structure", "bias": "LONG"},
                    {"specialist": "macro_cross_asset", "bias": "LONG"},
                    {"specialist": "risk", "bias": "NEUTRAL"},
                ]
            },
            report_markdown="",
            model_version="0.2.0",
            created_at=datetime.now(UTC),
        )
        session.add(dec)
        await session.flush()
        session.add(
            EvaluationRecord(
                decision_id=dec.id,
                result_quality=0.7 if i % 2 == 0 else 0.4,
                reasoning_quality=0.6,
                data_quality=0.8,
                classification="acerto_parcial",
                notes="test",
                payload={},
            )
        )
    await session.commit()

    cal = WeightCalibrator(session)
    proposed = await cal.propose(min_evaluations=20)
    assert proposed["status"] == "proposed"
    assert proposed["production_unchanged"] is True
    assert "market_structure" in proposed["weights"]

    activated = await cal.activate(UUID(str(proposed["id"])))
    assert activated["status"] == "activated"
    weights = await cal.get_active_weights()
    assert weights["market_structure"] > 0
