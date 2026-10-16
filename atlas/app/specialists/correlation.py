"""Dynamic Correlation and Lead-Lag Specialist."""

from __future__ import annotations

from typing import Any

from app.core.enums import Bias, SpecialistName
from app.core.exceptions import DataUnavailableError
from app.features.correlation import analyze_pair
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist

DEFAULT_MACRO_ASSETS = ["NDX", "SPX", "DXY", "VIX", "WTI", "GOLD", "NVDA", "MSTR", "ETH_USD"]


class DynamicCorrelationSpecialist(BaseSpecialist):
    name = SpecialistName.DYNAMIC_CORRELATION
    model_version = "0.1.0"

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        macro_series: dict[str, list[dict[str, Any]]] = context.get("macro_series", {})
        btc_candles = snapshot.timeframes.get("1d") or snapshot.timeframes.get("4h") or []
        if len(btc_candles) < 40:
            return self.unavailable(snapshot.symbol, "1d", "BTC history too short for correlation")

        btc_closes = [c.close for c in btc_candles]
        pair_reports: list[dict[str, Any]] = []
        evidence: list = []
        risks: list[str] = []
        alternatives: list[str] = []

        if not macro_series:
            return SpecialistAssessment(
                specialist=self.name,
                timestamp=self._now(),
                symbol=snapshot.symbol,
                timeframe="1d",
                bias=Bias.NO_TRADE,
                confidence=0.0,
                data_quality=0.0,
                evidence=[],
                risks=["Nenhuma série macro disponível para correlação"],
                invalidation_conditions=[],
                alternative_hypotheses=["Aguardar coleta cross-asset"],
                metrics={},
                model_version=self.model_version,
                errors=["DATA_UNAVAILABLE: macro_series"],
                availability="DATA_UNAVAILABLE",
            )

        for asset, rows in macro_series.items():
            closes = [float(r["close"]) for r in rows if r.get("close") is not None]
            # Align lengths by truncating to min length (daily approx)
            m = min(len(btc_closes), len(closes))
            report = analyze_pair(asset, btc_closes[-m:], closes[-m:])
            pair_reports.append(report)
            if report.get("availability") != "AVAILABLE":
                continue
            evidence.append(
                self.evidence(
                    f"{asset}: corr_móvel={report['rolling_corr_latest']:.2f}, "
                    f"estado={report['stability']['trend']}, "
                    f"lag={report['lead_lag']['best_lag']}",
                    weight=min(0.9, abs(report["rolling_corr_latest"])),
                    source="correlation",
                    timeframe="1d",
                )
            )
            if report.get("structural_break_hint"):
                risks.append(f"{asset}: possível quebra estrutural na relação com BTC")
            if report["stability"]["trend"] == "inverted":
                alternatives.append(f"Relação BTC–{asset} parece ter invertido de sinal")

        available = [p for p in pair_reports if p.get("availability") == "AVAILABLE"]
        if not available:
            return self.unavailable(snapshot.symbol, "1d", "no overlapping macro series")

        # Rank influencers by abs rolling corr and stability
        ranked = sorted(
            available,
            key=lambda p: (abs(p.get("rolling_corr_latest", 0.0)), p["stability"].get("stable", False)),
            reverse=True,
        )
        top = ranked[0]
        evidence.insert(
            0,
            self.evidence(
                f"Relação mais relevante agora: {top['asset']} "
                f"(corr={top['rolling_corr_latest']:.2f}, {top['stability']['trend']}). "
                f"{top['lead_lag']['interpretation']}",
                weight=0.85,
                source="correlation",
            ),
        )
        evidence.append(
            self.evidence(
                "Precedência temporal não implica causalidade comprovada.",
                weight=0.3,
                source="methodology",
            )
        )

        # Bias: if risk-on leaders (NDX/SPX) strongly correlated and leading up — soft long bias, etc.
        bias = Bias.NEUTRAL
        risk_on = [p for p in available if p["asset"] in {"NDX", "SPX", "NVDA"}]
        dxy = next((p for p in available if p["asset"] == "DXY"), None)
        score = 0.0
        if risk_on:
            mean_corr = sum(p["rolling_corr_latest"] for p in risk_on) / len(risk_on)
            # Without knowing leader return direction in this specialist alone, stay conservative
            if abs(mean_corr) > 0.4:
                alternatives.append(
                    "BTC parece acoplado a risk-on; confirmar direção via Macro Specialist"
                )
                score = mean_corr * 0.2
        if dxy and dxy["rolling_corr_latest"] < -0.3:
            evidence.append(
                self.evidence(
                    f"DXY correlação negativa recente ({dxy['rolling_corr_latest']:.2f})",
                    weight=0.55,
                )
            )

        conf = min(0.7, 0.3 + 0.4 * abs(top["rolling_corr_latest"]))
        if not top["stability"].get("stable"):
            conf = min(conf, 0.4)
            risks.append("relação estatística instável — reduzir confiança")
        conf = self.dampen_confidence(
            conf,
            sample_size=len(btc_closes),
            min_sample=60,
            data_quality=snapshot.data_quality,
            regime_uncertain=bool(top.get("structural_break_hint")),
        )

        if abs(score) < 0.05:
            bias = Bias.NEUTRAL
        elif score > 0:
            bias = Bias.LONG
        else:
            bias = Bias.SHORT

        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe="1d",
            bias=bias,
            confidence=conf,
            data_quality=min(snapshot.data_quality, 0.9 if available else 0.2),
            evidence=evidence,
            risks=risks,
            invalidation_conditions=[
                "Quebra estrutural confirmada nas top-3 relações",
                "Correlação móvel das líderes cai abaixo de |0.15|",
            ],
            alternative_hypotheses=alternatives,
            metrics={
                "pairs": pair_reports,
                "top_influencer": top["asset"],
                "ranking": [p["asset"] for p in ranked[:5]],
            },
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )


async def load_macro_context(provider: Any, assets: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Helper used by analysis service — swallows per-asset failures."""
    assets = assets or DEFAULT_MACRO_ASSETS
    out: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        try:
            out[asset] = await provider.fetch_series(asset, limit=180)
        except DataUnavailableError:
            continue
        except Exception:  # noqa: BLE001
            continue
    return out
