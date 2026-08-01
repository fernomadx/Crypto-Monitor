"""Multi-agent trade desk — confirma/veto sinais Kronos (TradingAgents-style)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class AnalystReport:
    name: str
    side: Side
    confidence: float
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


@dataclass
class DeskVerdict:
    side: Side
    confidence: float
    size_pct: float
    agrees_with_kronos: bool | None
    kronos_bias: str | None
    summary: str
    reports: list[AnalystReport] = field(default_factory=list)
    ticker: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "side": self.side.value,
            "confidence": self.confidence,
            "size_pct": self.size_pct,
            "agrees_with_kronos": self.agrees_with_kronos,
            "kronos_bias": self.kronos_bias,
            "summary": self.summary,
            "reports": [r.to_dict() for r in self.reports],
        }