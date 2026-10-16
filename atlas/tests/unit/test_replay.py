"""Replay virtual clock tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.replay import ReplaySession, VirtualClock


def test_virtual_clock_no_lookahead() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    clock = VirtualClock(start)
    session = ReplaySession(clock)
    rows = [
        {"event_time": (start - timedelta(days=1)).isoformat(), "v": 1},
        {"event_time": start.isoformat(), "v": 2},
        {"event_time": (start + timedelta(days=1)).isoformat(), "v": 3},
    ]
    visible = session.reveal(rows)
    assert [r["v"] for r in visible] == [1, 2]
    clock.advance(start + timedelta(days=1))
    visible2 = session.reveal(rows)
    assert [r["v"] for r in visible2] == [1, 2, 3]


def test_clock_cannot_go_backwards() -> None:
    clock = VirtualClock(datetime(2024, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError):
        clock.advance(datetime(2024, 1, 1, tzinfo=UTC))


def test_decision_immutable_record() -> None:
    clock = VirtualClock(datetime(2024, 1, 1, tzinfo=UTC))
    session = ReplaySession(clock)
    session.record_decision({"decision": "NO_TRADE"})
    assert session.decisions[0]["immutable"] is True
