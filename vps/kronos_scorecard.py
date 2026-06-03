#!/usr/bin/env python3
"""Avalia previsões Kronos maduras e envia scorecard no Telegram [KRONOS]."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_tracker import format_scorecard_telegram, score_mature_predictions
from lib.telegram import send_kronos_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(force_report: bool = False) -> None:
    n = score_mature_predictions()
    now = datetime.now(timezone.utc)
    weekly = force_report or (now.weekday() == 6 and now.hour == 12)

    if n == 0 and not weekly:
        logger.info("Scorecard: %d novas avaliações — sem Telegram", n)
        return

    body = format_scorecard_telegram()
    if n > 0:
        title = f"Scorecard atualizado (+{n} avaliações)"
    else:
        title = "Scorecard semanal — acompanhamento"
    send_kronos_alert(title, body)
    logger.info("Scorecard enviado (%d novas avaliações, weekly=%s)", n, weekly)


if __name__ == "__main__":
    force = "--weekly" in sys.argv or "--force" in sys.argv
    run(force_report=force)
