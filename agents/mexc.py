"""
agents/mexc.py — Saldo da carteira MEXC + preço BTC spot.

Cadência: a cada 15 min (via supercronic).

Lógica:
    1. Busca preço BTC/USDT (endpoint público, sem autenticação)
    2. Salva no DB
    3. Busca saldo da conta spot (requer API key read-only)
    4. Salva snapshot no DB
    5. Alerta com resumo do saldo

Segurança: MEXC_API_KEY e MEXC_API_SECRET nunca entram no código.
           Sempre lidos de variáveis de ambiente.
"""

import hashlib
import hmac
import logging
import os
import sys
import time

sys.path.insert(0, "/app")

import requests

from lib import db, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MEXC_API_KEY = os.environ.get("MEXC_API_KEY", "")
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET", "")
MEXC_BASE = "https://api.mexc.com"

# Ativos a exibir no alerta (ignora saldos < threshold em USDT)
MIN_USD_VALUE = 1.0


def _sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(
        MEXC_API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()


def _headers() -> dict:
    return {"X-MEXC-APIKEY": MEXC_API_KEY}


def fetch_btc_price() -> float | None:
    """Endpoint público — não requer autenticação."""
    try:
        resp = requests.get(
            f"{MEXC_BASE}/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=10,
        )
        resp.raise_for_status()
        price = float(resp.json()["price"])
        db.insert_price("mexc", "BTC", price)
        logger.info("MEXC BTC price: $%.2f", price)
        return price
    except Exception as exc:
        logger.error("fetch_btc_price falhou: %s", exc)
        return None


def fetch_account_balance() -> None:
    """Requer MEXC_API_KEY + MEXC_API_SECRET (read-only)."""
    if not MEXC_API_KEY or not MEXC_API_SECRET:
        logger.warning("MEXC_API_KEY / MEXC_API_SECRET não configurados, pulando saldo")
        return

    try:
        ts = int(time.time() * 1000)
        params = {"timestamp": ts}
        params["signature"] = _sign(params)

        resp = requests.get(
            f"{MEXC_BASE}/api/v3/account",
            params=params,
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        balances = [
            b for b in data.get("balances", [])
            if float(b["free"]) + float(b["locked"]) > 0
        ]

        # Busca preços para converter para USD (simplificado: usa USDT como referência)
        lines = []
        total_usd = 0.0

        for b in balances:
            asset = b["asset"]
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked

            # Tenta estimar valor em USDT
            usd_value = None
            if asset == "USDT":
                usd_value = total
            else:
                try:
                    r = requests.get(
                        f"{MEXC_BASE}/api/v3/ticker/price",
                        params={"symbol": f"{asset}USDT"},
                        timeout=5,
                    )
                    if r.ok:
                        usd_value = total * float(r.json()["price"])
                except Exception:
                    pass

            if usd_value is not None and usd_value < MIN_USD_VALUE:
                continue  # dust

            db.upsert_portfolio("mexc", asset, total, usd_value)

            if usd_value is not None:
                total_usd += usd_value
                lines.append(f"• <b>{asset}</b>: {total:.6g} (~${usd_value:,.2f})")
            else:
                lines.append(f"• <b>{asset}</b>: {total:.6g}")

        if lines:
            body = "\n".join(lines)
            if total_usd:
                body += f"\n\n<b>Total estimado: ~${total_usd:,.2f}</b>"
            telegram.send_alert("Saldo MEXC", body, emoji="💼")
        else:
            logger.info("MEXC: nenhum saldo relevante")

    except Exception as exc:
        logger.error("fetch_account_balance falhou: %s", exc)
        telegram.send(f"⚠️ MEXC balance fetch error: {exc}")


if __name__ == "__main__":
    db.init_db()
    btc = fetch_btc_price()
    if btc:
        logger.info("BTC/USDT: $%.2f", btc)
    fetch_account_balance()
