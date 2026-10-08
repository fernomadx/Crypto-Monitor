"""Batch evaluation of due decisions + optional weight proposal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.council.calibration import MIN_EVALUATIONS, WeightCalibrator
from app.evaluation.core import DecisionEvaluator
from app.models import CouncilDecisionRecord

logger = get_logger(__name__)


class BatchEvaluationService:
    """
    Evaluates decisions whose minimum horizon has elapsed.

    Never auto-activates production weights. May propose a candidate version
    after enough evaluations when auto_propose=True.
    """

    def __init__(self, session: AsyncSession, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.evaluator = DecisionEvaluator(session)
        self.calibrator = WeightCalibrator(session)

    async def run(
        self,
        *,
        limit: int = 50,
        min_age: timedelta | None = None,
        auto_propose: bool | None = None,
        min_evaluations_for_propose: int | None = None,
    ) -> dict[str, Any]:
        if min_age is None:
            min_age = timedelta(hours=self.settings.eval_min_age_hours)
        if auto_propose is None:
            auto_propose = self.settings.eval_auto_propose
        if min_evaluations_for_propose is None:
            min_evaluations_for_propose = self.settings.eval_min_for_propose

        cutoff = datetime.now(UTC) - min_age
        result = await self.session.execute(
            select(CouncilDecisionRecord)
            .where(
                CouncilDecisionRecord.evaluated_at.is_(None),
                CouncilDecisionRecord.created_at <= cutoff,
            )
            .order_by(CouncilDecisionRecord.created_at.asc())
            .limit(limit)
        )
        pending = list(result.scalars().all())
        evaluated: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for decision in pending:
            try:
                out = await self.evaluator.evaluate_decision(decision.id)
                if out.get("status") == "evaluated":
                    evaluated.append(out)
                else:
                    skipped.append(out)
            except Exception as exc:  # noqa: BLE001
                logger.warning("batch_eval_failed", decision_id=str(decision.id), error=str(exc))
                skipped.append(
                    {"decision_id": str(decision.id), "status": "error", "detail": str(exc)}
                )

        proposal = None
        if auto_propose and len(evaluated) > 0:
            proposal = await self.calibrator.propose(
                min_evaluations=min_evaluations_for_propose,
                note=(
                    f"Auto-proposta após batch evaluation "
                    f"({len(evaluated)} novos outcomes). Produção inalterada."
                ),
            )
            if proposal.get("status") == "insufficient_sample":
                proposal = {
                    **proposal,
                    "note": "Batch ran; weight proposal deferred until sample threshold",
                }

        return {
            "pending_found": len(pending),
            "evaluated": evaluated,
            "skipped": skipped,
            "n_evaluated": len(evaluated),
            "weight_proposal": proposal,
            "production_weights_unchanged": True,
            "min_evaluations_for_propose": min_evaluations_for_propose or MIN_EVALUATIONS,
        }
