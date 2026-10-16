"""Experience Specialist — similar historical case matching (structure-based v1)."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.enums import Bias, SpecialistName
from app.features.market_structure import compute_structure_features
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist

FEATURE_KEYS = [
    "position_in_range",
    "atr_pct",
    "realized_vol_20",
    "dist_ema20_pct",
    "impulse_5bar_pct",
    "range_width_pct",
]


class ExperienceSpecialist(BaseSpecialist):
    name = SpecialistName.EXPERIENCE
    model_version = "0.1.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        candles = snapshot.timeframes.get("1h") or snapshot.timeframes.get("4h") or []
        if len(candles) < 80:
            return self.unavailable(snapshot.symbol, "1h", "insufficient history for similarity")

        current = compute_structure_features(candles)
        if current.get("insufficient"):
            return self.unavailable(snapshot.symbol, "1h", "structure features insufficient")

        # Walk historical windows without look-ahead within the provided series
        cases: list[dict[str, Any]] = []
        closes = [c.close for c in candles]
        window = 60
        horizon = 12  # bars ahead for outcome within known history for past points
        cur_vec = np.array([float(current.get(k, 0.0)) for k in FEATURE_KEYS], dtype=float)

        for end in range(window, len(candles) - horizon, 5):
            past_slice = candles[:end]
            feat = compute_structure_features(past_slice)
            if feat.get("insufficient"):
                continue
            vec = np.array([float(feat.get(k, 0.0)) for k in FEATURE_KEYS], dtype=float)
            denom = np.linalg.norm(cur_vec) * np.linalg.norm(vec)
            if denom == 0:
                continue
            sim = float(np.dot(cur_vec, vec) / denom)
            # Regime / trend match bonus
            if feat.get("trend") == current.get("trend"):
                sim += 0.05
            if feat.get("regime") == current.get("regime"):
                sim += 0.05
            future_ret = closes[end + horizon - 1] / closes[end - 1] - 1.0
            cases.append(
                {
                    "index_end": end,
                    "similarity": round(min(1.0, sim), 4),
                    "trend": feat.get("trend"),
                    "regime": feat.get("regime"),
                    "forward_return_12bars": round(future_ret, 5),
                    "differences": [
                        k
                        for k in FEATURE_KEYS
                        if abs(float(feat.get(k, 0)) - float(current.get(k, 0))) > 2.0
                    ],
                }
            )

        cases.sort(key=lambda c: c["similarity"], reverse=True)
        top = cases[:5]
        if not top:
            return self.unavailable(snapshot.symbol, "1h", "no comparable cases")

        avg_fwd = float(np.mean([c["forward_return_12bars"] for c in top]))
        evidence = [
            self.evidence(
                f"Caso similar #{i + 1}: sim={c['similarity']:.2f}, "
                f"regime={c['regime']}, retorno_posterior_12barras={c['forward_return_12bars']:.2%}",
                weight=c["similarity"],
                source="experience",
                timeframe="1h",
            )
            for i, c in enumerate(top)
        ]
        evidence.append(
            self.evidence(
                "Similaridade estrutural ≠ garantia de repetição; diferenças de macro/funding podem dominar.",
                weight=0.4,
                source="methodology",
            )
        )

        if avg_fwd > 0.01:
            bias = Bias.LONG
        elif avg_fwd < -0.01:
            bias = Bias.SHORT
        else:
            bias = Bias.NEUTRAL

        conf = self.dampen_confidence(
            min(0.6, top[0]["similarity"] * 0.7),
            sample_size=len(top),
            min_sample=3,
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
            risks=["Amostra de casos baseada apenas em estrutura local (v0.1)"],
            invalidation_conditions=["Regime corrente diverge dos top cases"],
            alternative_hypotheses=[
                "Casos semelhantes tiveram outcomes mistos — edge fraco",
            ]
            if abs(avg_fwd) < 0.01
            else [],
            metrics={
                "similar_cases": top,
                "avg_forward_return": round(avg_fwd, 5),
                "limitations": [
                    "Sem funding/OI/news embedding nesta versão",
                    "Janela limitada ao histórico do snapshot",
                ],
            },
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
