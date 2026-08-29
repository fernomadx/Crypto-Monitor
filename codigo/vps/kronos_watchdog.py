#!/usr/bin/env python3
"""Alerta se Kronos não enviou previsão há muito tempo (com cooldown anti-spam)."""

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
ALERT_STAMP = Path(os.environ.get("KRONOS_WATCHDOG_ALERT_STAMP", "/data/kronos_watchdog_alerted"))
MAX_AGE_SEC = int(os.environ.get("KRONOS_WATCHDOG_MAX_AGE", str(90 * 60)))  # 90min
ALERT_COOLDOWN_SEC = int(os.environ.get("KRONOS_WATCHDOG_COOLDOWN", str(4 * 3600)))  # 4h


def _recently_alerted() -> bool:
    if not ALERT_STAMP.exists():
        return False
    return (time.time() - ALERT_STAMP.stat().st_mtime) < ALERT_COOLDOWN_SEC


def _send_watchdog(body: str) -> None:
    send_kronos_alert("Watchdog Kronos", body)
    ALERT_STAMP.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STAMP.touch()


def main() -> None:
    if _recently_alerted():
        return

    now = time.time()
    if not STAMP.exists():
        _send_watchdog(
            f"⚠️ Sem registro de execução OK (<code>{STAMP}</code>).\n"
            f"Verifique deploy Railway e <code>/data/kronos_daemon.log</code>.\n"
            f"<i>rules v{RULES_VERSION}</i>"
        )
        return

    age = now - STAMP.stat().st_mtime
    if age > MAX_AGE_SEC:
        last = datetime.fromtimestamp(STAMP.stat().st_mtime, tz=timezone.utc).strftime(
            "%d/%m %H:%M UTC"
        )
        _send_watchdog(
            f"⚠️ Sem alerta há <b>{int(age // 3600)}h{int((age % 3600) // 60)}m</b> "
            f"(último OK: {last}).\n"
            f"Possível crash/OOM — backup cron :08 UTC tenta recuperar.\n"
            f"Logs: <code>/data/kronos_daemon.log</code> · <code>/data/kronos.log</code>\n"
            f"<i>rules v{RULES_VERSION}</i>"
        )


if __name__ == "__main__":
    main()
