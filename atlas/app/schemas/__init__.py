"""Pydantic schemas — specialist and council contracts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.enums import Bias, Decision, SpecialistName


class EvidenceItem(BaseModel):
    claim: str
    weight: float = Field(ge=0.0, le=1.0, default=0.5)
    source: str = ""
    timeframe: str | None = None


class SpecialistAssessment(BaseModel):
    specialist: SpecialistName | str
    timestamp: datetime
    symbol: str
    timeframe: str
    bias: Bias
    confidence: float = Field(ge=0.0, le=1.0)
    data_quality: float = Field(ge=0.0, le=1.0)
    evidence: Sequence[EvidenceItem | str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    alternative_hypotheses: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    model_version: str = "0.1.0"
    errors: list[str] = Field(default_factory=list)
    availability: str = "AVAILABLE"

    @field_validator("confidence")
    @classmethod
    def cap_confidence_bounds(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class CouncilDecision(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    market_regime: str
    primary_hypothesis: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    invalidation: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    specialist_votes: list[SpecialistAssessment] = Field(default_factory=list)
    data_quality: float = Field(ge=0.0, le=1.0)
    symbol: str = "BTC/USDT"
    price: float | None = None
    timestamp: datetime | None = None
    model_version: str = "0.1.0"


class CandleDTO(BaseModel):
    symbol: str
    timeframe: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    collected_at: datetime
    event_time: datetime
    latency_ms: float | None = None
    completeness: float = 1.0
    raw_payload_hash: str = ""


class MarketSnapshot(BaseModel):
    symbol: str
    price: float
    timestamp: datetime
    timeframes: dict[str, list[CandleDTO]]
    data_quality: float
    sources: list[str]
    lag_sec: float | None = None


class HealthComponent(BaseModel):
    name: str
    status: str
    detail: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str
    components: list[HealthComponent]


class DecisionSummary(BaseModel):
    id: UUID
    decision: Decision
    confidence: float
    market_regime: str
    primary_hypothesis: str
    data_quality: float
    symbol: str
    price: float | None
    created_at: datetime


class AnalysisRunResponse(BaseModel):
    decision_id: UUID
    decision: CouncilDecision
    report_markdown: str
    report_json: dict[str, Any]
