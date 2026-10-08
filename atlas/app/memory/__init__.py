"""Memory package — case store interfaces for future investigation loop."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CouncilDecisionRecord, EvaluationRecord


class CaseMemory:
    """Persists and retrieves analysis cases. Never deletes history."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def archive_note(self, decision: CouncilDecisionRecord, note: str) -> dict[str, Any]:
        payload = dict(decision.payload or {})
        lessons = list(payload.get("lessons", []))
        lessons.append({"note": note, "status": "archived"})
        payload["lessons"] = lessons
        decision.payload = payload
        await self.session.commit()
        return {"decision_id": str(decision.id), "lessons": len(lessons)}

    async def attach_evaluation(self, evaluation: EvaluationRecord) -> UUID:
        self.session.add(evaluation)
        await self.session.commit()
        return evaluation.id
