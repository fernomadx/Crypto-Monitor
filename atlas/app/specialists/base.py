"""Base specialist interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.core.enums import Bias, SpecialistName
from app.schemas import EvidenceItem, MarketSnapshot, SpecialistAssessment


class BaseSpecialist(ABC):
    name: SpecialistName
    model_version: str = "0.1.0"

    @abstractmethod
    async def analyze(self, snapshot: MarketSnapshot, context: dict[str, Any] | None = None) -> SpecialistAssessment:
        raise NotImplementedError

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def unavailable(
        self,
        symbol: str,
        timeframe: str,
        reason: str,
    ) -> SpecialistAssessment:
        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=symbol,
            timeframe=timeframe,
            bias=Bias.NO_TRADE,
            confidence=0.0,
            data_quality=0.0,
            evidence=[],
            risks=[reason],
            invalidation_conditions=[],
            alternative_hypotheses=[],
            metrics={},
            model_version=self.model_version,
            errors=[f"DATA_UNAVAILABLE: {reason}"],
            availability="DATA_UNAVAILABLE",
        )

    @staticmethod
    def evidence(claim: str, weight: float = 0.5, source: str = "", timeframe: str | None = None) -> EvidenceItem:
        return EvidenceItem(claim=claim, weight=weight, source=source, timeframe=timeframe)

    def dampen_confidence(
        self,
        confidence: float,
        *,
        sample_size: int,
        min_sample: int,
        data_quality: float,
        regime_uncertain: bool = False,
    ) -> float:
        conf = confidence
        if sample_size < min_sample:
            conf = min(conf, 0.35)
        if data_quality < 0.6:
            conf = min(conf, 0.4)
        if regime_uncertain:
            conf = min(conf, 0.45)
        return round(max(0.0, min(1.0, conf)), 4)
