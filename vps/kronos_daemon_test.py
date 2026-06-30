#!/usr/bin/env python3
"""Testes do agendamento de candles do daemon Kronos."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_schedule import format_next_candle_line, next_candle_close_at, next_wake_time  # noqa: E402


def _utc(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 6, 7, h, m, s, tzinfo=timezone.utc)


class KronosDaemonScheduleTest(unittest.TestCase):
    def test_next_close_before_delay_window(self) -> None:
        self.assertEqual(next_candle_close_at(_utc(22, 0, 5)), _utc(22, 0, 0))

    def test_next_close_after_delay_window(self) -> None:
        self.assertEqual(next_candle_close_at(_utc(22, 48)), _utc(23, 0, 0))

    def test_next_close_exactly_at_delay(self) -> None:
        self.assertEqual(next_candle_close_at(_utc(22, 0, 12)), _utc(23, 0, 0))

    def test_wake_is_close_plus_delay(self) -> None:
        close = next_candle_close_at(_utc(22, 48))
        wake = next_wake_time(_utc(22, 48))
        self.assertEqual(wake, close.replace(second=12))

    def test_format_line_at_2248_shows_2300(self) -> None:
        line = format_next_candle_line(_utc(22, 48))
        self.assertIn("23:00 UTC", line)
        self.assertNotIn("22:00 UTC", line)

    def test_format_line_at_2147_shows_2200(self) -> None:
        line = format_next_candle_line(_utc(21, 47))
        self.assertIn("22:00 UTC", line)


if __name__ == "__main__":
    unittest.main()
