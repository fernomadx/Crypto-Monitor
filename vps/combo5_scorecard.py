#!/usr/bin/env python3
"""Envia ranking de performance COMBO5 no Telegram [COMBO5] (cron Railway)."""

from __future__ import annotations

import html
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.telegram import send_combo5_alert  # noqa: E402
from vps.combo5_signal import ranking_now  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("COMBO5_ENABLED", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run() -> int:
    if not _enabled():
        logger.info("COMBO5_ENABLED=0 — ranking não enviado")
        return 0
    body = ranking_now()
    sent = send_combo5_alert("RANKING", f"<pre>{html.escape(body)}</pre>")
    logger.info("COMBO5 ranking telegram=%s", sent)
    print(body, flush=True)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(run())
