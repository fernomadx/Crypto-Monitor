"""Regras do bot 📊 MEXC Análise (banner)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from unittest.mock import patch

import pandas as pd

from lib.mexc_analise_bot import (
    BotState,
    Position,
    acquire_singleton_lock,
    boot_banner,
    evaluate_signal,
    format_signal_alert,
    notify_enabled,
    side_action,
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

    def test_notify_watchdog_silent(self) -> None:
        self.assertFalse(notify_enabled("0"))
        self.assertFalse(notify_enabled("false"))
        self.assertFalse(notify_enabled(""))
        self.assertTrue(notify_enabled(None))
        self.assertTrue(notify_enabled("1"))

    def test_singleton_lock_blocks_second(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bot.lock"
            first = acquire_singleton_lock(path)
            self.assertIsNotNone(first)
            second = acquire_singleton_lock(path)
            self.assertIsNone(second)
            first.close()
            third = acquire_singleton_lock(path)
            self.assertIsNotNone(third)
            third.close()


class SignalFilterTests(unittest.TestCase):
    def test_long_blocked_rsi_over_65(self) -> None:
        # tendência de alta forte → RSI alto
        closes = [100 + i * 2 for i in range(80)]
        sig = evaluate_signal(_df_from_closes(closes, high_off=1, low_off=0.2))
        self.assertNotEqual(sig["side"], "LONG")


class BuySellAlertTests(unittest.TestCase):
    def test_side_action_compra_venda(self) -> None:
        self.assertEqual(side_action("LONG"), "COMPRA")
        self.assertEqual(side_action("SHORT"), "VENDA")

    def test_signal_alert_says_compra(self) -> None:
        text = format_signal_alert(
            side="LONG", limit=100.0, stop=98.0, take=104.0, rsi=55.0, adx=18.0
        )
        self.assertIn("SINAL COMPRA (LONG)", text)
        self.assertIn("BTC/USDT:USDT 1h", text)
        self.assertIn("não é ordem na exchange", text)

    def test_signal_alert_says_venda(self) -> None:
        text = format_signal_alert(
            side="SHORT", limit=100.0, stop=102.0, take=96.0, rsi=45.0, adx=22.0
        )
        self.assertIn("SINAL VENDA (SHORT)", text)

    def _sig(self, side: str) -> dict:
        return {
            "side": side,
            "rsi": 55.0,
            "adx": 20.0,
            "atr": 1.0,
            "close": 100.0,
            "blocks": [],
        }

    def test_tick_emits_compra_on_long_signal(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        df = _df_from_closes([99, 100, 101])
        with patch("lib.mexc_analise_bot.evaluate_signal", return_value=self._sig("LONG")):
            new, msgs = tick(state=BotState(), df=df, last_price=100.0, now=now)
        self.assertTrue(new.position and new.position.side == "LONG")
        self.assertTrue(any("SINAL COMPRA (LONG)" in m for m in msgs))
        again, again_msgs = tick(state=new, df=df, last_price=100.5, now=now)
        self.assertFalse(any("SINAL" in m for m in again_msgs))
        self.assertEqual(again.position.side, "LONG")

    def test_tick_emits_venda_on_short_signal(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        df = _df_from_closes([101, 100, 99])
        with patch("lib.mexc_analise_bot.evaluate_signal", return_value=self._sig("SHORT")):
            new, msgs = tick(state=BotState(), df=df, last_price=100.0, now=now)
        self.assertTrue(new.position and new.position.side == "SHORT")
        self.assertTrue(any("SINAL VENDA (SHORT)" in m for m in msgs))

    def test_tick_hold_sends_nothing(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        df = _df_from_closes([100, 101, 102])
        hold = self._sig("LONG")
        hold["side"] = None
        with patch("lib.mexc_analise_bot.evaluate_signal", return_value=hold):
            new, msgs = tick(state=BotState(), df=df, last_price=102.0, now=now)
        self.assertIsNone(new.position)
        self.assertEqual(msgs, [])

    def test_fill_alert_says_compra(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        df = _df_from_closes([99, 100, 101])
        pos = Position(
            side="LONG",
            entry=100.0,
            stop=98.0,
            take=104.0,
            limit=100.0,
            filled=False,
            r=2.0,
            opened_at="2026-08-29T00:00:00+00:00",
        )
        new, msgs = tick(
            state=BotState(position=pos),
            df=df,
            last_price=99.5,
            now=now,
            low=99.5,
            high=100.5,
        )
        self.assertTrue(new.position and new.position.filled)
        self.assertTrue(any("FILL COMPRA (LONG)" in m for m in msgs))


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
