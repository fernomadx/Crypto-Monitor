"""Trade Desk — multi-agent confirmation layer for Kronos."""

from lib.trade_desk.engine import apply_desk_to_results, evaluate_symbol, format_desk_section
from lib.trade_desk.models import DeskVerdict, Side

__all__ = [
    "Side",
    "DeskVerdict",
    "evaluate_symbol",
    "apply_desk_to_results",
    "format_desk_section",
]