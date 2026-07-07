"""Detecta mudança de versão das regras Kronos e reseta scorecard automaticamente."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from lib.kronos_config import RULES_VERSION, format_boot_message

logger = logging.getLogger(__name__)

STAMP_PATH = Path(os.environ.get("KRONOS_RULES_STAMP", "/data/kronos_rules_version.txt"))
RESET_FOR_PATH = Path(os.environ.get("KRONOS_RESET_FOR_STAMP", "/data/kronos_catalog_reset_for.txt"))


def _reset_catalog() -> int:
    from lib.db import get_conn
    from lib.kronos_tracker import init_kronos_tables

    init_kronos_tables()
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM kronos_predictions").fetchone()[0]
        if total > 0:
            conn.execute("DELETE FROM kronos_predictions")
            conn.execute("DELETE FROM sqlite_sequence WHERE name='kronos_predictions'")
    logger.info("Kronos catalog reset: %d registros apagados (rules v%s)", total, RULES_VERSION)
    return total


def ensure_catalog_for_current_rules(*, notify: bool = True) -> tuple[bool, int]:
    """
    Reseta catálogo se ainda não foi resetado para RULES_VERSION atual.
    Retorna (reset_executado, registros_apagados).
    """
    RESET_FOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)

    reset_for = RESET_FOR_PATH.read_text().strip() if RESET_FOR_PATH.exists() else ""
    prev_rules = STAMP_PATH.read_text().strip() if STAMP_PATH.exists() else ""

    force = os.environ.get("KRONOS_FORCE_CATALOG_RESET", "").strip().lower() in ("1", "true", "yes")
    need_reset = force or reset_for != RULES_VERSION

    deleted = 0
    if need_reset:
        deleted = _reset_catalog()
        RESET_FOR_PATH.write_text(RULES_VERSION)
        if notify:
            _notify_reset(prev_rules or reset_for or "?", deleted)

    STAMP_PATH.write_text(RULES_VERSION)
    return need_reset, deleted


def check_and_update(*, notify: bool = True) -> bool:
    """Compat: retorna True se resetou catálogo nesta execução."""
    did_reset, _ = ensure_catalog_for_current_rules(notify=notify)
    return did_reset


def _notify_reset(old: str, deleted: int) -> None:
    try:
        from lib.telegram import send_kronos_alert

        body = format_boot_message()
        if deleted:
            body = (
                f"🔄 <b>Scorecard resetado</b> — {deleted} registros antigos (v{old}) apagados.\n"
                f"Catálogo limpo para <b>v{RULES_VERSION}</b>.\n\n" + body
            )
        else:
            body = f"✅ Catálogo v{RULES_VERSION} já estava limpo.\n\n" + body
        send_kronos_alert(f"Kronos v{RULES_VERSION} pronto", body)
    except Exception as exc:
        logger.warning("notify reset: %s", exc)
