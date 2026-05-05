"""
lib/telegram.py — helper para enviar mensagens ao Telegram.

Uso:
    from lib.telegram import send, send_alert
    send("mensagem simples")
    send_alert("🚨 Funding alto", "BTC: 0.08%")
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send(text: str, parse_mode: str = "HTML") -> bool:
    """
    Envia mensagem de texto ao chat configurado.
    Retorna True se 200 OK, False caso contrário.
    Nunca levanta exceção — falha silenciosa com log.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not resp.ok:
            logger.error("Telegram error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def send_alert(title: str, body: str, emoji: str = "🔔") -> bool:
    """Formata alerta com título em negrito e corpo."""
    text = f"{emoji} <b>{title}</b>\n{body}"
    return send(text)
