"""Markdown and JSON report builder."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.enums import SpecialistName
from app.schemas import CouncilDecision, SpecialistAssessment


def _spec(assessments: list[SpecialistAssessment], name: SpecialistName) -> SpecialistAssessment | None:
    for a in assessments:
        value = a.specialist.value if hasattr(a.specialist, "value") else str(a.specialist)
        if value == name.value:
            return a
    return None


def _evidence_lines(assessment: SpecialistAssessment | None, limit: int = 5) -> list[str]:
    if not assessment:
        return ["DATA_UNAVAILABLE"]
    lines: list[str] = []
    for ev in assessment.evidence[:limit]:
        lines.append(ev.claim if hasattr(ev, "claim") else str(ev))
    return lines or ["(sem evidências)"]


def build_report_json(decision: CouncilDecision) -> dict[str, Any]:
    assessments = decision.specialist_votes
    return {
        "title": "ATLAS BTC ANALYSIS",
        "timestamp": (decision.timestamp or datetime.now(UTC)).isoformat(),
        "price": decision.price,
        "regime": decision.market_regime,
        "data_quality": decision.data_quality,
        "decision": decision.decision.value,
        "confidence": decision.confidence,
        "executive_summary": decision.primary_hypothesis,
        "market_structure": _evidence_lines(_spec(assessments, SpecialistName.MARKET_STRUCTURE)),
        "macro_correlations": _evidence_lines(_spec(assessments, SpecialistName.MACRO_CROSS_ASSET))
        + _evidence_lines(_spec(assessments, SpecialistName.DYNAMIC_CORRELATION)),
        "liquidity_derivatives": _evidence_lines(_spec(assessments, SpecialistName.LIQUIDITY_DERIVATIVES)),
        "news_events": _evidence_lines(_spec(assessments, SpecialistName.NEWS_EVENTS)),
        "similar_cases": _evidence_lines(_spec(assessments, SpecialistName.EXPERIENCE)),
        "supporting_evidence": decision.supporting_evidence,
        "contradictions": decision.contradictions,
        "bull_scenario": [e for e in decision.supporting_evidence if "LONG" in e or "comprador" in e.lower()]
        or ["Continuidade se TF superior permanecer alinhado"],
        "bear_scenario": [e for e in decision.contradictions if "SHORT" in e or "vendedor" in e.lower()]
        or ["Reversão se invalidação for atingida"],
        "range_scenario": ["Consolidação se compressão persistir sem rompimento confirmado"],
        "entry_conditions": decision.entry_conditions,
        "invalidation": decision.invalidation,
        "targets": decision.targets,
        "risk_reward": decision.risk_notes,
        "events_to_monitor": [
            "Mudança de correlação das top relações",
            "Headlines regulatórias / ETF",
            "Romimento com volume no TF de referência",
        ],
        "what_would_change_mind": decision.invalidation
        + decision.contradictions[:3]
        + ["Melhora/deterioração material da qualidade dos dados"],
        "specialists": [a.model_dump(mode="json") for a in assessments],
    }


def build_report_markdown(decision: CouncilDecision) -> str:
    data = build_report_json(decision)
    lines = [
        "# ATLAS BTC ANALYSIS",
        "",
        f"**Timestamp:** {data['timestamp']}",
        f"**Preço:** {data['price']}",
        f"**Regime:** {data['regime']}",
        f"**Qualidade dos dados:** {data['data_quality']:.2f}",
        "",
        f"## Decisão: {data['decision']}",
        f"**Confiança:** {data['confidence']:.2f}",
        "",
        "## Resumo executivo",
        data["executive_summary"],
        "",
        "## Estrutura de mercado",
        *([f"- {x}" for x in data["market_structure"]]),
        "",
        "## Macro e correlações",
        *([f"- {x}" for x in data["macro_correlations"]]),
        "",
        "## Liquidez e derivativos",
        *([f"- {x}" for x in data["liquidity_derivatives"]]),
        "",
        "## Notícias e eventos",
        *([f"- {x}" for x in data["news_events"]]),
        "",
        "## Casos históricos semelhantes",
        *([f"- {x}" for x in data["similar_cases"]]),
        "",
        "## Evidências favoráveis",
        *([f"- {x}" for x in data["supporting_evidence"]] or ["- (nenhuma)"]),
        "",
        "## Evidências contrárias",
        *([f"- {x}" for x in data["contradictions"]] or ["- (nenhuma)"]),
        "",
        "## Cenário comprador",
        *([f"- {x}" for x in data["bull_scenario"]]),
        "",
        "## Cenário vendedor",
        *([f"- {x}" for x in data["bear_scenario"]]),
        "",
        "## Cenário lateral",
        *([f"- {x}" for x in data["range_scenario"]]),
        "",
        "## Entrada condicional",
        *([f"- {x}" for x in data["entry_conditions"]] or ["- N/A (NO TRADE)"]),
        "",
        "## Invalidação",
        *([f"- {x}" for x in data["invalidation"]] or ["- N/A"]),
        "",
        "## Alvos",
        *([f"- {x}" for x in data["targets"]] or ["- N/A"]),
        "",
        "## Risco-retorno",
        *([f"- {x}" for x in data["risk_reward"]] or ["- N/A"]),
        "",
        "## Eventos a monitorar",
        *([f"- {x}" for x in data["events_to_monitor"]]),
        "",
        "## O que faria o ATLAS mudar de opinião",
        *([f"- {x}" for x in data["what_would_change_mind"]]),
        "",
    ]
    return "\n".join(lines)
