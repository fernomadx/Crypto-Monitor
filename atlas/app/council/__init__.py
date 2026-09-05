"""Council Aggregator — weighted consensus, not a simple average."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.enums import Bias, Decision, SpecialistName
from app.schemas import CouncilDecision, SpecialistAssessment

# Base reliability priors (will be replaced by historical performance later)
SPECIALIST_PRIOR: dict[str, float] = {
    SpecialistName.MARKET_STRUCTURE.value: 1.0,
    SpecialistName.MACRO_CROSS_ASSET.value: 0.85,
    SpecialistName.DYNAMIC_CORRELATION.value: 0.8,
    SpecialistName.LIQUIDITY_DERIVATIVES.value: 0.9,
    SpecialistName.NEWS_EVENTS.value: 0.55,
    SpecialistName.EXPERIENCE.value: 0.6,
    SpecialistName.RISK.value: 1.1,
}


class CouncilAggregator:
    model_version = "0.1.0"

    def aggregate(
        self,
        assessments: list[SpecialistAssessment],
        *,
        symbol: str = "BTC/USDT",
        price: float | None = None,
        historical_weights: dict[str, float] | None = None,
    ) -> CouncilDecision:
        usable = [a for a in assessments if a.availability != "DATA_UNAVAILABLE"]
        data_quality = (
            sum(a.data_quality for a in assessments) / max(len(assessments), 1) if assessments else 0.0
        )

        if not usable:
            return self._no_trade(
                assessments,
                symbol=symbol,
                price=price,
                data_quality=data_quality,
                reason="Nenhum especialista com dados disponíveis",
                regime="unknown",
            )

        # Risk specialist veto-ish
        def _name(a: SpecialistAssessment) -> str:
            return a.specialist.value if hasattr(a.specialist, "value") else str(a.specialist)

        risk = next((a for a in usable if _name(a) == SpecialistName.RISK.value), None)
        if risk and risk.bias == Bias.NO_TRADE and risk.confidence >= 0.5:
            return self._no_trade(
                assessments,
                symbol=symbol,
                price=price,
                data_quality=data_quality,
                reason="Risk Specialist recomenda NO_TRADE",
                regime=self._infer_regime(usable),
                extra_risks=risk.risks,
            )

        long_w = short_w = 0.0
        weights_detail: list[dict[str, Any]] = []
        supporting: list[str] = []
        contradictions: list[str] = []

        for a in usable:
            name = a.specialist.value if hasattr(a.specialist, "value") else str(a.specialist)
            prior = (historical_weights or {}).get(name, SPECIALIST_PRIOR.get(name, 0.7))
            independence = 1.0
            # Soft independence penalty if evidence empty
            if not a.evidence:
                independence = 0.5
            w = prior * a.confidence * max(0.2, a.data_quality) * independence
            if a.bias == Bias.LONG:
                long_w += w
            elif a.bias == Bias.SHORT:
                short_w += w
            elif a.bias == Bias.NO_TRADE:
                # Pull toward no trade by reducing net edge
                long_w *= 0.85
                short_w *= 0.85
            weights_detail.append({"specialist": name, "weight": round(w, 4), "bias": a.bias.value})

            for ev in a.evidence[:3]:
                claim = ev.claim if hasattr(ev, "claim") else str(ev)
                if a.bias in {Bias.LONG, Bias.SHORT}:
                    supporting.append(f"[{name}] {claim}")
                else:
                    contradictions.append(f"[{name}] {claim}")

        # Divergence detection
        directional = [a for a in usable if a.bias in {Bias.LONG, Bias.SHORT}]
        has_long = any(a.bias == Bias.LONG for a in directional)
        has_short = any(a.bias == Bias.SHORT for a in directional)
        strong_divergence = has_long and has_short and long_w > 0.2 and short_w > 0.2

        net = long_w - short_w
        total = long_w + short_w
        edge = abs(net) / total if total > 0 else 0.0

        if data_quality < 0.45:
            return self._no_trade(
                assessments,
                symbol=symbol,
                price=price,
                data_quality=data_quality,
                reason="Qualidade de dados insuficiente",
                regime=self._infer_regime(usable),
            )

        if strong_divergence and edge < 0.35:
            return self._no_trade(
                assessments,
                symbol=symbol,
                price=price,
                data_quality=data_quality,
                reason="Conflito entre especialistas sem resolução",
                regime=self._infer_regime(usable),
                contradictions=[
                    f"LONG weight={long_w:.2f} vs SHORT weight={short_w:.2f}",
                    *contradictions[:5],
                ],
            )

        if edge < 0.2 or total < 0.35:
            return self._no_trade(
                assessments,
                symbol=symbol,
                price=price,
                data_quality=data_quality,
                reason="Sem edge claro após agregação ponderada",
                regime=self._infer_regime(usable),
            )

        # Collect invalidation / entry / targets
        invalidation: list[str] = []
        entry: list[str] = []
        targets: list[str] = []
        risk_notes: list[str] = []
        for a in usable:
            invalidation.extend(a.invalidation_conditions[:2])
            risk_notes.extend(a.risks[:2])
            name = a.specialist.value if hasattr(a.specialist, "value") else str(a.specialist)
            if name == SpecialistName.RISK.value:
                rr = a.metrics.get("reward_risk")
                if rr is not None and rr < 1.5:
                    return self._no_trade(
                        assessments,
                        symbol=symbol,
                        price=price,
                        data_quality=data_quality,
                        reason="Relação risco-retorno ruim",
                        regime=self._infer_regime(usable),
                    )
                if rr is not None:
                    targets.append(f"Alvo inicial ≈ ATR*3 (R:R {rr})")
                    entry.append("Entrada condicional após confirmação do timeframe superior")

        if not invalidation:
            return self._no_trade(
                assessments,
                symbol=symbol,
                price=price,
                data_quality=data_quality,
                reason="Invalidação não pôde ser definida",
                regime=self._infer_regime(usable),
            )

        decision = Decision.LONG if net > 0 else Decision.SHORT
        confidence = min(0.85, 0.35 + edge * 0.5)
        if strong_divergence:
            confidence = min(confidence, 0.45)
        if data_quality < 0.7:
            confidence = min(confidence, 0.55)

        regime = self._infer_regime(usable)
        hypothesis = (
            f"Hipótese {decision.value}: edge ponderado={edge:.2f}, "
            f"regime={regime}, qualidade_dados={data_quality:.2f}"
        )

        return CouncilDecision(
            decision=decision,
            confidence=round(confidence, 4),
            market_regime=regime,
            primary_hypothesis=hypothesis,
            supporting_evidence=supporting[:12],
            contradictions=contradictions[:8],
            entry_conditions=entry
            or [
                "Aguardar pullback para região de valor no TF de execução",
                "Confirmar alinhamento com TF superior",
            ],
            invalidation=list(dict.fromkeys(invalidation))[:8],
            targets=targets or ["Alvo 1: 1.5R", "Alvo 2: 3R"],
            risk_notes=list(dict.fromkeys(risk_notes))[:8],
            specialist_votes=assessments,
            data_quality=round(data_quality, 4),
            symbol=symbol,
            price=price,
            timestamp=datetime.now(UTC),
            model_version=self.model_version,
        )

    def _infer_regime(self, assessments: list[SpecialistAssessment]) -> str:
        for a in assessments:
            name = a.specialist.value if hasattr(a.specialist, "value") else str(a.specialist)
            if name == SpecialistName.MACRO_CROSS_ASSET.value:
                return str(a.metrics.get("macro_regime", "unknown"))
            if name == SpecialistName.MARKET_STRUCTURE.value:
                alignment = a.metrics.get("alignment", {})
                if alignment:
                    return f"structure:{alignment.get('1d')}/{alignment.get('4h')}/{alignment.get('1h')}"
        return "unspecified"

    def _no_trade(
        self,
        assessments: list[SpecialistAssessment],
        *,
        symbol: str,
        price: float | None,
        data_quality: float,
        reason: str,
        regime: str,
        contradictions: list[str] | None = None,
        extra_risks: list[str] | None = None,
    ) -> CouncilDecision:
        return CouncilDecision(
            decision=Decision.NO_TRADE,
            confidence=round(min(0.7, 0.4 + (1 - data_quality) * 0.2), 4),
            market_regime=regime,
            primary_hypothesis=f"NO_TRADE: {reason}",
            supporting_evidence=[reason],
            contradictions=contradictions or [],
            entry_conditions=[],
            invalidation=[],
            targets=[],
            risk_notes=(extra_risks or []) + [reason],
            specialist_votes=assessments,
            data_quality=round(data_quality, 4),
            symbol=symbol,
            price=price,
            timestamp=datetime.now(UTC),
            model_version=self.model_version,
        )
