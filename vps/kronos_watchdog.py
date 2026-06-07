#!/usr/bin/env python3
"""Alerta se Kronos não enviou previsão há muito tempo."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_config import RULES_VERSION, apply_v31_defaults  # noqa: E402

apply_v31_defaults()

from lib.telegram import send_kronos_alert  # noqa: E402

STAMP = Path(os.environ.get("KRONOS_LAST_OK", "/data/kronos.last_ok"))
MAX_AGE_SEC = int(os.environ.get("KRONOS_WATCHDOG_MAX_AGE", str(90 * 60)))  # 90min (cron 1H)


def main() -> None:
    now = time.time()
    if not STAMP.exists():
        send_kronos_alert(
            "Watchdog Kronos",
            f"⚠️ Sem registro de execução OK (<code>{STAMP}</code>).\n"
            f"Verifique deploy Railway e <code>/data/kronos.log</code>.\n"
            f"<i>rules v{RULES_VERSION}</i>",
        )
        return

    age = now - STAMP.stat().st_mtime
    if age > MAX_AGE_SEC:
        last = datetime.fromtimestamp(STAMP.stat().st_mtime, tz=timezone.utc).strftime("%d/%m %H:%M UTC")
        send_kronos_alert(
            "Watchdog Kronos",
            f"⚠️ Sem alerta há <b>{int(age // 3600)}h{int((age % 3600) // 60)}m</b> "
            f"(último OK: {last}).\n"
            f"Possível crash/OOM no container — redeploy ou ver <code>/data/kronos.log</code>.\n"
            f"<i>rules v{RULES_VERSION}</i>",
        )


if __name__ == "__main__":
    main()
