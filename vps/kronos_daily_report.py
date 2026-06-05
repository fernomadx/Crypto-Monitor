#!/usr/bin/env python3
"""Envia relatório diário Kronos no Telegram (ranking por timeframe + scorecard)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_config import apply_v31_defaults  # noqa: E402

apply_v31_defaults()

from lib.kronos_tracker import format_daily_report_telegram, init_kronos_tables  # noqa: E402
from lib.telegram import send_kronos_alert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(dry_run: bool = False) -> None:
    init_kronos_tables()
    body = format_daily_report_telegram()
    if dry_run:
        print(body.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
        return
    ok = send_kronos_alert("Relatório diário — performance por timeframe", body)
    if ok:
        logger.info("Relatório diário [KRONOS] enviado")
    else:
        logger.error("Falha ao enviar relatório diário")
        sys.exit(1)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
