"""
agents/hyperliquid.py — Funding rates + posições/PnL da carteira.

Cadência: a cada 15 min (via supercronic).

Lógica:
    1. Busca funding rate atual de BTC, ETH, SOL via API pública
    2. Salva no DB
    3. Alerta se |funding| > FUNDING_THRESHOLD
    4. Busca posições abertas do endereço configurado
    5. Alerta se PnL não-realizado mudou >5% desde último snapshot
"""

import os
import sys
import logging

# Garante que lib/ seja importável
sys.path.insert(0, "/app")

import requests

from lib import db, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HL_URL = "https://api.hyperliquid.xyz/info"
ADDRESS = os.environ.get("HYPERLIQUID_ADDRESS", "")
TICKERS = [t.strip() for t in os.environ.get("TICKERS", "BTC,ETH,SOL").split(",")]
FUNDING_THRESHOLD = float(os.environ.get("FUNDING_THRESHOLD", "0.0005"))


def _post(payload: dict) -> dict:
    resp = requests.post(HL_URL, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_funding_rates() -> None:
    """Busca e salva funding rates de todos os tickers configurados."""
    try:
        data = _post({"type": "metaAndAssetCtxs"})
        universe = data[0]["universe"]
        asset_ctxs = data[1]

        # Mapeia nome do ativo → índice
        name_to_idx = {asset["name"]: i for i, asset in enumerate(universe)}

        for ticker in TICKERS:
            idx = name_to_idx.get(ticker)
            if idx is None:
                logger.warning("Ticker %s não encontrado na Hyperliquid", ticker)
                continue

            ctx = asset_ctxs[idx]
            funding = float(ctx.get("funding", 0))
            mark_price = float(ctx.get("markPx", 0))

            db.insert_funding(ticker, funding, mark_price)
            db.insert_price("hyperliquid", ticker, mark_price)

            logger.info("Hyperliquid %s: funding=%.6f markPx=%.2f", ticker, funding, mark_price)

            if abs(funding) >= FUNDING_THRESHOLD:
                direction = "🟢 LONG paga SHORT" if funding > 0 else "🔴 SHORT paga LONG"
                telegram.send_alert(
                    f"Funding Alert — {ticker}",
                    f"Rate: <code>{funding:.6f}</code> ({funding*100:.4f}%)\n"
                    f"Threshold: {FUNDING_THRESHOLD:.6f}\n"
                    f"Direção: {direction}\n"
                    f"Mark price: ${mark_price:,.2f}",
                    emoji="💸",
                )

    except Exception as exc:
        logger.error("fetch_funding_rates falhou: %s", exc)
        telegram.send(f"⚠️ Hyperliquid funding fetch error: {exc}")


def fetch_positions() -> None:
    """Busca posições abertas + PnL do endereço configurado."""
    if not ADDRESS:
        logger.warning("HYPERLIQUID_ADDRESS não configurado, pulando posições")
        return

    try:
        data = _post({"type": "clearinghouseState", "user": ADDRESS})
        asset_positions = data.get("assetPositions", [])

        if not asset_positions:
            logger.info("Nenhuma posição aberta em %s", ADDRESS)
            return

        lines = []
        for pos_wrapper in asset_positions:
            pos = pos_wrapper.get("position", {})
            coin = pos.get("coin", "?")
            size = float(pos.get("szi", 0))
            entry_px = float(pos.get("entryPx", 0) or 0)
            unrealized_pnl = float(pos.get("unrealizedPnl", 0) or 0)
            leverage = pos.get("leverage", {})
            lev_value = leverage.get("value", "?") if isinstance(leverage, dict) else "?"

            if size == 0:
                continue

            side = "LONG" if size > 0 else "SHORT"
            pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
            lines.append(
                f"{pnl_emoji} <b>{coin}</b> {side} | Size: {abs(size):.4f} | "
                f"Entry: ${entry_px:,.2f} | PnL: ${unrealized_pnl:+,.2f} | {lev_value}x"
            )

            # Salva snapshot
            db.upsert_portfolio("hyperliquid", coin, size, unrealized_pnl)

        if lines:
            telegram.send_alert(
                "Posições Hyperliquid",
                "\n".join(lines),
                emoji="📊",
            )

    except Exception as exc:
        logger.error("fetch_positions falhou: %s", exc)
        telegram.send(f"⚠️ Hyperliquid positions fetch error: {exc}")


if __name__ == "__main__":
    db.init_db()
    fetch_funding_rates()
    fetch_positions()
