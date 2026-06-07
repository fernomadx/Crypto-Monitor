"""Integração QUANT → Kronos (contexto de notícia / pesquisa na decisão)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from lib import quant_state

MAX_AGE_HOURS = float(os.environ.get("QUANT_MAX_AGE_HOURS", "4"))
VETO_ENABLED = os.environ.get("QUANT_KRONOS_VETO", "1").strip() not in ("0", "false", "no")
SCORE_INTERVAL = os.environ.get("KRONOS_SCORE_INTERVAL", "4h").strip().lower()


def _side(bias: str) -> int:
    if bias == "BULLISH":
        return 1
    if bias == "BEARISH":
        return -1
    return 0


def _fresh(at_iso: str | None) -> bool:
    if not at_iso:
        return False
    try:
        at = datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - at).total_seconds() / 3600
        return age_h <= MAX_AGE_HOURS
    except (ValueError, TypeError):
        return False


def ticker_context(ticker: str) -> dict | None:
    state = quant_state.load()
    meta = (state.get("tickers") or {}).get(ticker.upper())
    if not meta or not _fresh(meta.get("at")):
        return None
    if float(meta.get("impact_score", 0)) < float(os.environ.get("QUANT_KRONOS_MIN_IMPACT", "0.65")):
        return None
    return meta


def conflicts_with_bias(ticker: str, kronos_bias: str) -> tuple[bool, str]:
    """True se contexto QUANT contradiz viés do Kronos."""
    ctx = ticker_context(ticker)
    if not ctx or not VETO_ENABLED:
        return False, ""

    qb = ctx.get("bias", "NEUTRAL")
    ks = _side(kronos_bias)
    qs = _side(qb)
    if qs == 0 or ks == 0:
        return False, ""

    if ks != qs:
        return True, (
            f"QUANT {qb} ({ctx.get('impact_score', 0):.0%}) contradiz Kronos {kronos_bias}: "
            f"{ctx.get('summary', '')[:120]}"
        )
    return False, ""


def apply_to_results(results_by_interval: dict[str, list[dict]]) -> None:
    """Ajusta tradeable / align_note com contexto QUANT (só score interval 4h por padrão)."""
    for interval, results in results_by_interval.items():
        if interval.lower() != SCORE_INTERVAL:
            continue
        for r in results:
            conflict, note = conflicts_with_bias(r["ticker"], r.get("bias", "NEUTRO"))
            if conflict:
                r["tradeable"] = False
                prev = r.get("align_note") or ""
                r["align_note"] = f"{prev} | {note}".strip(" |")
                r["quant_conflict"] = True
            else:
                ctx = ticker_context(r["ticker"])
                if ctx and _side(ctx.get("bias", "")) == _side(r.get("bias", "")):
                    r["quant_aligned"] = True


def format_kronos_footer() -> str:
    state = quant_state.load()
    lines = ["<b>🧠 Contexto QUANT</b> (notícias / pesquisa)"]

    g_bias = state.get("global_bias", "NEUTRAL")
    g_score = float(state.get("impact_score", 0))
    if g_score >= float(os.environ.get("QUANT_KRONOS_MIN_IMPACT", "0.65")) and state.get("headline"):
        lines.append(
            f"Global: <b>{g_bias}</b> ({g_score:.0%}) — {state.get('summary', '')[:160]}"
        )
    else:
        lines.append("Sem evento de alto impacto nas últimas horas.")

    for ticker in ("BTC", "ETH", "SOL"):
        ctx = ticker_context(ticker)
        if ctx:
            lines.append(
                f"· {ticker}: {ctx.get('bias')} ({ctx.get('impact_score', 0):.0%}) — "
                f"{ctx.get('summary', '')[:80]}"
            )

    if VETO_ENABLED:
        lines.append(
            f"<i>Scorecard {SCORE_INTERVAL.upper()}: veto se QUANT contradiz viés "
            f"(janela {MAX_AGE_HOURS:.0f}h).</i>"
        )
    return "\n".join(lines)
