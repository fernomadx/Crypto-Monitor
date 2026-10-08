"""Liquidity specialist and walk-forward tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Bias
from app.replay import VirtualClock, WalkForwardConfig, WalkForwardReplay, generate_purged_splits
from app.schemas import MarketSnapshot
from app.specialists.liquidity import LiquidityDerivativesSpecialist
from tests.conftest import make_candles


@pytest.mark.asyncio
async def test_liquidity_with_derivatives() -> None:
    candles = make_candles(n=60, trend=0.001)
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        price=candles[-1].close,
        timestamp=datetime.now(UTC),
        timeframes={"1h": candles},
        data_quality=0.9,
        sources=["test"],
    )
    derivatives = {
        "funding": 0.0008,
        "open_interest": 1e6,
        "open_interest_usd": 5e9,
        "oi_change": None,
        "basis_bps": 12.0,
        "mark_price": 65010.0,
        "index_price": 65000.0,
        "liquidations": [
            {"pos_side": "long", "side": "sell", "size": 1.0, "price": 64900.0},
            {"pos_side": "long", "side": "sell", "size": 2.0, "price": 64850.0},
            {"pos_side": "long", "side": "sell", "size": 1.5, "price": 64800.0},
        ],
        "availability": "AVAILABLE",
        "errors": [],
    }
    result = await LiquidityDerivativesSpecialist().analyze(snap, {"derivatives": derivatives})
    assert result.availability == "AVAILABLE"
    assert result.bias in {Bias.LONG, Bias.SHORT, Bias.NEUTRAL}
    assert result.evidence
    assert "crowded_long" in str(result.metrics.get("positioning_regime"))


@pytest.mark.asyncio
async def test_liquidity_unavailable_without_data() -> None:
    candles = make_candles(n=40)
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        price=candles[-1].close,
        timestamp=datetime.now(UTC),
        timeframes={"1h": candles},
        data_quality=0.9,
        sources=["test"],
    )
    result = await LiquidityDerivativesSpecialist().analyze(snap, {})
    assert result.availability == "DATA_UNAVAILABLE"


def test_purged_splits_have_embargo_gap() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 12, 1, tzinfo=UTC)
    splits = generate_purged_splits(
        start,
        end,
        WalkForwardConfig(
            train_size=timedelta(days=60),
            test_size=timedelta(days=14),
            step_size=timedelta(days=30),
            embargo=timedelta(days=3),
            purge=timedelta(days=1),
        ),
    )
    assert splits
    for s in splits:
        assert s.train_end <= s.embargo_start
        assert s.embargo_end <= s.test_start
        assert s.test_start < s.test_end


def test_walkforward_no_lookahead() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [
        {"event_time": (start + timedelta(days=i)).isoformat(), "close": 100 + i}
        for i in range(150)
    ]
    seen_futures = []

    def decision_fn(train, visible, clock: VirtualClock):
        # Capture whether any visible row is after clock
        for row in visible:
            ts = datetime.fromisoformat(row["event_time"])
            if ts > clock.now:
                seen_futures.append(ts)
        return {"decision": "NO_TRADE", "n": len(visible)}

    wf = WalkForwardReplay(
        WalkForwardConfig(
            train_size=timedelta(days=40),
            test_size=timedelta(days=10),
            step_size=timedelta(days=20),
            embargo=timedelta(days=2),
            purge=timedelta(days=1),
        )
    )
    result = wf.run(
        rows,
        start=start,
        end=start + timedelta(days=120),
        decision_fn=decision_fn,
        step=timedelta(days=3),
    )
    assert result.fold_results
    assert not seen_futures
    assert all(d.get("immutable") for f in result.fold_results for d in f["decisions"])
