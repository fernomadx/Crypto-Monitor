"""Market Structure Specialist — multi-timeframe BTC structure."""

from __future__ import annotations

from typing import Any

from app.core.enums import Bias, SpecialistName
from app.features.market_structure import compute_structure_features
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist


class MarketStructureSpecialist(BaseSpecialist):
    name = SpecialistName.MARKET_STRUCTURE
    model_version = "0.1.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        preferred = ["1d", "4h", "1h", "15m", "5m", "1w"]
        features_by_tf: dict[str, dict[str, Any]] = {}
        for tf in preferred:
            candles = snapshot.timeframes.get(tf)
            if candles:
                features_by_tf[tf] = compute_structure_features(candles)

        if not features_by_tf:
            return self.unavailable(snapshot.symbol, "1h", "no OHLCV timeframes in snapshot")

        evidence: list = []
        risks: list[str] = []
        invalidation: list[str] = []
        alternatives: list[str] = []
        scores: list[float] = []

        for tf, feat in features_by_tf.items():
            if feat.get("insufficient"):
                risks.append(f"{tf}: amostra insuficiente ({feat.get('sample_size', 0)})")
                continue
            trend = feat["trend"]
            claim = (
                f"{tf}: tendência={trend}, regime={feat['regime']}, "
                f"posição_range={feat['position_in_range']:.2f}, "
                f"ATR%={feat['atr_pct']:.2f}"
            )
            weight = 0.7 if tf in {"1d", "4h"} else 0.5
            evidence.append(self.evidence(claim, weight=weight, source="structure", timeframe=tf))

            if trend == "uptrend":
                scores.append(1.0 if tf in {"1d", "4h"} else 0.6)
            elif trend == "downtrend":
                scores.append(-1.0 if tf in {"1d", "4h"} else -0.6)
            else:
                scores.append(0.0)

            if feat.get("false_breakout_risk"):
                risks.append(f"{tf}: risco de falso rompimento (volume não confirma)")
            if feat.get("breakout_up"):
                evidence.append(
                    self.evidence(
                        f"{tf}: rompimento de máxima do range"
                        + (" com volume" if feat.get("volume_confirmation") else " sem confirmação de volume"),
                        weight=0.6,
                        timeframe=tf,
                    )
                )
            if feat.get("breakout_down"):
                evidence.append(
                    self.evidence(
                        f"{tf}: rompimento de mínima do range"
                        + (" com volume" if feat.get("volume_confirmation") else " sem confirmação de volume"),
                        weight=0.6,
                        timeframe=tf,
                    )
                )
            if feat.get("compression"):
                alternatives.append(f"{tf}: compressão — expansão iminente possível em ambas direções")
            if abs(feat.get("dist_ema20_pct", 0.0)) > 3:
                risks.append(f"{tf}: preço estendido vs EMA20 ({feat['dist_ema20_pct']:.2f}%)")

        # Alignment across timeframes
        daily: dict[str, Any] = features_by_tf.get("1d") or {}
        h4: dict[str, Any] = features_by_tf.get("4h") or {}
        h1: dict[str, Any] = features_by_tf.get("1h") or {}
        m15: dict[str, Any] = features_by_tf.get("15m") or {}

        if daily.get("trend") == "uptrend" and h4.get("trend") == "range":
            evidence.append(
                self.evidence("1D permanece comprador; 4H em consolidação", weight=0.75, timeframe="multi")
            )
        if h1.get("breakout_up") and not h1.get("volume_confirmation"):
            evidence.append(
                self.evidence(
                    "1H rompeu resistência sem confirmação de volume",
                    weight=0.65,
                    timeframe="1h",
                )
            )
            risks.append("risco de falso rompimento elevado no 1H")
        if m15.get("dist_ema20_pct", 0) > 2:
            risks.append("15m estendido — pullback provável antes de continuação")

        # Invalidation regions from higher TF structure
        for tf in ("1d", "4h", "1h"):
            tf_feat = features_by_tf.get(tf)
            if not tf_feat or tf_feat.get("insufficient"):
                continue
            if tf_feat["trend"] == "uptrend":
                invalidation.append(f"Fechamento abaixo de {tf_feat['range_low']:.2f} no {tf}")
            elif tf_feat["trend"] == "downtrend":
                invalidation.append(f"Fechamento acima de {tf_feat['range_high']:.2f} no {tf}")
            else:
                invalidation.append(
                    f"Saída do range [{tf_feat['range_low']:.2f}, {tf_feat['range_high']:.2f}] no {tf} sem follow-through"
                )

        avg_score = sum(scores) / max(len(scores), 1)
        if abs(avg_score) < 0.25:
            bias = Bias.NEUTRAL
            conf = 0.35
            alternatives.append("Mercado sem alinhamento claro entre timeframes — preferir NO_TRADE no Council")
        elif avg_score > 0:
            bias = Bias.LONG
            conf = min(0.85, 0.45 + abs(avg_score) * 0.35)
        else:
            bias = Bias.SHORT
            conf = min(0.85, 0.45 + abs(avg_score) * 0.35)

        regime_uncertain = any(f.get("regime") == "uncertain" or f.get("trend") == "transition" for f in features_by_tf.values())
        sample = min((f.get("sample_size", 0) for f in features_by_tf.values()), default=0)
        conf = self.dampen_confidence(
            conf,
            sample_size=sample,
            min_sample=50,
            data_quality=snapshot.data_quality,
            regime_uncertain=regime_uncertain,
        )

        if not invalidation:
            risks.append("invalidação não pôde ser definida com precisão")
            conf = min(conf, 0.4)

        primary_tf = "1h" if "1h" in features_by_tf else next(iter(features_by_tf))
        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe=primary_tf,
            bias=bias,
            confidence=conf,
            data_quality=snapshot.data_quality,
            evidence=evidence,
            risks=risks,
            invalidation_conditions=invalidation,
            alternative_hypotheses=alternatives,
            metrics={
                "score": round(avg_score, 4),
                "features_by_tf": {k: v for k, v in features_by_tf.items()},
                "alignment": {
                    "1d": daily.get("trend"),
                    "4h": h4.get("trend"),
                    "1h": h1.get("trend"),
                    "15m": m15.get("trend"),
                },
            },
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
