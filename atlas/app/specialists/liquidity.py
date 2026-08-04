"""Liquidity and Derivatives Specialist — OKX public funding/OI/basis/liqs."""

from __future__ import annotations

from typing import Any

from app.core.enums import Bias, SpecialistName
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist


class LiquidityDerivativesSpecialist(BaseSpecialist):
    name = SpecialistName.LIQUIDITY_DERIVATIVES
    model_version = "0.2.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        derivatives = context.get("derivatives")

        if not derivatives:
            assessment = self.unavailable(
                snapshot.symbol,
                "1h",
                "funding/OI/liquidations/basis not available",
            )
            assessment.metrics = {
                "expected_fields": [
                    "funding",
                    "open_interest",
                    "oi_change",
                    "liquidations",
                    "basis",
                    "spot_volume",
                    "futures_volume",
                ],
                "status": "DATA_UNAVAILABLE",
            }
            assessment.alternative_hypotheses = [
                "Distinguir compra spot vs short squeeze vs deleveraging quando dados existirem",
            ]
            return assessment

        evidence: list = []
        risks: list[str] = []
        alternatives: list[str] = []
        score = 0.0
        regime_label = "balanced"

        funding = derivatives.get("funding")
        oi = derivatives.get("open_interest")
        oi_change = derivatives.get("oi_change")
        basis_bps = derivatives.get("basis_bps")
        liqs = derivatives.get("liquidations") or []
        mark = derivatives.get("mark_price")
        index = derivatives.get("index_price")

        if funding is not None:
            evidence.append(
                self.evidence(
                    f"Funding atual={funding:.6f}"
                    + (
                        f" (média hist={derivatives.get('funding_mean_hist'):.6f})"
                        if derivatives.get("funding_mean_hist") is not None
                        else ""
                    ),
                    weight=0.7,
                    source="derivatives",
                )
            )
            if funding > 0.0005:
                score -= 0.25
                risks.append("Funding elevado — longs pagam; risco de long liquidation / squeeze")
                regime_label = "crowded_long"
            elif funding < -0.0005:
                score += 0.25
                evidence.append(
                    self.evidence("Funding negativo — shorts pagam; possível short squeeze", 0.65)
                )
                regime_label = "crowded_short"
            else:
                evidence.append(self.evidence("Funding neutro — sem crowding extremo", 0.45))

        if oi is not None:
            evidence.append(
                self.evidence(
                    f"Open interest={oi:.2f}"
                    + (
                        f" (~${derivatives.get('open_interest_usd'):,.0f})"
                        if derivatives.get("open_interest_usd")
                        else ""
                    ),
                    weight=0.55,
                    source="derivatives",
                )
            )

        # Price vs OI heuristics when oi_change known
        price_up = False
        if snapshot.timeframes.get("1h") and len(snapshot.timeframes["1h"]) >= 2:
            c0 = snapshot.timeframes["1h"][-2].close
            c1 = snapshot.timeframes["1h"][-1].close
            price_up = c1 > c0

        if oi_change is not None:
            if price_up and oi_change > 0:
                score += 0.15
                evidence.append(
                    self.evidence(
                        "Preço↑ + OI↑ — expansão de alavancagem (não prova compra spot)",
                        0.6,
                    )
                )
                alternatives.append("Pode ser abertura de longs alavancados")
            elif price_up and oi_change < 0:
                score += 0.05
                evidence.append(
                    self.evidence(
                        "Preço↑ + OI↓ — possível short cover / short squeeze",
                        0.65,
                    )
                )
                regime_label = "short_cover"
            elif (not price_up) and oi_change < 0:
                score -= 0.1
                evidence.append(
                    self.evidence("Preço↓ + OI↓ — deleveraging / fechamento de posições", 0.6)
                )
                regime_label = "deleveraging"
            elif (not price_up) and oi_change > 0:
                score -= 0.15
                evidence.append(
                    self.evidence("Preço↓ + OI↑ — possível aumento de shorts", 0.6)
                )
        else:
            alternatives.append("oi_change indisponível nesta coleta — sem inferência preço×OI")

        if basis_bps is not None:
            evidence.append(
                self.evidence(
                    f"Basis futures-spot ≈ {basis_bps:.1f} bps "
                    f"(mark={mark}, index={index})",
                    weight=0.5,
                    source="derivatives",
                )
            )
            if basis_bps > 15:
                risks.append("Basis positivo elevado — futures caros vs spot")
            elif basis_bps < -15:
                risks.append("Basis negativo — futures com desconto vs spot")

        long_liqs = sum(1 for x in liqs if x.get("pos_side") == "long" or x.get("side") == "sell")
        short_liqs = sum(1 for x in liqs if x.get("pos_side") == "short" or x.get("side") == "buy")
        if liqs:
            evidence.append(
                self.evidence(
                    f"Liquidações recentes: n={len(liqs)} (long_side≈{long_liqs}, short_side≈{short_liqs})",
                    weight=0.55,
                    source="derivatives",
                )
            )
            if long_liqs > short_liqs * 1.5 and long_liqs >= 3:
                score -= 0.1
                risks.append("Concentração de liquidações de long — cascata possível")
            elif short_liqs > long_liqs * 1.5 and short_liqs >= 3:
                score += 0.1
                alternatives.append("Pressão de short liquidation pode amplificar alta")

        evidence.append(
            self.evidence(
                "Derivativos explicam posicionamento/alavancagem; não causam preço por si só.",
                weight=0.3,
                source="methodology",
            )
        )

        if score > 0.2:
            bias = Bias.LONG
        elif score < -0.2:
            bias = Bias.SHORT
        else:
            bias = Bias.NEUTRAL

        dq = 0.85 if derivatives.get("availability") == "AVAILABLE" else 0.65
        if derivatives.get("errors"):
            dq = min(dq, 0.7)
            risks.extend([f"parcial: {e}" for e in derivatives["errors"][:3]])

        conf = self.dampen_confidence(
            min(0.75, 0.4 + abs(score)),
            sample_size=1 if funding is not None else 0,
            min_sample=1,
            data_quality=dq,
            regime_uncertain=oi_change is None,
        )

        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe="1h",
            bias=bias,
            confidence=conf,
            data_quality=dq,
            evidence=evidence,
            risks=risks,
            invalidation_conditions=[
                "Funding inverte sinal com magnitude > 0.0005",
                "Basis cruza 0 com aceleração de OI contra a hipótese",
            ],
            alternative_hypotheses=alternatives,
            metrics={
                **derivatives,
                "score": round(score, 4),
                "positioning_regime": regime_label,
            },
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
