"""Evaluation of past decisions — no auto-recalibration of production."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EVALUATION_HORIZONS
from app.models import Candle, CouncilDecisionRecord, EvaluationRecord, PredictionOutcome

HORIZON_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class DecisionEvaluator:
    """Scores result quality vs reasoning quality. Does not mutate production weights."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def evaluate_decision(self, decision_id: UUID) -> dict[str, Any]:
        result = await self.session.execute(
            select(CouncilDecisionRecord).where(CouncilDecisionRecord.id == decision_id)
        )
        decision = result.scalar_one_or_none()
        if decision is None:
            raise ValueError(f"decision {decision_id} not found")
        if decision.evaluated_at is not None:
            return {"status": "already_evaluated", "decision_id": str(decision_id)}

        entry_price = decision.price
        created = decision.created_at
        if entry_price is None:
            return {"status": "skipped", "reason": "no entry price"}

        outcomes: list[dict[str, Any]] = []
        direction_hits = 0
        horizons_checked = 0

        for horizon in EVALUATION_HORIZONS:
            delta = HORIZON_DELTAS[horizon]
            target_time = created + delta
            # Use 1h candles for path stats when available
            candles = await self._candles_between(decision.symbol, "1h", created, target_time)
            if not candles:
                continue
            horizons_checked += 1
            closes = [c.close for c in candles]
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            end_price = closes[-1]
            ret = end_price / entry_price - 1.0
            mfe = (max(highs) / entry_price - 1.0) if decision.decision == "LONG" else (entry_price / min(lows) - 1.0)
            mae = (entry_price / min(lows) - 1.0) if decision.decision == "LONG" else (max(highs) / entry_price - 1.0)
            if decision.decision == "SHORT":
                mfe = entry_price / min(lows) - 1.0
                mae = max(highs) / entry_price - 1.0
                direction_correct = ret < 0
            elif decision.decision == "LONG":
                mfe = max(highs) / entry_price - 1.0
                mae = entry_price / min(lows) - 1.0
                direction_correct = ret > 0
            else:
                direction_correct = abs(ret) < 0.01
                mfe = max(abs(max(highs) / entry_price - 1), abs(entry_price / min(lows) - 1))
                mae = mfe

            if direction_correct:
                direction_hits += 1

            outcome = PredictionOutcome(
                decision_id=decision.id,
                horizon=horizon,
                return_pct=ret,
                mae=mae,
                mfe=mfe,
                direction_correct=direction_correct,
                payload={"end_price": end_price, "bars": len(candles)},
            )
            self.session.add(outcome)
            outcomes.append(
                {
                    "horizon": horizon,
                    "return_pct": ret,
                    "mae": mae,
                    "mfe": mfe,
                    "direction_correct": direction_correct,
                }
            )

        result_quality = direction_hits / max(horizons_checked, 1)
        # Reasoning quality proxy: evidence present + invalidation defined + not contradicted by data gaps
        payload = decision.payload or {}
        has_evidence = bool(payload.get("supporting_evidence"))
        has_invalidation = bool(payload.get("invalidation"))
        reasoning_quality = 0.2 + 0.3 * float(has_evidence) + 0.3 * float(has_invalidation)
        reasoning_quality += 0.2 * float(decision.data_quality)
        reasoning_quality = min(1.0, reasoning_quality)

        classification = self._classify(
            decision.decision,
            result_quality,
            reasoning_quality,
            decision.data_quality,
        )

        evaluation = EvaluationRecord(
            decision_id=decision.id,
            result_quality=result_quality,
            reasoning_quality=reasoning_quality,
            data_quality=decision.data_quality,
            classification=classification,
            notes="Auto-evaluation v0.1 — no production weight updates",
            payload={"outcomes": outcomes},
        )
        self.session.add(evaluation)
        decision.evaluated_at = datetime.now(UTC)
        await self.session.commit()

        return {
            "status": "evaluated",
            "decision_id": str(decision_id),
            "result_quality": result_quality,
            "reasoning_quality": reasoning_quality,
            "classification": classification,
            "outcomes": outcomes,
        }

    async def _candles_between(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        result = await self.session.execute(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time >= start,
                Candle.open_time <= end,
            )
            .order_by(Candle.open_time.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _classify(
        decision: str,
        result_quality: float,
        reasoning_quality: float,
        data_quality: float,
    ) -> str:
        if decision == "NO_TRADE":
            return "no_trade_recorded"
        if result_quality >= 0.6 and reasoning_quality >= 0.6:
            return "acerto_por_raciocinio_correto"
        if result_quality >= 0.6 and reasoning_quality < 0.45:
            return "acerto_acidental"
        if result_quality >= 0.4:
            return "acerto_parcial"
        if data_quality < 0.5:
            return "erro_de_informacao"
        if reasoning_quality < 0.45:
            return "erro_de_raciocinio"
        return "evento_imprevisivel_ou_regime_nao_reconhecido"
