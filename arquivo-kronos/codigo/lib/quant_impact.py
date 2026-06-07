"""Detecção de notícias de impacto + atualização do estado QUANT."""

from __future__ import annotations

import json
import logging
import os
import re

from lib import news_sources, quant_state

logger = logging.getLogger(__name__)

IMPACT_THRESHOLD = float(os.environ.get("QUANT_IMPACT_THRESHOLD", "0.70"))
HOURLY_MIN_RELEVANCE = float(os.environ.get("QUANT_HOURLY_MIN_RELEVANCE", "0.45"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Pré-filtro rápido (evita Haiku em fluff óbvio)
_RELEVANCE_HINTS = re.compile(
    r"\b(btc|bitcoin|eth|ethereum|sol|solana|crypto|defi|etf|sec|cftc|fed|fomc|"
    r"rate|cpi|inflation|hack|exploit|liquidat|bankrupt|approval|ban|regulat|"
    r"sanction|tariff|war|inflow|outflow|whale|funding|stablecoin|tether|binance|"
    r"coinbase|blackrock|microstrategy|halving|mining|sec\s|lawsuit|settlement)\b",
    re.I,
)
_NOISE_HINTS = re.compile(
    r"\b(podcast|opinion|sponsored|nft\s+art|celebrity|meme\s+coin\s+launch|"
    r"giveaway|airdrop\s+scam|price\s+prediction\s+202[0-9])\b",
    re.I,
)


def impact_alerts_enabled() -> bool:
    """QUANT_IMPACT_ALERTS=0 — só atualiza estado; alertas vão no digest 1H."""
    return os.environ.get("QUANT_IMPACT_ALERTS", "true").lower() not in ("0", "false", "no", "off")


def _impact_alerts_enabled() -> bool:
    return impact_alerts_enabled()

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


def _parse_json_array(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().rstrip("`")
    data = json.loads(text)
    return data if isinstance(data, list) else []


def keyword_relevant(title: str) -> bool:
    """Pré-filtro barato antes do Haiku."""
    if not title or len(title) < 12:
        return False
    if _NOISE_HINTS.search(title):
        return False
    return bool(_RELEVANCE_HINTS.search(title))


def score_article(title: str) -> dict | None:
    """Score de uma manchete (sem threshold)."""
    if not ANTHROPIC_API_KEY:
        return None

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Analise relevância desta manchete para trading crypto curto prazo (1H).

Manchete: "{title}"

Responda APENAS JSON:
{{
  "impact_score": <0.0 a 1.0 — 0=irrelevante/fluff, 1=choque>,
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "summary": "<1 frase em português>",
  "tickers": ["BTC", "ETH", "SOL" ...]
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
        tickers = data.get("tickers") or detect_tickers(title)
        return {
            "impact_score": score,
            "bias": data.get("bias", "NEUTRAL"),
            "summary": data.get("summary", ""),
            "tickers": [str(t).upper() for t in tickers],
        }
    except Exception as exc:
        logger.error("score_article falhou: %s", exc)
        return None


def batch_score_relevance(articles: list[dict], min_score: float) -> list[dict]:
    """Rankeia manchetes em 1 chamada Haiku; retorna artigos enriquecidos."""
    candidates = [a for a in articles if keyword_relevant(a.get("title", ""))]
    if not candidates:
        return []

    if not ANTHROPIC_API_KEY:
        return [{**a, "impact_score": 0.5, "bias": "NEUTRAL", "summary": ""} for a in candidates[:8]]

    import anthropic

    lines = "\n".join(f'{i}: {a.get("title", "")[:200]}' for i, a in enumerate(candidates[:20]))
    prompt = f"""Você filtra notícias RELEVANTES para trading crypto 1H (BTC/ETH/SOL).

Ignore: fluff, opinião vazia, NFT arte, podcasts, previsões longo prazo sem catalisador.

Para cada índice, score 0.0–1.0 de relevância/impacto de mercado.

MANCHETES:
{lines}

Responda APENAS JSON array (só índices com score >= {min_score}):
[{{"i": 0, "impact_score": 0.7, "bias": "BULLISH", "summary": "frase PT", "tickers": ["BTC"]}}]
"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        ranked = _parse_json_array(msg.content[0].text.strip())
        out: list[dict] = []
        for row in ranked:
            idx = int(row.get("i", -1))
            score = float(row.get("impact_score", 0))
            if idx < 0 or idx >= len(candidates) or score < min_score:
                continue
            art = dict(candidates[idx])
            art["impact_score"] = score
            art["bias"] = row.get("bias", "NEUTRAL")
            art["summary"] = row.get("summary", "")
            art["tickers"] = [str(t).upper() for t in (row.get("tickers") or detect_tickers(art.get("title", "")))]
            out.append(art)
        out.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        return out
    except Exception as exc:
        logger.error("batch_score_relevance falhou: %s", exc)
        return []


def analyze_impact(title: str, url: str = "") -> dict | None:
    """Retorna dict com bias, score, summary ou None se baixo impacto."""
    scored = score_article(title)
    if not scored or scored["impact_score"] < IMPACT_THRESHOLD:
        return None
    return scored


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
