"""Regras do bot 📊 MEXC Análise (banner)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from lib.mexc_analise_bot import (
    BotState,
    Position,
    boot_banner,
    evaluate_signal,
    tick,
)


def _df_from_closes(closes: list[float], *, high_off: float = 10.0, low_off: float = 10.0) -> pd.DataFrame:
    n = len(closes)
    rows = []
    t0 = 1_700_000_000_000
    for i, c in enumerate(closes):
        rows.append(
            {
                "open_time": t0 + i * 3_600_000,
                "open": c,
                "high": c + high_off,
                "low": c - low_off,
                "close": c,
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


class BannerTests(unittest.TestCase):
    def test_banner_matches_user_bot(self) -> None:
        text = boot_banner()
        self.assertIn("📊 MEXC Análise", text)
        self.assertIn("Bot iniciado", text)
        self.assertIn("BTC/USDT:USDT 1h", text)
        self.assertIn("Lev: 20x", text)
        self.assertIn("Poll: 15s", text)
        self.assertIn("Cooldown pós-STOP: 12h (sem inverter)", text)
        self.assertIn("Long: bloqueia RSI>65 ou ADX≥40", text)
        self.assertIn("1.5R (não em 1R", text)
        self.assertIn("Stop máx: 5%", text)


class SignalFilterTests(unittest.TestCase):
    def test_long_blocked_rsi_over_65(self) -> None:
        # tendência de alta forte → RSI alto
        closes = [100 + i * 2 for i in range(80)]
        sig = evaluate_signal(_df_from_closes(closes, high_off=1, low_off=0.2))
        self.assertNotEqual(sig["side"], "LONG")


class PositionTests(unittest.TestCase):
    def _long_pos(self, *, be: bool = False) -> Position:
        return Position(
            side="LONG",
            entry=100.0,
            stop=98.0,
            take=104.0,
            limit=100.0,
            filled=True,
            r=2.0,
            opened_at="2026-07-01T00:00:00+00:00",
            be_done=be,
        )

    def test_be_not_at_1r(self) -> None:
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        df = _df_from_closes([99, 100, 101])
        state = BotState(position=self._long_pos(), last_candle="1")
        # 1.0R = +2 → preço 102, ainda sem BE
        new, msgs = tick(state=state, df=df, last_price=102.0, now=now)
        self.assertTrue(new.position and not new.position.be_done)
        self.assertFalse(any("BE" in m for m in msgs))

    def test_be_at_1_5r(self) -> None:
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        df = _df_from_closes([99, 100, 101])
        state = BotState(position=self._long_pos(), last_candle="1")
        # 1.5R = +3 → preço 103
        new, msgs = tick(state=state, df=df, last_price=103.0, now=now)
        self.assertTrue(new.position and new.position.be_done)
        self.assertEqual(new.position.stop, 100.0)
        self.assertTrue(any("1.5R" in m for m in msgs))

    def test_stop_starts_12h_cooldown(self) -> None:
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        df = _df_from_closes([99, 100, 101])
        state = BotState(position=self._long_pos(), last_candle="1")
        new, msgs = tick(state=state, df=df, last_price=97.0, now=now, low=97.0, high=100.0)
        self.assertIsNone(new.position)
        self.assertIn("cooldown 12h", "".join(msgs))
        until = datetime.fromisoformat(new.cooldown_until)
        self.assertEqual(until - now, timedelta(hours=12))


if __name__ == "__main__":
    unittest.main()
