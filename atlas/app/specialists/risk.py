"""Risk Specialist — risk/reward and invalidation quality."""

from __future__ import annotations

from typing import Any

from app.core.enums import Bias, SpecialistName
from app.features.market_structure import compute_structure_features
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist


class RiskSpecialist(BaseSpecialist):
    name = SpecialistName.RISK
    model_version = "0.1.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        candles = snapshot.timeframes.get("1h") or snapshot.timeframes.get("4h")
        if not candles:
            return self.unavailable(snapshot.symbol, "1h", "no candles for risk")

        feat = compute_structure_features(candles)
        if feat.get("insufficient"):
            return self.unavailable(snapshot.symbol, "1h", "insufficient for ATR/risk")

        atr = float(feat["atr14"])
        price = float(feat["last_price"])
        stop_distance = atr * 1.5
        target_distance = atr * 3.0
        rr = target_distance / stop_distance if stop_distance else 0.0

        evidence = [
            self.evidence(
                f"ATR14={atr:.2f} ({feat['atr_pct']:.2f}%); stop≈{stop_distance:.2f}; alvo≈{target_distance:.2f}; R:R≈{rr:.2f}",
                weight=0.8,
                source="risk",
                timeframe="1h",
            )
        ]
        risks: list[str] = []
        if feat.get("false_breakout_risk"):
            risks.append("Setup com risco elevado de falso rompimento")
        if feat.get("compression"):
            risks.append("Compressão: stop curto pode ser stopado por expansão")
        if snapshot.data_quality < 0.6:
            risks.append("Qualidade de dados baixa — não dimensionar risco normalmente")

        # Risk specialist often votes NO_TRADE when RR poor or uncertainty high
        if rr < 1.5 or snapshot.data_quality < 0.5 or feat.get("regime") in {"uncertain", "compression"}:
            bias = Bias.NO_TRADE
            conf = 0.55
            evidence.append(self.evidence("Condições de risco desfavoráveis — preferir NO_TRADE", 0.75))
        else:
            bias = Bias.NEUTRAL
            conf = 0.45

        conf = self.dampen_confidence(
            conf,
            sample_size=int(feat.get("sample_size", 0)),
            min_sample=50,
            data_quality=snapshot.data_quality,
        )

        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe="1h",
            bias=bias,
            confidence=conf,
            data_quality=snapshot.data_quality,
            evidence=evidence,
            risks=risks,
            invalidation_conditions=[
                f"Preço além de {stop_distance:.2f} do ponto de entrada condicional",
            ],
            alternative_hypotheses=["Aguardar compressão resolver com direção clara"],
            metrics={
                "atr": atr,
                "price": price,
                "stop_distance": stop_distance,
                "target_distance": target_distance,
                "reward_risk": round(rr, 3),
            },
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
