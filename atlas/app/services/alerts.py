"""Decision-change alerts with optional Telegram delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.models import AlertRecord, CouncilDecisionRecord
from app.services.telegram import TelegramNotifier

logger = get_logger(__name__)


class DecisionAlertService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.telegram = TelegramNotifier(self.settings)

    async def check_and_emit(self, new_decision: CouncilDecisionRecord) -> AlertRecord | None:
        result = await self.session.execute(
            select(CouncilDecisionRecord)
            .where(
                CouncilDecisionRecord.symbol == new_decision.symbol,
                CouncilDecisionRecord.id != new_decision.id,
            )
            .order_by(CouncilDecisionRecord.created_at.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        if previous is None:
            return None
        if previous.decision == new_decision.decision:
            if abs(previous.confidence - new_decision.confidence) < 0.25:
                return None
            kind = "confidence_shift"
            message = (
                f"Confiança {previous.decision} {previous.confidence:.2f} → "
                f"{new_decision.confidence:.2f}"
            )
        else:
            kind = "decision_change"
            message = (
                f"Decisão {previous.decision} → {new_decision.decision} "
                f"(conf {new_decision.confidence:.2f})"
            )

        telegram_status: dict[str, Any] = {"status": "skipped"}
        if self.settings.telegram_alerts_enabled:
            telegram_status = await self.telegram.send_alert(
                kind=kind,
                message=message,
                symbol=new_decision.symbol,
                price=new_decision.price,
            )

        alert = AlertRecord(
            kind=kind,
            symbol=new_decision.symbol,
            message=message,
            payload={
                "previous_id": str(previous.id),
                "new_id": str(new_decision.id),
                "previous_decision": previous.decision,
                "new_decision": new_decision.decision,
                "previous_confidence": previous.confidence,
                "new_confidence": new_decision.confidence,
                "price": new_decision.price,
                "created_at": datetime.now(UTC).isoformat(),
                "telegram": telegram_status,
            },
            decision_id=new_decision.id,
        )
        self.session.add(alert)
        await self.session.commit()
        logger.info("alert_emitted", kind=kind, message=message, telegram=telegram_status.get("status"))
        return alert

    async def list_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "kind": r.kind,
                "symbol": r.symbol,
                "message": r.message,
                "payload": r.payload,
                "decision_id": str(r.decision_id) if r.decision_id else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "acknowledged": r.acknowledged,
            }
            for r in rows
        ]

    async def acknowledge(self, alert_id: UUID) -> bool:
        result = await self.session.execute(select(AlertRecord).where(AlertRecord.id == alert_id))
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.acknowledged = True
        await self.session.commit()
        return True
