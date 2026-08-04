"""Analysis orchestration service."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.btc import BtcMarketCollector
from app.collectors.providers.stooq import StooqProvider
from app.collectors.providers.yahoo import YahooMacroProvider
from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.council import CouncilAggregator
from app.models import CouncilDecisionRecord, SpecialistAssessmentRecord
from app.reports import build_report_json, build_report_markdown
from app.schemas import AnalysisRunResponse, CouncilDecision, DecisionSummary, MarketSnapshot
from app.specialists import (
    DynamicCorrelationSpecialist,
    ExperienceSpecialist,
    LiquidityDerivativesSpecialist,
    MacroCrossAssetSpecialist,
    MarketStructureSpecialist,
    NewsEventsSpecialist,
    RiskSpecialist,
)
from app.specialists.correlation import load_macro_context
from app.utils.jsonable import to_jsonable

logger = get_logger(__name__)


class AnalysisService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.collector = BtcMarketCollector(session, settings=self.settings)
        self.council = CouncilAggregator()
        self.specialists = [
            MarketStructureSpecialist(),
            DynamicCorrelationSpecialist(),
            MacroCrossAssetSpecialist(),
            LiquidityDerivativesSpecialist(),
            NewsEventsSpecialist(),
            ExperienceSpecialist(),
            RiskSpecialist(),
        ]

    async def run_btc_analysis(self, collect: bool = True) -> AnalysisRunResponse:
        snapshot: MarketSnapshot | None
        if collect:
            snapshot = await self.collector.collect()
        else:
            snapshot = await self.collector.latest_snapshot()
            if snapshot is None:
                snapshot = await self.collector.collect()
        assert snapshot is not None

        context = await self._build_context(snapshot)
        assessments = []
        for specialist in self.specialists:
            try:
                assessment = await specialist.analyze(snapshot, context)
            except Exception as exc:  # noqa: BLE001
                logger.error("specialist_failed", specialist=specialist.name, error=str(exc))
                assessment = specialist.unavailable(snapshot.symbol, "1h", str(exc))
            assessments.append(assessment)
            # enrich context for downstream specialists
            name = assessment.specialist.value if hasattr(assessment.specialist, "value") else str(assessment.specialist)
            if name == "dynamic_correlation":
                context["correlation_metrics"] = to_jsonable(assessment.metrics)

        # Refresh macro with correlation context
        for i, specialist in enumerate(self.specialists):
            if isinstance(specialist, MacroCrossAssetSpecialist):
                assessments[i] = await specialist.analyze(snapshot, context)
                break

        # Sanitize metrics for JSON persistence
        for assessment in assessments:
            assessment.metrics = to_jsonable(assessment.metrics)

        decision = self.council.aggregate(
            assessments,
            symbol=snapshot.symbol,
            price=snapshot.price,
        )
        report_md = build_report_markdown(decision)
        report_json = build_report_json(decision)
        decision_id = await self._persist(decision, report_md, assessments)
        logger.info(
            "analysis_complete",
            decision_id=str(decision_id),
            decision=decision.decision.value,
            confidence=decision.confidence,
        )
        return AnalysisRunResponse(
            decision_id=decision_id,
            decision=decision,
            report_markdown=report_md,
            report_json=report_json,
        )

    async def _build_context(self, snapshot: MarketSnapshot) -> dict[str, Any]:
        context: dict[str, Any] = {"snapshot_quality": snapshot.data_quality}
        providers: list[Any] = []
        if self.settings.stooq_enabled:
            providers.append(StooqProvider(self.settings))
        providers.append(YahooMacroProvider(self.settings))
        macro: dict[str, list[dict[str, Any]]] = {}
        try:
            for provider in providers:
                partial = await load_macro_context(provider)
                for key, rows in partial.items():
                    if key not in macro and rows:
                        macro[key] = rows
                if len(macro) >= 5:
                    break
        finally:
            for provider in providers:
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
        context["macro_series"] = macro
        context["macro_source_count"] = len(macro)
        return context

    async def _persist(
        self,
        decision: CouncilDecision,
        report_md: str,
        assessments: list[Any],
    ) -> UUID:
        record = CouncilDecisionRecord(
            symbol=decision.symbol,
            decision=decision.decision.value,
            confidence=decision.confidence,
            market_regime=decision.market_regime,
            primary_hypothesis=decision.primary_hypothesis,
            data_quality=decision.data_quality,
            price=decision.price,
            payload=decision.model_dump(mode="json"),
            report_markdown=report_md,
            model_version=decision.model_version,
        )
        self.session.add(record)
        await self.session.flush()

        for a in assessments:
            self.session.add(
                SpecialistAssessmentRecord(
                    decision_id=record.id,
                    specialist=a.specialist.value if hasattr(a.specialist, "value") else str(a.specialist),
                    symbol=a.symbol,
                    timeframe=a.timeframe,
                    bias=a.bias.value,
                    confidence=a.confidence,
                    data_quality=a.data_quality,
                    payload=a.model_dump(mode="json"),
                    model_version=a.model_version,
                )
            )
        await self.session.commit()
        return record.id

    async def latest_decision(self) -> AnalysisRunResponse | None:
        result = await self.session.execute(
            select(CouncilDecisionRecord).order_by(CouncilDecisionRecord.created_at.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        decision = CouncilDecision.model_validate(row.payload)
        return AnalysisRunResponse(
            decision_id=row.id,
            decision=decision,
            report_markdown=row.report_markdown,
            report_json=build_report_json(decision),
        )

    async def list_decisions(self, limit: int = 20) -> list[DecisionSummary]:
        result = await self.session.execute(
            select(CouncilDecisionRecord)
            .order_by(CouncilDecisionRecord.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            DecisionSummary(
                id=r.id,
                decision=r.decision,  # type: ignore[arg-type]
                confidence=r.confidence,
                market_regime=r.market_regime,
                primary_hypothesis=r.primary_hypothesis,
                data_quality=r.data_quality,
                symbol=r.symbol,
                price=r.price,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def get_decision(self, decision_id: UUID) -> AnalysisRunResponse | None:
        result = await self.session.execute(
            select(CouncilDecisionRecord).where(CouncilDecisionRecord.id == decision_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        decision = CouncilDecision.model_validate(row.payload)
        return AnalysisRunResponse(
            decision_id=row.id,
            decision=decision,
            report_markdown=row.report_markdown,
            report_json=build_report_json(decision),
        )

    def specialists_status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name.value,
                "model_version": s.model_version,
                "status": "ready",
            }
            for s in self.specialists
        ]
