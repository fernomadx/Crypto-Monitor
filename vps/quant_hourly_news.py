#!/usr/bin/env python3
"""
Digest QUANT no fechamento do candle 1H (cron :01 UTC).

Envia [QUANT] no Telegram com manchetes da última hora + resumo Haiku.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.quant_hourly_news import build_digest  # noqa: E402
from lib.telegram import send_quant_alert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCK_PATH = Path(os.environ.get("QUANT_HOURLY_LOCK", "/data/quant_hourly.lock"))
GRACE_SEC = int(os.environ.get("QUANT_HOURLY_GRACE_SEC", "45"))


def _lock_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")


def _acquire_lock() -> bool:
    key = _lock_key()
    if LOCK_PATH.exists() and LOCK_PATH.read_text().strip() == key:
        logger.info("QUANT hourly: já executado nesta hora (%s)", key)
        return False
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(key)
    return True


def run() -> None:
    if GRACE_SEC > 0:
        logger.info("Aguardando %ss pós-fechamento candle 1H...", GRACE_SEC)
        time.sleep(GRACE_SEC)

    if not _acquire_lock():
        return

    body = build_digest()
    if not body:
        logger.info("QUANT hourly: sem manchetes na janela — skip Telegram")
        return

    if send_quant_alert("Notícias 1H — candle fechado", body):
        logger.info("QUANT hourly digest enviado")
    else:
        logger.error("QUANT hourly: falha ao enviar Telegram")


if __name__ == "__main__":
    run()
