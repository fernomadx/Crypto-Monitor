"""Detecta mudança de versão das regras Kronos e sugere reset do scorecard."""

from __future__ import annotations

import os
from pathlib import Path

from lib.kronos_config import RULES_VERSION

STAMP_PATH = Path(os.environ.get("KRONOS_RULES_STAMP", "/data/kronos_rules_version.txt"))


def check_and_update(*, notify: bool = True) -> bool:
    """
    Retorna True se a versão mudou neste boot.
    Grava a versão atual em disco.
    """
    prev = STAMP_PATH.read_text().strip() if STAMP_PATH.exists() else ""
    changed = prev != RULES_VERSION
    if changed:
        STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        STAMP_PATH.write_text(RULES_VERSION)
        if notify and prev:
            _notify_version_change(prev)
    elif not STAMP_PATH.exists():
        STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        STAMP_PATH.write_text(RULES_VERSION)
    return changed


def _notify_version_change(old: str) -> None:
    try:
        from lib.telegram import send_kronos_alert

        send_kronos_alert(
            f"Regras {old} → v{RULES_VERSION}",
            "Scorecard antigo não é comparável com as novas regras.\n"
            "Rode no Railway Shell:\n"
            "<code>python3 vps/kronos_reset_catalog.py --confirm</code>\n"
            "Próximos trades 4H BTC entram no catálogo v5 limpo.",
        )
    except Exception:
        pass
