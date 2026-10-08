"""Report builder tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import Bias, Decision, SpecialistName
from app.reports import build_report_json, build_report_markdown
from app.schemas import CouncilDecision, EvidenceItem, SpecialistAssessment


def test_report_contains_required_sections() -> None:
    assessment = SpecialistAssessment(
        specialist=SpecialistName.MARKET_STRUCTURE,
        timestamp=datetime.now(UTC),
        symbol="BTC/USDT",
        timeframe="1h",
        bias=Bias.NEUTRAL,
        confidence=0.4,
        data_quality=0.8,
        evidence=[EvidenceItem(claim="range")],
    )
    decision = CouncilDecision(
        decision=Decision.NO_TRADE,
        confidence=0.5,
        market_regime="range",
        primary_hypothesis="NO_TRADE: sem edge",
        supporting_evidence=["sem edge"],
        specialist_votes=[assessment],
        data_quality=0.8,
        price=65000.0,
        timestamp=datetime.now(UTC),
    )
    md = build_report_markdown(decision)
    assert "ATLAS BTC ANALYSIS" in md
    assert "Decisão" in md or "DECIS" in md.upper() or "## Decisão" in md
    assert "Invalidação" in md
    js = build_report_json(decision)
    assert js["decision"] == "NO_TRADE"
    assert "what_would_change_mind" in js
