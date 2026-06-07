"""Digest de notícias QUANT no fechamento do candle 1H — só relevantes."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from lib import llmquant_client, news_sources, quant_impact, quant_state

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LOOKBACK_MIN = int(os.environ.get("QUANT_HOURLY_LOOKBACK_MIN", "65"))
MAX_HEADLINES = int(os.environ.get("QUANT_HOURLY_MAX_HEADLINES", "6"))
MIN_RELEVANCE = float(os.environ.get("QUANT_HOURLY_MIN_RELEVANCE", "0.45"))
BRT = timezone(timedelta(hours=-3))


def _enabled() -> bool:
    return os.environ.get("QUANT_HOURLY_NEWS", "true").lower() not in ("0", "false", "no", "off")


def _haiku_hourly_summary(articles: list[dict]) -> str | None:
    if not ANTHROPIC_API_KEY or not articles:
        return None

    import anthropic

    bullets = "\n".join(
        f"- [{a.get('bias', 'NEUTRAL')} {a.get('impact_score', 0):.0%}] {a.get('title', '')}"
        for a in articles[:8]
    )
    prompt = f"""Você é analista crypto. Resuma as notícias RELEVANTES da última hora para a próxima vela 1H.

NOTÍCIAS (já filtradas):
{bullets}

Responda em português, máximo 4 bullets:
• catalisadores reais para BTC/ETH/SOL
• tom (risk-on / risk-off / neutro)
• o que monitorar na hora seguinte
Sem inventar fatos."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning("Haiku hourly summary: %s", exc)
        return None


def _market_lines() -> list[str]:
    lines: list[str] = []
    if not llmquant_client.configured():
        return lines
    for sym in ("BTC-USD", "ETH-USD", "SOL-USD"):
        try:
            snap = llmquant_client.crypto_snapshot(sym)
            if snap:
                lines.append(
                    f"· {sym.replace('-USD', '')}: ${snap.get('price', 0):,.0f} "
                    f"({snap.get('dayChangePercent', 0):+.1f}% 24h)"
                )
        except Exception as exc:
            logger.debug("snapshot %s: %s", sym, exc)
    return lines


def _format_header(now_utc: datetime, count: int) -> str:
    now_brt = now_utc.astimezone(BRT)
    return (
        f"<b>Notícias relevantes 1H</b> ({count})\n"
        f"🕐 candle fechado · {now_utc.strftime('%H:%M')} UTC · "
        f"{now_brt.strftime('%H:%M')} BRT"
    )


def _bias_emoji(bias: str) -> str:
    return {"BULLISH": "🟢", "BEARISH": "🔴"}.get(bias, "⚪")


def build_digest(now_utc: datetime | None = None) -> str | None:
    """Monta digest só com notícias relevantes; None se nada passou no filtro."""
    if not _enabled():
        logger.info("QUANT hourly news desativado (QUANT_HOURLY_NEWS)")
        return None

    now_utc = now_utc or datetime.now(timezone.utc)
    raw = news_sources.fetch_all(max_age_minutes=LOOKBACK_MIN)
    if not raw:
        return None

    relevant = quant_impact.batch_score_relevance(raw, min_score=MIN_RELEVANCE)
    if not relevant:
        logger.info("QUANT hourly: nenhuma notícia relevante (min=%.2f)", MIN_RELEVANCE)
        return None

    picked = relevant[:MAX_HEADLINES]
    lines = [_format_header(now_utc, len(picked)), ""]

    summary = _haiku_hourly_summary(picked)
    if summary:
        lines.append("<b>Resumo</b>")
        lines.append(summary)
        lines.append("")

    lines.append("<b>Relevantes</b>")
    for art in picked:
        title = art.get("title", "").strip()
        source = art.get("source", "?")
        url = art.get("url", "")
        score = art.get("impact_score", 0)
        bias = art.get("bias", "NEUTRAL")
        why = art.get("summary", "")
        tickers = ", ".join(art.get("tickers", []))
        emoji = _bias_emoji(bias)
        head = f"{emoji} <b>{bias}</b> ({score:.0%})"
        if tickers:
            head += f" · {tickers}"
        if url:
            lines.append(f"{head}\n<a href=\"{url}\">{title}</a> <i>({source})</i>")
        else:
            lines.append(f"{head}\n{title} <i>({source})</i>")
        if why:
            lines.append(f"<i>{why}</i>")
        lines.append("")

    market = _market_lines()
    if market:
        lines.append("<b>Mercado</b>")
        lines.extend(market)

    ctx = quant_state.load()
    if ctx.get("headline") and ctx.get("impact_score", 0) >= MIN_RELEVANCE:
        lines.append("")
        lines.append(
            f"<b>Contexto ativo:</b> {ctx.get('global_bias')} "
            f"({ctx.get('impact_score', 0):.0%}) — {ctx.get('summary', '')[:120]}"
        )

    return "\n".join(lines).strip()[:3900]
