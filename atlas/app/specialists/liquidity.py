"""Liquidity and Derivatives Specialist — interface first."""

from __future__ import annotations

from typing import Any

from app.core.enums import Bias, SpecialistName
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist


class LiquidityDerivativesSpecialist(BaseSpecialist):
    name = SpecialistName.LIQUIDITY_DERIVATIVES
    model_version = "0.1.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        derivatives = context.get("derivatives")

        if not derivatives:
            assessment = self.unavailable(
                snapshot.symbol,
                "1h",
                "funding/OI/liquidations/basis not connected in v0.1",
            )
            assessment.metrics = {
                "expected_fields": [
                    "funding",
                    "open_interest",
                    "oi_change",
                    "liquidations",
                    "basis",
                    "spot_volume",
                    "futures_volume",
                    "cvd",
                ],
                "status": "DATA_UNAVAILABLE",
            }
            assessment.alternative_hypotheses = [
                "Quando dados existirem: distinguir compra spot vs short squeeze vs deleveraging",
            ]
            return assessment

        # Future path when derivatives dict is supplied
        evidence: list = []
        risks: list[str] = []
        score = 0.0
        funding = derivatives.get("funding")
        oi_change = derivatives.get("oi_change")
        if funding is not None:
            if funding > 0.0005:
                score -= 0.2
                risks.append("funding elevado — longs pagam, risco de long squeeze")
                evidence.append(self.evidence(f"Funding positivo elevado ({funding})", 0.6))
            elif funding < -0.0005:
                score += 0.2
                evidence.append(self.evidence(f"Funding negativo ({funding}) — shorts pagam", 0.6))
        if oi_change is not None and snapshot.price:
            # price up + oi up => leverage expansion; price up + oi down => short cover
            pass

        bias = Bias.LONG if score > 0.15 else Bias.SHORT if score < -0.15 else Bias.NEUTRAL
        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe="1h",
            bias=bias,
            confidence=self.dampen_confidence(0.5, sample_size=1, min_sample=1, data_quality=0.7),
            data_quality=0.7,
            evidence=evidence,
            risks=risks,
            invalidation_conditions=["Mudança abrupta de funding/OI contra a hipótese"],
            alternative_hypotheses=[],
            metrics=derivatives,
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
