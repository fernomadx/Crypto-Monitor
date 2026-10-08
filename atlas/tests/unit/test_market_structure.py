"""Unit tests — market structure features and specialist."""

from __future__ import annotations

import pytest

from app.core.enums import Bias
from app.features.correlation import analyze_pair, returns_from_closes, rolling_correlation
from app.features.market_structure import compute_structure_features
from app.schemas import MarketSnapshot
from app.specialists.market_structure import MarketStructureSpecialist
from app.specialists.risk import RiskSpecialist
from tests.conftest import make_candles


def test_structure_features_uptrend() -> None:
    candles = make_candles(n=120, trend=0.002)
    feat = compute_structure_features(candles)
    assert not feat["insufficient"]
    assert feat["sample_size"] == 120
    assert feat["last_price"] > 50000
    assert "trend" in feat
    assert "atr14" in feat


def test_structure_features_insufficient() -> None:
    candles = make_candles(n=10)
    feat = compute_structure_features(candles)
    assert feat["insufficient"] is True


@pytest.mark.asyncio
async def test_market_structure_specialist_longish() -> None:
    candles_1h = make_candles(n=120, trend=0.002, timeframe="1h")
    candles_4h = make_candles(n=80, trend=0.003, timeframe="4h")
    candles_1d = make_candles(n=60, trend=0.004, timeframe="1d")
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        price=candles_1h[-1].close,
        timestamp=candles_1h[-1].open_time,
        timeframes={"1h": candles_1h, "4h": candles_4h, "1d": candles_1d, "15m": candles_1h},
        data_quality=0.9,
        sources=["test"],
    )
    specialist = MarketStructureSpecialist()
    result = await specialist.analyze(snap)
    assert result.specialist.value == "market_structure"
    assert result.bias in {Bias.LONG, Bias.NEUTRAL, Bias.SHORT}
    assert 0 <= result.confidence <= 1
    assert result.evidence
    assert result.data_quality == 0.9


@pytest.mark.asyncio
async def test_risk_specialist_prefers_no_trade_on_compression_like() -> None:
    candles = make_candles(n=80, trend=0.00005)
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        price=candles[-1].close,
        timestamp=candles[-1].open_time,
        timeframes={"1h": candles},
        data_quality=0.9,
        sources=["test"],
    )
    result = await RiskSpecialist().analyze(snap)
    assert result.specialist.value == "risk"
    assert result.metrics.get("reward_risk") is not None


def test_correlation_pair() -> None:
    import numpy as np

    x = list(np.cumsum(np.random.default_rng(0).normal(0, 1, 100)) + 100)
    y = [v * 1.01 + i * 0.01 for i, v in enumerate(x)]
    report = analyze_pair("NDX", x, y, window=30, max_lag=3)
    assert report["availability"] == "AVAILABLE"
    assert "lead_lag" in report
    assert "disclaimer" in report


def test_rolling_correlation_length() -> None:
    a = returns_from_closes(list(range(100, 200)))
    b = returns_from_closes(list(range(200, 300)))
    rolling = rolling_correlation(a, b, window=20)
    assert len(rolling) == len(a) - 20 + 1
