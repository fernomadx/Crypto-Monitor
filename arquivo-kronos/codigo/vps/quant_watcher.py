#!/usr/bin/env python3
"""
Watcher QUANT — detecta notícias de impacto e manda [QUANT] no Telegram.

Roda no Hetzner (ou Railway) a cada 5–10 min via cron.
Não spamma: só alerta quando há notícia nova acima do threshold.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.quant_impact import scan_new_impacts  # noqa: E402
from lib.telegram import send_quant_alert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    alerts = scan_new_impacts()
    if not alerts:
        logger.info("QUANT watcher: sem impacto novo")
        return

    for a in alerts:
        tickers = ", ".join(a.get("tickers", []))
        direction = a.get("bias", "NEUTRAL")
        score = a.get("impact_score", 0)
        body = (
            f"<b>{a.get('title', '')}</b>\n\n"
            f"Impacto: <b>{direction}</b> ({score:.0%}) · {tickers}\n"
            f"📝 {a.get('summary', '')}\n"
        )
        if a.get("url"):
            body += f'\n<a href="{a["url"]}">Fonte</a>'
        send_quant_alert(f"Notícia de impacto — {direction}", body)
        logger.info("Alerta QUANT: %s (%.0f%%)", a.get("title", "")[:60], score * 100)


if __name__ == "__main__":
    run()
