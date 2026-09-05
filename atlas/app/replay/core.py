"""Replay core primitives."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class VirtualClock:
    def __init__(self, start: datetime):
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        self._now = start

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, to: datetime) -> None:
        if to.tzinfo is None:
            to = to.replace(tzinfo=UTC)
        if to < self._now:
            raise ValueError("cannot move virtual clock backwards in replay")
        self._now = to


class ReplaySession:
    """Reveals data only up to the virtual clock. Decisions are immutable once recorded."""

    def __init__(self, clock: VirtualClock):
        self.clock = clock
        self.decisions: list[dict[str, Any]] = []
        self.code_version = "0.1.0"

    def reveal(self, rows: list[dict[str, Any]], time_key: str = "event_time") -> list[dict[str, Any]]:
        out = []
        for row in rows:
            ts = row.get(time_key)
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts <= self.clock.now:
                out.append(row)
        return out

    def record_decision(self, decision: dict[str, Any]) -> None:
        frozen = dict(decision)
        frozen["recorded_at"] = self.clock.now.isoformat()
        frozen["immutable"] = True
        frozen["code_version"] = self.code_version
        self.decisions.append(frozen)
