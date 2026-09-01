"""COMBO5 — Kronos 3TF + desk veto + journal numerado (entrada/stop/saída)."""

from lib.combo5.journal import (
    TradeJournal,
    format_entry_alert,
    format_exit_alert,
    format_performance_ranking,
)

__all__ = [
    "TradeJournal",
    "format_entry_alert",
    "format_exit_alert",
    "format_performance_ranking",
    "Combo5Signal",
    "evaluate_combo5",
]


def __getattr__(name: str):
    if name in {"Combo5Signal", "evaluate_combo5"}:
        from lib.combo5.signal import Combo5Signal, evaluate_combo5

        exports = {
            "Combo5Signal": Combo5Signal,
            "evaluate_combo5": evaluate_combo5,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
