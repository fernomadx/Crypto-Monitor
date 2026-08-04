"""Core enums and constants."""

from __future__ import annotations

from enum import StrEnum


class Bias(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    NO_TRADE = "NO_TRADE"


class Decision(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class DataAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class SpecialistName(StrEnum):
    MARKET_STRUCTURE = "market_structure"
    MACRO_CROSS_ASSET = "macro_cross_asset"
    DYNAMIC_CORRELATION = "dynamic_correlation"
    LIQUIDITY_DERIVATIVES = "liquidity_derivatives"
    NEWS_EVENTS = "news_events"
    EXPERIENCE = "experience"
    RISK = "risk"


TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d", "1w")

BINANCE_INTERVAL_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}

EVALUATION_HORIZONS = ("15m", "1h", "4h", "24h", "7d")
