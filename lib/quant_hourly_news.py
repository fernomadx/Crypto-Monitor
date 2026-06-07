"""Digest de notícias QUANT no fechamento do candle 1H."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from lib import llmquant_client, news_sources, quant_state

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LOOKBACK_MIN = int(os.environ.get("QUANT_HOURLY_LOOKBACK_MIN", "65"))
MAX_HEADLINES = int(os.environ.get("QUANT_HOURLY_MAX_HEADLINES", "8"))
BRT = timezone(timedelta(hours=-3))


def _enabled() -> bool:
    return os.environ.get("QUANT_HOURLY_NEWS", "true").lower() not in ("0", "false", "no", "off")


def _haiku_hourly_summary(headlines: list[str]) -> str | None:
    if not ANTHROPIC_API_KEY or not headlines:
        return None

    import anthropic

    bullets = "\n".join(f"- {h}" for h in headlines[:12])
    prompt = f"""Você é analista crypto. Resuma as manchetes da última hora para trading 1H.

MANCHETES:
{bullets}

Responda em português, máximo 5 bullets curtos:
• impacto provável em BTC/ETH/SOL
• tom geral (risk-on / risk-off / neutro)
• destaque só o que importa para a próxima hora
Sem inventar fatos fora das manchetes."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
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


def _format_header(now_utc: datetime) -> str:
    now_brt = now_utc.astimezone(BRT)
    return (
        f"<b>Notícias 1H</b> — candle fechado\n"
        f"🕐 {now_utc.strftime('%H:%M')} UTC · "
        f"{now_brt.strftime('%H:%M')} BRT"
    )


def build_digest(now_utc: datetime | None = None) -> str | None:
    """Monta texto HTML do digest; None se desativado ou sem notícias."""
    if not _enabled():
        logger.info("QUANT hourly news desativado (QUANT_HOURLY_NEWS)")
        return None

    now_utc = now_utc or datetime.now(timezone.utc)
    articles = news_sources.fetch_all(max_age_minutes=LOOKBACK_MIN)
    if not articles:
        return None

    lines = [_format_header(now_utc), ""]
    titles = [a.get("title", "").strip() for a in articles if a.get("title")]
    summary = _haiku_hourly_summary(titles)
    if summary:
        lines.append("<b>Resumo</b>")
        lines.append(summary)
        lines.append("")

    lines.append(f"<b>Manchetes ({min(len(articles), MAX_HEADLINES)})</b>")
    for art in articles[:MAX_HEADLINES]:
        title = art.get("title", "").strip()
        source = art.get("source", "?")
        url = art.get("url", "")
        if url:
            lines.append(f"• <a href=\"{url}\">{title}</a> <i>({source})</i>")
        else:
            lines.append(f"• {title} <i>({source})</i>")

    market = _market_lines()
    if market:
        lines.append("")
        lines.append("<b>Mercado LLMQuant</b>")
        lines.extend(market)

    ctx = quant_state.load()
    if ctx.get("headline") and ctx.get("impact_score", 0) >= 0.5:
        lines.append("")
        lines.append(
            f"<b>Contexto ativo:</b> {ctx.get('global_bias')} "
            f"({ctx.get('impact_score', 0):.0%}) — {ctx.get('summary', '')[:120]}"
        )

    return "\n".join(lines)[:3900]
