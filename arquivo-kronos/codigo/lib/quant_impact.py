"""Detecção de notícias de impacto + atualização do estado QUANT."""

from __future__ import annotations

import json
import logging
import os
import re

from lib import news_sources, quant_state

logger = logging.getLogger(__name__)

IMPACT_THRESHOLD = float(os.environ.get("QUANT_IMPACT_THRESHOLD", "0.65"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

TICKER_PATTERNS = {
    "BTC": re.compile(r"\b(btc|bitcoin)\b", re.I),
    "ETH": re.compile(r"\b(eth|ethereum)\b", re.I),
    "SOL": re.compile(r"\b(sol|solana)\b", re.I),
}


def detect_tickers(text: str) -> list[str]:
    found = []
    for ticker, pat in TICKER_PATTERNS.items():
        if pat.search(text):
            found.append(ticker)
    return found or ["BTC"]


def analyze_impact(title: str, url: str = "") -> dict | None:
    """Retorna dict com bias, score, summary ou None se baixo impacto."""
    if not ANTHROPIC_API_KEY:
        return None

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Analise o impacto desta manchete crypto para trading de curto prazo (1H–4H).

Manchete: "{title}"

Responda APENAS JSON:
{{
  "impact_score": <0.0 a 1.0 — 0=irrelevante, 1=choque de mercado>,
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "summary": "<1 frase em português sobre impacto>",
  "tickers": ["BTC", "ETH", "SOL" ... afetados]
}}
"""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(msg.content[0].text.strip())
        score = float(data.get("impact_score", 0))
        if score < IMPACT_THRESHOLD:
            return None
        tickers = data.get("tickers") or detect_tickers(title)
        return {
            "impact_score": score,
            "bias": data.get("bias", "NEUTRAL"),
            "summary": data.get("summary", ""),
            "tickers": [str(t).upper() for t in tickers],
        }
    except Exception as exc:
        logger.error("analyze_impact falhou: %s", exc)
        return None


def scan_new_impacts(max_age_minutes: int | None = None) -> list[dict]:
    """Varre notícias; retorna alertas novos (não vistos)."""
    age = max_age_minutes or int(os.environ.get("QUANT_POLL_MINUTES", "10")) + 2
    articles = news_sources.fetch_all(max_age_minutes=age)
    state = quant_state.load()
    alerts: list[dict] = []

    for article in articles:
        url = article.get("url") or ""
        title = article.get("title") or ""
        if not title or quant_state.url_seen(state, url):
            continue

        impact = analyze_impact(title, url)
        quant_state.remember_url(state, url)

        if not impact:
            continue

        alert = {
            "title": title,
            "url": url,
            "source": article.get("source"),
            **impact,
        }
        alerts.append(alert)

        for ticker in impact["tickers"]:
            quant_state.set_ticker_impact(
                state,
                ticker,
                bias=impact["bias"],
                impact_score=impact["impact_score"],
                headline=title,
                summary=impact["summary"],
                url=url,
            )

    if articles or alerts:
        try:
            quant_state.save(state)
        except OSError as exc:
            logger.warning("Não gravou quant_state: %s", exc)

    return alerts
