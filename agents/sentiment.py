"""
agents/sentiment.py — News intake + análise de sentimento em duas camadas.

Cadência: a cada 10 min (via supercronic).

Pipeline:
    1. Busca artigos recentes de todas as fontes (lib/news_sources.py)
    2. Camada 1 — VADER: roda em 100% dos artigos. Grátis, local, instantâneo.
    3. Filtra artigos com |compound| > VADER_THRESHOLD (~top 5%)
    4. Camada 2 — Claude Haiku: analisa apenas os filtrados. Custo ~$0.001/artigo.
    5. Salva tudo no DB. Alerta se sentimento extremo detectado.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from lib import db, news_sources, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VADER_THRESHOLD = float(os.environ.get("VADER_THRESHOLD", "0.5"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

vader = SentimentIntensityAnalyzer()


def analyze_with_vader(title: str) -> float:
    """Retorna compound score entre -1 e 1."""
    scores = vader.polarity_scores(title)
    return scores["compound"]


def analyze_with_haiku(title: str, url: str) -> tuple[float, str]:
    """
    Retorna (score normalizado -1..1, resumo em português).
    Score: -1 extremamente bearish, 0 neutro, 1 extremamente bullish.
    Só chamado se |vader_score| > VADER_THRESHOLD.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY não configurado, pulando Haiku")
        return (0.0, "")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Você é um analista de mercado crypto sênior.

Analise esta manchete de notícia:
"{title}"

Responda APENAS no formato JSON abaixo, sem texto extra:
{{
  "score": <float entre -1.0 (extremamente bearish) e 1.0 (extremamente bullish)>,
  "summary": "<resumo em português de 1 frase explicando o impacto>"
}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = message.content[0].text.strip()
        data = json.loads(text)
        score = float(data.get("score", 0.0))
        score = max(-1.0, min(1.0, score))  # clamp
        summary = data.get("summary", "")
        return (score, summary)
    except Exception as exc:
        logger.error("Haiku analysis falhou para '%s': %s", title[:60], exc)
        return (0.0, "")


def run() -> None:
    articles = news_sources.fetch_all(max_age_minutes=12)  # margem de segurança vs 10 min

    if not articles:
        logger.info("Nenhum artigo novo encontrado")
        return

    haiku_count = 0
    alerts = []

    for article in articles:
        title = article["title"]
        url = article.get("url")
        source = article["source"]

        vader_score = analyze_with_vader(title)

        haiku_score = None
        haiku_summary = None

        if abs(vader_score) >= VADER_THRESHOLD:
            haiku_score, haiku_summary = analyze_with_haiku(title, url or "")
            haiku_count += 1
            logger.info(
                "Haiku [%.2f]: %s — %s",
                haiku_score,
                title[:60],
                haiku_summary[:80] if haiku_summary else "",
            )

        row_id = db.insert_article(
            source=source,
            title=title,
            url=url,
            vader_score=vader_score,
            haiku_score=haiku_score,
            haiku_summary=haiku_summary,
        )

        # Alerta se sentimento extremo (Haiku confirma o sinal VADER)
        if row_id and haiku_score is not None and abs(haiku_score) >= 0.7:
            score_to_use = haiku_score
            emoji = "🚀" if score_to_use > 0 else "💀"
            direction = "BULLISH" if score_to_use > 0 else "BEARISH"
            alerts.append({
                "title": title,
                "url": url,
                "score": score_to_use,
                "summary": haiku_summary,
                "emoji": emoji,
                "direction": direction,
                "row_id": row_id,
            })
            db.mark_article_alerted(row_id)

    logger.info(
        "Sentimento: %d artigos processados, %d via Haiku, %d alertas",
        len(articles), haiku_count, len(alerts),
    )

    for alert in alerts:
        telegram.send_alert(
            f"Sentimento {alert['direction']} — Score {alert['score']:+.2f}",
            f"<b>{alert['title']}</b>\n\n"
            f"📝 {alert['summary']}\n\n"
            f"{'<a href=\"' + alert['url'] + '\">Ler mais</a>' if alert['url'] else ''}",
            emoji=alert["emoji"],
        )


if __name__ == "__main__":
    db.init_db()
    run()
