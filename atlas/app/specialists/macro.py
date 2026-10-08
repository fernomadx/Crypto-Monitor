"""Macro and Cross-Asset Specialist."""

from __future__ import annotations

from typing import Any

from app.core.enums import Bias, SpecialistName
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist


def _last_return(rows: list[dict[str, Any]], lookback: int = 5) -> float | None:
    closes = [float(r["close"]) for r in rows if r.get("close") is not None]
    if len(closes) <= lookback:
        return None
    return closes[-1] / closes[-1 - lookback] - 1.0


class MacroCrossAssetSpecialist(BaseSpecialist):
    name = SpecialistName.MACRO_CROSS_ASSET
    model_version = "0.1.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        macro: dict[str, list[dict[str, Any]]] = context.get("macro_series", {})
        corr_metrics: dict[str, Any] = context.get("correlation_metrics", {})

        if not macro:
            return self.unavailable(snapshot.symbol, "1d", "macro series unavailable")

        evidence: list = []
        risks: list[str] = []
        alternatives: list[str] = []
        score = 0.0

        rets: dict[str, float] = {}
        for key, rows in macro.items():
            ret = _last_return(rows, 5)
            if ret is not None:
                rets[key] = ret

        ndx = rets.get("NDX")
        spx = rets.get("SPX")
        dxy = rets.get("DXY")
        vix = rets.get("VIX")
        wti = rets.get("WTI")
        gold = rets.get("GOLD")

        risk_on = False
        risk_off = False
        if ndx is not None and spx is not None:
            if ndx > 0.01 and spx > 0.005:
                risk_on = True
                score += 0.4
                evidence.append(self.evidence("Risk-on: Nasdaq e S&P positivos na janela recente", 0.7))
            elif ndx < -0.01 and spx < -0.005:
                risk_off = True
                score -= 0.4
                evidence.append(self.evidence("Risk-off: Nasdaq e S&P negativos na janela recente", 0.7))

        if dxy is not None:
            if dxy > 0.005:
                score -= 0.25
                evidence.append(self.evidence(f"DXY fortalecendo ({dxy:.2%}) — pressão típica sobre BTC", 0.6))
            elif dxy < -0.005:
                score += 0.2
                evidence.append(self.evidence(f"DXY enfraquecendo ({dxy:.2%})", 0.55))

        if vix is not None:
            if vix > 0.1:
                risk_off = True
                score -= 0.25
                evidence.append(self.evidence(f"VIX em alta ({vix:.2%}) — aversão a risco", 0.65))
            elif vix < -0.1:
                score += 0.15
                evidence.append(self.evidence(f"VIX em queda ({vix:.2%})", 0.5))

        if wti is not None:
            evidence.append(
                self.evidence(
                    f"Petróleo (WTI) retorno recente {wti:.2%} — canal potencial "
                    "inflação→juros→Treasury→DXY→tech→BTC deve ser testado, não assumido",
                    weight=0.45,
                    source="macro",
                )
            )
            # Soft test: if oil up strongly and DXY up, note transmission pressure
            if wti > 0.03 and dxy is not None and dxy > 0:
                alternatives.append(
                    "Petróleo ganhando relevância: alta conjunta com DXY pode transmitir aperto financeiro"
                )
                risks.append("possível transmissão petróleo→inflação implícita→juros")

        if gold is not None and gold > 0.02 and risk_off:
            evidence.append(self.evidence("Ouro firme em contexto risk-off", 0.4))

        # Decoupling detection via correlation context
        top = corr_metrics.get("top_influencer")
        pairs = {p["asset"]: p for p in corr_metrics.get("pairs", []) if p.get("availability") == "AVAILABLE"}
        ndx_pair = pairs.get("NDX")
        if ndx_pair and abs(ndx_pair.get("rolling_corr_latest", 0)) < 0.15:
            alternatives.append("BTC parece desacoplado do Nasdaq na janela móvel recente")
            evidence.append(self.evidence("Desacoplamento BTC–NDX (corr baixa)", 0.6))
        elif ndx_pair and ndx_pair.get("rolling_corr_latest", 0) > 0.4:
            evidence.append(self.evidence("BTC segue Nasdaq na janela móvel atual (associação)", 0.65))

        if top == "WTI":
            alternatives.append("Petróleo aparece como principal associação recente com BTC")
        if top == "DXY" and pairs.get("DXY", {}).get("stability", {}).get("trend") == "weakening":
            alternatives.append("DXY perdeu força explicativa relativa")

        crypto_specific = False
        if risk_on is False and risk_off is False and abs(score) < 0.1:
            crypto_specific = True
            alternatives.append("Movimento parece específico de cripto / sem confirmação macro clara")

        if score > 0.25:
            bias = Bias.LONG
        elif score < -0.25:
            bias = Bias.SHORT
        else:
            bias = Bias.NEUTRAL

        conf = min(0.75, 0.35 + abs(score) * 0.5)
        conf = self.dampen_confidence(
            conf,
            sample_size=len(macro),
            min_sample=3,
            data_quality=snapshot.data_quality,
            regime_uncertain=crypto_specific,
        )

        regime = "risk_on" if risk_on else "risk_off" if risk_off else "mixed_or_crypto_specific"

        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe="1d",
            bias=bias,
            confidence=conf,
            data_quality=min(1.0, 0.5 + 0.1 * len(rets)),
            evidence=evidence,
            risks=risks,
            invalidation_conditions=[
                "Reversão abrupta de NDX/SPX contra a hipótese",
                "Spike de VIX > 20% em 2 sessões",
            ],
            alternative_hypotheses=alternatives,
            metrics={
                "returns_5d": {k: round(v, 5) for k, v in rets.items()},
                "macro_regime": regime,
                "score": round(score, 4),
            },
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
