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


def _telegram_config() -> tuple[str, str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID devem estar definidos (Railway Variables)."
        )
    return token, chat_id, f"https://api.telegram.org/bot{token}"


def _kronos_telegram_config() -> tuple[str, str, str]:
    """
    Bot dedicado Kronos (VPS BTCCURSOR).
    Se KRONOS_TELEGRAM_* não estiver definido, usa o bot principal (Railway).
    """
    token = (
        os.environ.get("KRONOS_TELEGRAM_BOT_TOKEN", "").strip()
        or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    )
    chat_id = (
        os.environ.get("KRONOS_TELEGRAM_CHAT_ID", "").strip()
        or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    )
    if not token or not chat_id:
        raise RuntimeError(
            "Defina KRONOS_TELEGRAM_BOT_TOKEN + KRONOS_TELEGRAM_CHAT_ID (BTCCURSOR) "
            "ou TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (Railway)."
        )
    return token, chat_id, f"https://api.telegram.org/bot{token}"


def send(text: str, parse_mode: str = "HTML") -> bool:
    """
    Envia mensagem de texto ao chat configurado.
    Retorna True se 200 OK, False caso contrário.
    Nunca levanta exceção — falha silenciosa com log.
    """
    try:
        _, chat_id, base_url = _telegram_config()
        resp = requests.post(
            f"{base_url}/sendMessage",
            json={
                "chat_id": chat_id,
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


def send_kronos_alert(title: str, body: str) -> bool:
    """
    Alerta Kronos — bot dedicado (KRONOS_TELEGRAM_*) ou fallback Railway.
    Prefixo [KRONOS] no texto da mensagem.
    """
    text = (
        f"📈 <b>[KRONOS]</b> {title}\n\n{body}\n\n"
        "<i>Experimental — não é recomendação de trade. "
        "Confirme com preço, funding e notícias do monitor.</i>"
    )
    try:
        _, chat_id, base_url = _kronos_telegram_config()
        resp = requests.post(
            f"{base_url}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not resp.ok:
            logger.error("Kronos Telegram error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.error("Kronos Telegram send failed: %s", exc)
        return False


def send_photo(path: str, caption: str = "", parse_mode: str = "HTML") -> bool:
    """Envia imagem ao chat (PNG/JPG). Caption até 1024 caracteres."""
    try:
        _, chat_id, base_url = _telegram_config()
        caption = caption[:1024]
        with open(path, "rb") as photo_file:
            resp = requests.post(
                f"{base_url}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": parse_mode,
                },
                files={"photo": photo_file},
                timeout=60,
            )
        if not resp.ok:
            logger.error("Telegram photo error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.error("Telegram send_photo failed: %s", exc)
        return False


def send_quant_alert(title: str, body: str) -> bool:
    """Alerta do módulo QUANT — canal separado de KRONOS e sentiment."""
    text = (
        f"🧠 <b>[QUANT]</b> {title}\n\n{body}\n\n"
        "<i>Contexto / pesquisa — não é ordem de trade. "
        "Use com Kronos e funding.</i>"
    )
    return send(text)


def _chunk_text(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return chunks


def _strip_html(text: str) -> str:
    import re

    plain = re.sub(r"</?([bi]|code|i)>", "", text)
    return plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def send_quant_reply(chat_id: str, body: str, *, parse_mode: str | None = "HTML") -> bool:
    """Resposta do bot QUANT (on-demand) para um chat."""
    try:
        _, _, base_url = _telegram_config()
        ok = True
        for chunk in _chunk_text(body[:12000]):
            payload: dict = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            resp = requests.post(
                f"{base_url}/sendMessage",
                json=payload,
                timeout=30,
            )
            if not resp.ok and parse_mode == "HTML":
                logger.warning("Quant reply HTML failed %s — retry plain", resp.status_code)
                plain = _strip_html(chunk)
                resp = requests.post(
                    f"{base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": plain,
                        "disable_web_page_preview": True,
                    },
                    timeout=30,
                )
            if not resp.ok:
                logger.error("Quant reply error %s: %s", resp.status_code, resp.text[:200])
                ok = False
        return ok
    except Exception as exc:
        logger.error("Quant reply failed: %s", exc)
        return False


def send_kronos_photo(path: str, caption: str) -> bool:
    """Gráfico Kronos via bot dedicado (ou fallback)."""
    text = f"📈 [KRONOS] {caption}"
    try:
        _, chat_id, base_url = _kronos_telegram_config()
        with open(path, "rb") as photo_file:
            resp = requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": chat_id, "caption": text[:1024]},
                files={"photo": photo_file},
                timeout=60,
            )
        if not resp.ok:
            logger.error("Kronos Telegram photo error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.error("Kronos Telegram send_photo failed: %s", exc)
        return False
