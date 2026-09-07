"""Optional Telegram notifier for ATLAS alerts."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """Sends messages only when ATLAS_TELEGRAM_* is configured. Never required."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    async def send(self, text: str) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "detail": "ATLAS_TELEGRAM_BOT_TOKEN/CHAT_ID not set"}

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": text[:3500],
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_sec) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
                if not body.get("ok"):
                    logger.warning("telegram_send_failed", body=body)
                    return {"status": "error", "detail": str(body)}
                return {"status": "sent", "message_id": body.get("result", {}).get("message_id")}
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram_send_exception", error=str(exc))
            return {"status": "error", "detail": str(exc)}

    async def send_alert(self, *, kind: str, message: str, symbol: str, price: float | None) -> dict[str, Any]:
        text = (
            f"ATLAS alert [{kind}]\n"
            f"{symbol}\n"
            f"{message}\n"
            f"price={price if price is not None else 'n/a'}"
        )
        return await self.send(text)
