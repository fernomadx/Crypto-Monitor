"""
agents/polymarket.py — Scanner de oportunidades em mercados de previsão.

Cadência: a cada 30 min (via supercronic).

Lógica:
    1. Busca mercados ativos de crypto via Gamma API (pública, sem auth)
    2. Filtra por volume mínimo e spread de probabilidade interessante
    3. Alerta mercados com edge aparente (probabilidade ≠ expectativa de mercado eficiente)

Nota: Polymarket não tem endpoint de arbitragem garantido — este agente
      sinaliza mercados que merecem atenção manual, não executa trades.
"""

import logging
import sys

sys.path.insert(0, "/app")

import requests

from lib import db, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"

# Filtros
MIN_VOLUME_24H = 5_000      # USD — ignora mercados com pouco volume
MIN_LIQUIDITY = 1_000       # USD — ignora mercados secos
CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "crypto", "coinbase", "binance", "halving", "etf",
]

# Probabilidade "interessante": nem perto de 0 nem perto de 1
PROB_MIN = 0.10
PROB_MAX = 0.90


def _is_crypto_market(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in CRYPTO_KEYWORDS)


def fetch_markets() -> list[dict]:
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": 100,
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("Polymarket fetch_markets falhou: %s", exc)
        return []


def scan() -> None:
    markets = fetch_markets()
    if not markets:
        return

    interesting = []

    for m in markets:
        question = m.get("question", "")
        if not _is_crypto_market(question):
            continue

        volume_24h = float(m.get("volume24hr", 0) or 0)
        liquidity = float(m.get("liquidity", 0) or 0)

        if volume_24h < MIN_VOLUME_24H or liquidity < MIN_LIQUIDITY:
            continue

        # outcomes: lista de {outcome, price}
        outcomes = m.get("outcomes", [])
        prices_raw = m.get("outcomePrices", [])

        # Normaliza: Polymarket retorna preços como strings ou lista
        try:
            if isinstance(prices_raw, str):
                import json
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw

            prices = [float(p) for p in prices]
        except Exception:
            continue

        if len(prices) < 2:
            continue

        yes_prob = prices[0]  # índice 0 = YES

        if not (PROB_MIN <= yes_prob <= PROB_MAX):
            continue  # muito certo ou muito improvável — menos interessante

        end_date = m.get("endDate", "N/A")
        url = f"https://polymarket.com/event/{m.get('slug', '')}"

        interesting.append({
            "question": question,
            "yes_prob": yes_prob,
            "volume_24h": volume_24h,
            "liquidity": liquidity,
            "end_date": end_date,
            "url": url,
        })

    logger.info("Polymarket: %d mercados crypto interessantes de %d totais", len(interesting), len(markets))

    if not interesting:
        return

    # Ordena por volume
    interesting.sort(key=lambda x: x["volume_24h"], reverse=True)
    top = interesting[:5]

    lines = []
    for m in top:
        prob_pct = m["yes_prob"] * 100
        lines.append(
            f"• <b>{m['question']}</b>\n"
            f"  YES: {prob_pct:.1f}% | Vol24h: ${m['volume_24h']:,.0f} | "
            f"Liq: ${m['liquidity']:,.0f}\n"
            f"  Fecha: {m['end_date'][:10] if m['end_date'] != 'N/A' else 'N/A'} | "
            f"<a href='{m['url']}'>Ver mercado</a>"
        )

    telegram.send_alert(
        f"Polymarket — {len(interesting)} mercados crypto ativos",
        "\n\n".join(lines),
        emoji="🎯",
    )


if __name__ == "__main__":
    db.init_db()
    scan()
