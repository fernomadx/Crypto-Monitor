#!/usr/bin/env python3
"""Diagnóstico Kronos — rode no Railway Shell: python vps/kronos_check.py"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_config import RULES_VERSION, active_config, apply_v31_defaults  # noqa: E402

apply_v31_defaults()

LOG = Path("/data/kronos.log")
STAMP = Path("/data/kronos.last_ok")
LOCK = Path("/data/kronos.signal.lock")
BOOT = Path("/app/vps/railway_boot.sh")
RUN_SH = Path("/app/vps/kronos_run.sh")


def age(path: Path) -> str:
    if not path.exists():
        return "não existe"
    sec = time.time() - path.stat().st_mtime
    return f"{int(sec // 3600)}h{int((sec % 3600) // 60)}m atrás"


def tail(path: Path, n: int = 15) -> str:
    if not path.exists():
        return "(arquivo ausente)"
    lines = path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-n:]) if lines else "(vazio)"


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    c = active_config()
    print(f"=== Kronos check — {now} ===\n")
    print(f"Rules version: {RULES_VERSION}")
    print(f"Config: R:R {c['min_rr']} stop4H {c['stop_4h']}% temp {c['temperature']}")
    print(f"TELEGRAM_BOT_TOKEN: {'OK' if os.environ.get('TELEGRAM_BOT_TOKEN') else 'FALTA'}")
    print(f"TELEGRAM_CHAT_ID: {'OK' if os.environ.get('TELEGRAM_CHAT_ID') else 'FALTA'}")
    print(f"KRONOS_PATH exists: {Path(os.environ.get('KRONOS_PATH', '/app/Kronos')).is_dir()}")
    print(f"railway_boot.sh (sem signal no boot): {BOOT.exists()}")
    print(f"kronos_run.sh (lock): {RUN_SH.exists()}")
    print(f"\n/data/kronos.last_ok: {age(STAMP)}")
    print(f"/data/kronos.signal.lock: {age(LOCK)}", end="")
    if LOCK.exists():
        try:
            pid = LOCK.read_text().strip()
            print(f" pid={pid}")
        except Exception:
            print()
    else:
        print()
    print(f"/data/kronos.log: {age(LOG)}")
    print("\n--- últimas linhas kronos.log ---")
    print(tail(LOG))
    print("\nCron esperado: minuto :15 UTC a cada 2h (18:15, 20:15, ...)")
    print("Watchdog: :45 UTC a cada 2h se >3h30 sem last_ok")


if __name__ == "__main__":
    main()
