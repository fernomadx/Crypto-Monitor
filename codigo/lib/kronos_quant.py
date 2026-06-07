"""Integração QUANT → Kronos (contexto de notícia / pesquisa na decisão)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from lib import quant_state

MAX_AGE_HOURS = float(os.environ.get("QUANT_MAX_AGE_HOURS", "4"))
SCORE_INTERVAL = os.environ.get("KRONOS_SCORE_INTERVAL", "4h").strip().lower()


def _kronos_mode() -> str:
    """
    warn — só aviso no alerta Kronos (bom para testar)
    veto — bloqueia scorecard 4H se contradiz
    off  — não altera tradeable (footer mínimo)
    """
    mode = os.environ.get("QUANT_KRONOS_MODE", "").strip().lower()
    if mode in ("warn", "veto", "off"):
        return mode
    # legado QUANT_KRONOS_VETO=0/1
    if os.environ.get("QUANT_KRONOS_VETO", "1").strip() in ("0", "false", "no"):
        return "warn"
    return "veto"


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


def conflict_note(ticker: str, kronos_bias: str) -> str:
    """Nota se contexto QUANT contradiz viés do Kronos (vazio se ok)."""
    ctx = ticker_context(ticker)
    if not ctx or _kronos_mode() == "off":
        return ""

    qb = ctx.get("bias", "NEUTRAL")
    ks = _side(kronos_bias)
    qs = _side(qb)
    if qs == 0 or ks == 0 or ks == qs:
        return ""

    return (
        f"QUANT {qb} ({ctx.get('impact_score', 0):.0%}) contradiz Kronos {kronos_bias}: "
        f"{ctx.get('summary', '')[:120]}"
    )


def apply_to_results(results_by_interval: dict[str, list[dict]]) -> None:
    """Ajusta tradeable / align_note com contexto QUANT (só score interval 4h por padrão)."""
    for interval, results in results_by_interval.items():
        if interval.lower() != SCORE_INTERVAL:
            continue
        for r in results:
            note = conflict_note(r["ticker"], r.get("bias", "NEUTRO"))
            if note:
                prev = r.get("align_note") or ""
                r["align_note"] = f"{prev} | ⚠️ {note}".strip(" |")
                r["quant_conflict"] = True
                if _kronos_mode() == "veto":
                    r["tradeable"] = False
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

    mode = _kronos_mode()
    if mode == "veto":
        lines.append(
            f"<i>Modo veto — scorecard {SCORE_INTERVAL.upper()} bloqueado se QUANT contradiz "
            f"(janela {MAX_AGE_HOURS:.0f}h).</i>"
        )
    elif mode == "warn":
        lines.append(
            f"<i>Modo teste (warn) — só aviso, não bloqueia scorecard.</i>"
        )
    return "\n".join(lines)
