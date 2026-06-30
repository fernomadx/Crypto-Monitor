#!/usr/bin/env python3
"""
Apaga o catálogo de previsões Kronos e recomeça o scorecard do zero.

NÃO apaga funding, notícias, portfolio nem outros dados do crypto-monitor.

Uso no Railway Shell:
  python3 vps/kronos_reset_catalog.py --confirm

Dry-run (só mostra quantos registros seriam apagados):
  python3 vps/kronos_reset_catalog.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.db import DB_PATH, get_conn  # noqa: E402
from lib.kronos_tracker import init_kronos_tables  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset catálogo Kronos (kronos_predictions)")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Executa a exclusão (sem isso, apenas mostra contagem)",
    )
    args = parser.parse_args()

    init_kronos_tables()

    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM kronos_predictions").fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM kronos_predictions WHERE scored_short_at IS NOT NULL"
        ).fetchone()[0]
        pending = total - scored

    print(f"DB: {DB_PATH}")
    print(f"Registros em kronos_predictions: {total} ({scored} avaliados, {pending} pendentes)")

    if total == 0:
        print("Nada a apagar.")
        return

    if not args.confirm:
        print("\nDry-run. Para apagar tudo e recomeçar:")
        print("  python3 vps/kronos_reset_catalog.py --confirm")
        return

    with get_conn() as conn:
        conn.execute("DELETE FROM kronos_predictions")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='kronos_predictions'")

    print(f"\n✅ Catálogo Kronos apagado ({total} registros).")
    print("Próximas previsões 4H operáveis começam scorecard limpo (v4.0: 3x, BTC, filtros novos).")
    print("Tabelas funding/notícias/portfolio não foram alteradas.")


if __name__ == "__main__":
    main()
