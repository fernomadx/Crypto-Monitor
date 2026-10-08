"""Versioned council weight calibration — proposes, never auto-applies to production."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.council import SPECIALIST_PRIOR
from app.models import CouncilDecisionRecord, EvaluationRecord, ModelWeightVersion

logger = get_logger(__name__)

MIN_EVALUATIONS = 20


class WeightCalibrator:
    """
    Builds a candidate weight version from evaluation history.

    Production weights change only when a version is explicitly activated.
    Isolated errors never mutate production.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def propose(
        self,
        *,
        min_evaluations: int = MIN_EVALUATIONS,
        note: str = "",
    ) -> dict[str, Any]:
        evals = await self._load_evaluations()
        if len(evals) < min_evaluations:
            return {
                "status": "insufficient_sample",
                "n_evaluations": len(evals),
                "required": min_evaluations,
                "message": "Amostra insuficiente — nenhuma alteração de produção proposta",
            }

        specialist_scores: dict[str, list[float]] = {k: [] for k in SPECIALIST_PRIOR}
        for ev, decision in evals:
            payload = decision.payload or {}
            votes = payload.get("specialist_votes") or []
            # reward specialists that agreed with eventually-good outcomes
            outcome = float(ev.result_quality)
            reasoning = float(ev.reasoning_quality)
            for vote in votes:
                name = vote.get("specialist")
                if name not in specialist_scores:
                    continue
                bias = vote.get("bias")
                decided = decision.decision
                agree = 0.0
                if decided in {"LONG", "SHORT"} and bias == decided:
                    agree = 1.0
                elif decided == "NO_TRADE" and bias in {"NEUTRAL", "NO_TRADE"}:
                    agree = 0.7
                elif bias in {"LONG", "SHORT"} and decided != bias:
                    agree = 0.2
                else:
                    agree = 0.5
                specialist_scores[name].append(0.5 * outcome + 0.3 * reasoning + 0.2 * agree)

        priors = dict(SPECIALIST_PRIOR)
        proposed: dict[str, float] = {}
        for name, scores in specialist_scores.items():
            if len(scores) < max(5, min_evaluations // 4):
                proposed[name] = priors[name]
                continue
            mean = sum(scores) / len(scores)
            # Map [0,1] performance to weight multiplier around prior
            multiplier = 0.7 + mean  # ~0.7–1.7
            proposed[name] = round(max(0.3, min(1.8, priors[name] * multiplier)), 4)

        version = ModelWeightVersion(
            id=uuid4(),
            version_label=f"candidate-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            status="candidate",
            weights=proposed,
            priors=priors,
            metrics={
                "n_evaluations": len(evals),
                "specialist_sample_sizes": {k: len(v) for k, v in specialist_scores.items()},
                "mean_result_quality": sum(e.result_quality for e, _ in evals) / len(evals),
                "mean_reasoning_quality": sum(e.reasoning_quality for e, _ in evals) / len(evals),
            },
            notes=note
            or "Proposta automática — requer ativação explícita; não altera produção sozinha",
        )
        self.session.add(version)
        await self.session.commit()
        logger.info("weight_candidate_created", version=version.version_label, n=len(evals))
        return {
            "status": "proposed",
            "id": str(version.id),
            "version_label": version.version_label,
            "weights": proposed,
            "metrics": version.metrics,
            "production_unchanged": True,
        }

    async def activate(self, version_id: UUID) -> dict[str, Any]:
        result = await self.session.execute(
            select(ModelWeightVersion).where(ModelWeightVersion.id == version_id)
        )
        version = result.scalar_one_or_none()
        if version is None:
            return {"status": "not_found"}
        if version.status == "rejected":
            return {"status": "rejected_cannot_activate"}

        # Deactivate current production
        active = await self.session.execute(
            select(ModelWeightVersion).where(ModelWeightVersion.status == "active")
        )
        for row in active.scalars().all():
            row.status = "archived"
            row.archived_at = datetime.now(UTC)

        version.status = "active"
        version.activated_at = datetime.now(UTC)
        await self.session.commit()
        return {
            "status": "activated",
            "id": str(version.id),
            "version_label": version.version_label,
            "weights": version.weights,
        }

    async def reject(self, version_id: UUID, reason: str = "") -> dict[str, Any]:
        result = await self.session.execute(
            select(ModelWeightVersion).where(ModelWeightVersion.id == version_id)
        )
        version = result.scalar_one_or_none()
        if version is None:
            return {"status": "not_found"}
        version.status = "rejected"
        version.notes = (version.notes or "") + f"\nRejected: {reason}"
        version.archived_at = datetime.now(UTC)
        await self.session.commit()
        return {"status": "rejected", "id": str(version.id)}

    async def get_active_weights(self) -> dict[str, float]:
        result = await self.session.execute(
            select(ModelWeightVersion)
            .where(ModelWeightVersion.status == "active")
            .order_by(ModelWeightVersion.activated_at.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        if version is None:
            return dict(SPECIALIST_PRIOR)
        return dict(version.weights)

    async def list_versions(self, limit: int = 20) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(ModelWeightVersion)
            .order_by(ModelWeightVersion.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "version_label": r.version_label,
                "status": r.status,
                "weights": r.weights,
                "metrics": r.metrics,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "activated_at": r.activated_at.isoformat() if r.activated_at else None,
            }
            for r in rows
        ]

    async def _load_evaluations(self) -> list[tuple[EvaluationRecord, CouncilDecisionRecord]]:
        result = await self.session.execute(
            select(EvaluationRecord, CouncilDecisionRecord)
            .join(CouncilDecisionRecord, CouncilDecisionRecord.id == EvaluationRecord.decision_id)
            .order_by(EvaluationRecord.created_at.asc())
        )
        out: list[tuple[EvaluationRecord, CouncilDecisionRecord]] = []
        for row in result.all():
            out.append((row[0], row[1]))
        return out
