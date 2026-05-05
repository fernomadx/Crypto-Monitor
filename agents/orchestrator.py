"""
agents/orchestrator.py — Consensus a cada 4h.

Cadência: a cada 4h (via supercronic).

Lógica:
    1. Lê sinais das últimas 4h do DB:
       - Funding rates (médias e picos por ticker)
       - Artigos com sentimento relevante (VADER ou Haiku)
       - Snapshots de preço recentes
    2. Monta prompt estruturado para Claude Haiku
    3. Haiku sintetiza em consenso de mercado (bullish / bearish / neutro + reasoning)
    4. Envia alerta no Telegram
    5. Salva síntese no DB
"""

import json
import logging
import os
import sys

sys.path.insert(0, "/app")

import anthropic

from lib import db, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def build_context(signals: dict) -> str:
    """Serializa sinais em texto estruturado para o prompt."""
    parts = []

    if signals["funding"]:
        parts.append("=== FUNDING RATES (últimas 4h) ===")
        for f in signals["funding"]:
            parts.append(
                f"  {f['ticker']}: avg={f['avg_funding']:.6f} max={f['max_funding']:.6f}"
            )

    if signals["prices"]:
        parts.append("\n=== PREÇOS RECENTES ===")
        seen = set()
        for p in signals["prices"]:
            key = (p["source"], p["ticker"])
            if key not in seen:
                parts.append(f"  {p['source'].upper()} {p['ticker']}: ${p['price']:,.2f} ({p['ts']})")
                seen.add(key)

    if signals["articles"]:
        parts.append("\n=== NOTÍCIAS COM SENTIMENTO RELEVANTE ===")
        for a in signals["articles"]:
            score = a.get("haiku_score") or a.get("vader_score") or 0
            summary = a.get("haiku_summary") or ""
            parts.append(
                f"  [{score:+.2f}] {a['title']}"
                + (f"\n    → {summary}" if summary else "")
            )

    return "\n".join(parts) if parts else "Nenhum sinal significativo nas últimas 4h."


def synthesize(context: str) -> str:
    """Chama Haiku para síntese. Retorna texto formatado."""
    if not ANTHROPIC_API_KEY:
        return "ANTHROPIC_API_KEY não configurado — síntese indisponível."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Você é um analista sênior de mercado crypto. Abaixo estão os dados coletados nas últimas 4 horas pelo sistema de monitoramento.

{context}

Com base nesses dados, produza uma síntese de mercado em português com:
1. **Consenso**: BULLISH / BEARISH / NEUTRO (com intensidade: fraco, moderado, forte)
2. **Reasoning**: 2-3 frases explicando os principais drivers
3. **Watch list**: até 3 pontos concretos para monitorar nas próximas 4h
4. **Risk**: 1 risco principal que poderia invalidar o consenso

Seja direto. Máximo de 200 palavras. Sem formalidades."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as exc:
        logger.error("Haiku synthesis falhou: %s", exc)
        return f"Erro na síntese: {exc}"


def run() -> None:
    signals = db.get_recent_signals(hours=4)

    has_data = signals["funding"] or signals["articles"] or signals["prices"]
    if not has_data:
        logger.info("Orchestrator: sem sinais nas últimas 4h, pulando síntese")
        return

    context = build_context(signals)
    logger.info("Orchestrator context:\n%s", context)

    synthesis = synthesize(context)
    logger.info("Orchestrator synthesis:\n%s", synthesis)

    db.insert_orchestrator_log(synthesis)

    telegram.send_alert(
        "Consensus 4h — Síntese de Mercado",
        synthesis,
        emoji="🧠",
    )


if __name__ == "__main__":
    db.init_db()
    run()
