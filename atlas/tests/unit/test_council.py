"""Council aggregator tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import Bias, Decision, SpecialistName
from app.council import CouncilAggregator
from app.schemas import EvidenceItem, SpecialistAssessment


def _a(
    name: SpecialistName,
    bias: Bias,
    confidence: float,
    data_quality: float = 0.9,
    availability: str = "AVAILABLE",
    invalidation: list[str] | None = None,
    risks: list[str] | None = None,
    metrics: dict | None = None,
) -> SpecialistAssessment:
    return SpecialistAssessment(
        specialist=name,
        timestamp=datetime.now(UTC),
        symbol="BTC/USDT",
        timeframe="1h",
        bias=bias,
        confidence=confidence,
        data_quality=data_quality,
        evidence=[EvidenceItem(claim=f"{name.value} says {bias.value}", weight=0.7)],
        risks=risks or [],
        invalidation_conditions=invalidation or ["inv"],
        alternative_hypotheses=[],
        metrics=metrics or {},
        availability=availability,
    )


def test_council_no_trade_on_conflict() -> None:
    council = CouncilAggregator()
    decision = council.aggregate(
        [
            _a(SpecialistName.MARKET_STRUCTURE, Bias.LONG, 0.7),
            _a(SpecialistName.MACRO_CROSS_ASSET, Bias.SHORT, 0.7),
            _a(SpecialistName.DYNAMIC_CORRELATION, Bias.LONG, 0.4),
            _a(SpecialistName.NEWS_EVENTS, Bias.SHORT, 0.4),
        ],
        price=100.0,
    )
    assert decision.decision == Decision.NO_TRADE


def test_council_no_trade_when_risk_vetoes() -> None:
    council = CouncilAggregator()
    decision = council.aggregate(
        [
            _a(SpecialistName.MARKET_STRUCTURE, Bias.LONG, 0.8),
            _a(SpecialistName.RISK, Bias.NO_TRADE, 0.7, risks=["RR ruim"]),
        ],
        price=100.0,
    )
    assert decision.decision == Decision.NO_TRADE
    assert "Risk" in decision.primary_hypothesis or "NO_TRADE" in decision.primary_hypothesis


def test_council_long_when_aligned() -> None:
    council = CouncilAggregator()
    decision = council.aggregate(
        [
            _a(SpecialistName.MARKET_STRUCTURE, Bias.LONG, 0.8, invalidation=["stop below X"]),
            _a(SpecialistName.MACRO_CROSS_ASSET, Bias.LONG, 0.7, invalidation=["macro break"]),
            _a(SpecialistName.DYNAMIC_CORRELATION, Bias.LONG, 0.6),
            _a(
                SpecialistName.RISK,
                Bias.NEUTRAL,
                0.4,
                metrics={"reward_risk": 2.0},
                invalidation=["atr stop"],
            ),
        ],
        price=100.0,
    )
    assert decision.decision == Decision.LONG
    assert decision.confidence > 0
    assert decision.invalidation


def test_council_no_trade_poor_data() -> None:
    council = CouncilAggregator()
    decision = council.aggregate(
        [
            _a(SpecialistName.MARKET_STRUCTURE, Bias.LONG, 0.8, data_quality=0.2),
            _a(SpecialistName.MACRO_CROSS_ASSET, Bias.LONG, 0.7, data_quality=0.2),
        ],
        price=100.0,
    )
    assert decision.decision == Decision.NO_TRADE
