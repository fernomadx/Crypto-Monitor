"""Walk-forward replay with embargo and purged temporal splits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.replay.core import ReplaySession, VirtualClock


@dataclass(frozen=True)
class TimeSplit:
    train_start: datetime
    train_end: datetime
    embargo_start: datetime
    embargo_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass
class WalkForwardConfig:
    train_size: timedelta = timedelta(days=90)
    test_size: timedelta = timedelta(days=14)
    step_size: timedelta = timedelta(days=14)
    embargo: timedelta = timedelta(days=3)
    purge: timedelta = timedelta(days=1)


@dataclass
class WalkForwardResult:
    splits: list[TimeSplit]
    fold_results: list[dict[str, Any]] = field(default_factory=list)
    code_version: str = "0.2.0"
    notes: list[str] = field(default_factory=list)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def generate_purged_splits(
    start: datetime,
    end: datetime,
    config: WalkForwardConfig | None = None,
) -> list[TimeSplit]:
    """Expanding/rolling walk-forward with purge+embargo between train and test."""
    cfg = config or WalkForwardConfig()
    start, end = _aware(start), _aware(end)
    splits: list[TimeSplit] = []

    train_end = start + cfg.train_size
    while True:
        embargo_start = train_end
        embargo_end = train_end + cfg.embargo
        test_start = embargo_end + cfg.purge
        test_end = test_start + cfg.test_size
        if test_end > end:
            break
        splits.append(
            TimeSplit(
                train_start=start,
                train_end=train_end - cfg.purge,  # purge end of train near embargo
                embargo_start=embargo_start,
                embargo_end=embargo_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        train_end = train_end + cfg.step_size
    return splits


def filter_rows_in_window(
    rows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    time_key: str = "event_time",
) -> list[dict[str, Any]]:
    start, end = _aware(start), _aware(end)
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get(time_key)
        if ts is None:
            continue
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        ts = _aware(ts)
        if start <= ts <= end:
            out.append(row)
    return out


class WalkForwardReplay:
    """
    Runs a decision function fold-by-fold without look-ahead.

    decision_fn(train_rows, test_asof_rows, clock) -> dict decision
    The test rows passed are only those revealed up to the virtual clock.
    """

    def __init__(self, config: WalkForwardConfig | None = None, code_version: str = "0.2.0"):
        self.config = config or WalkForwardConfig()
        self.code_version = code_version

    def run(
        self,
        rows: list[dict[str, Any]],
        *,
        start: datetime,
        end: datetime,
        decision_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], VirtualClock], dict[str, Any]],
        time_key: str = "event_time",
        step: timedelta | None = None,
    ) -> WalkForwardResult:
        splits = generate_purged_splits(start, end, self.config)
        result = WalkForwardResult(splits=splits, code_version=self.code_version)
        result.notes.extend(
            [
                "Walk-forward com purged train end + embargo antes do teste",
                "Dados futuros nunca revelados ao decision_fn",
                "Decisões gravadas como imutáveis por fold",
                "Sem uso de pesos de produção alterados automaticamente",
            ]
        )

        for i, split in enumerate(splits):
            train_rows = filter_rows_in_window(rows, split.train_start, split.train_end, time_key)
            clock = VirtualClock(split.test_start)
            session = ReplaySession(clock)
            session.code_version = self.code_version

            fold_decisions: list[dict[str, Any]] = []
            cursor = split.test_start
            step_delta = step or timedelta(days=1)
            while cursor <= split.test_end:
                clock.advance(cursor)
                visible_test = session.reveal(
                    filter_rows_in_window(rows, split.test_start, split.test_end, time_key),
                    time_key=time_key,
                )
                # Also ensure no leakage from after cursor in train (already purged)
                decision = decision_fn(train_rows, visible_test, clock)
                session.record_decision(decision)
                fold_decisions.append(dict(session.decisions[-1]))
                cursor = cursor + step_delta

            result.fold_results.append(
                {
                    "fold": i,
                    "train_start": split.train_start.isoformat(),
                    "train_end": split.train_end.isoformat(),
                    "embargo": [split.embargo_start.isoformat(), split.embargo_end.isoformat()],
                    "test_start": split.test_start.isoformat(),
                    "test_end": split.test_end.isoformat(),
                    "n_train": len(train_rows),
                    "n_decisions": len(fold_decisions),
                    "decisions": fold_decisions,
                }
            )
        return result
