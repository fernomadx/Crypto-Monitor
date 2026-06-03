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
    new_trades = score_mature_predictions()
    short_closed = [t for t in new_trades if t.get("horizon") == "short"]
    now = datetime.now(timezone.utc)
    weekly = force_report or (now.weekday() == 6 and now.hour == 12)

    if not short_closed and not weekly:
        logger.info("Scorecard: nada novo — sem Telegram")
        return

    body = format_scorecard_telegram(new_trades=short_closed if short_closed else None)
    if short_closed:
        gains = sum(1 for t in short_closed if t["result"] == "gain")
        losses = sum(1 for t in short_closed if t["result"] == "loss")
        pnl = sum(t["pnl_usdc"] for t in short_closed)
        title = f"Scorecard — {gains} gain / {losses} loss (${pnl:+.2f})"
    else:
        title = "Scorecard semanal — 1000 USDC / 100 por trade"
    send_kronos_alert(title, body)
    logger.info("Scorecard enviado (%d fechadas, weekly=%s)", len(short_closed), weekly)


if __name__ == "__main__":
    force = "--weekly" in sys.argv or "--force" in sys.argv
    run(force_report=force)
