"""Agendamento de candles horários do daemon Kronos."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

CANDLE_DELAY_SEC = int(os.environ.get("KRONOS_CANDLE_DELAY_SEC", "12"))


def next_candle_close_at(now: datetime) -> datetime:
    """Próximo fechamento HH:00 UTC do candle horário (sempre no futuro ou iminente)."""
    now_utc = now.astimezone(timezone.utc)
    close = now_utc.replace(minute=0, second=0, microsecond=0)
    if now_utc >= close + timedelta(seconds=CANDLE_DELAY_SEC):
        close += timedelta(hours=1)
    return close


def next_wake_time(now: datetime) -> datetime:
    """Próximo instante para rodar após fechamento do candle horário."""
    return next_candle_close_at(now) + timedelta(seconds=CANDLE_DELAY_SEC)


def format_next_candle_line(now: datetime | None = None) -> str:
    """Linha Telegram com próximo fechamento e minutos restantes (UTC)."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    close = next_candle_close_at(now_utc)
    mins = max(0, int((close - now_utc).total_seconds() + 59) // 60)
    return f"Próximo fechamento: <b>{close.strftime('%H:%M')} UTC</b> (em ~{mins} min)"
