"""Journal COMBO5: entrada, saída e ranking de performance."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.combo5.journal import (
    JournalState,
    NumberedTrade,
    TradeJournal,
    format_performance_ranking,
)


def _closed_trade(
    *,
    number: int,
    symbol: str,
    result: str,
    pnl_abs: float,
    pnl_pct: float,
    closed_at: datetime,
    side: str = "LONG",
) -> NumberedTrade:
    return NumberedTrade(
        number=number,
        symbol=symbol,
        side=side,
        status="CLOSED",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        qty=10.0,
        opened_at=(closed_at - timedelta(hours=4)).isoformat(),
        opened_at_local_note="n/d",
        exit_price=101.0,
        closed_at=closed_at.isoformat(),
        result=result,
        exit_reason="take_profit" if result == "GAIN" else "stop_loss",
        pnl_pct=pnl_pct,
        pnl_abs=pnl_abs,
        outcome_explanation="teste",
    )


class Combo5JournalTests(unittest.TestCase):
    def test_open_and_close_include_entry_exit_and_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = TradeJournal(Path(tmp) / "journal.json")
            opened, entry_msg = journal.open_trade(
                symbol="BTCUSDT",
                side="LONG",
                price=100.0,
                stop=98.0,
                take_profit=104.0,
                qty=10.0,
                entry_reasons=["Kronos ALIGN_BULL"],
                kronos_bias="BULL",
                strength_pct=1.2,
                confidence=0.8,
            )
            self.assertEqual(opened.number, 1)
            self.assertIn("ENTRADA Nº 1", entry_msg)
            self.assertIn("BTCUSDT", entry_msg)

            closed, exit_msg = journal.close_trade(
                symbol="BTCUSDT",
                exit_price=104.0,
                exit_reason="take_profit",
            )
            self.assertEqual(closed.result, "GAIN")
            self.assertIn("FECHAMENTO — ENTRADA Nº 1", exit_msg)
            self.assertIn("Ranking COMBO5", exit_msg)
            self.assertIn("Por par (tudo):", exit_msg)
            self.assertIn("BTCUSDT", exit_msg)

    def test_ranking_windows_by_closed_at(self) -> None:
        now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        recent = _closed_trade(
            number=2,
            symbol="ETHUSDT",
            result="GAIN",
            pnl_abs=20.0,
            pnl_pct=2.0,
            closed_at=now - timedelta(days=3),
        )
        older = _closed_trade(
            number=1,
            symbol="BTCUSDT",
            result="LOSS",
            pnl_abs=-10.0,
            pnl_pct=-1.0,
            closed_at=now - timedelta(days=20),
        )
        state = JournalState(
            next_number=3,
            closed_trades=[older, recent],
        )
        text = format_performance_ranking(state, now=now)
        self.assertIn("7 dias: 1 fecha.", text)
        self.assertIn("30 dias: 2 fecha.", text)
        self.assertIn("Tudo: 2 fecha.", text)
        self.assertIn("ETHUSDT: 1 · 100% · +20.00 USDT", text)
        self.assertIn("BTCUSDT: 1 · 0% · -10.00 USDT", text)
        eth_pos = text.index("ETHUSDT:")
        btc_pos = text.index("BTCUSDT:")
        self.assertLess(eth_pos, btc_pos)

    def test_ranking_lists_open_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = TradeJournal(Path(tmp) / "journal.json")
            journal.open_trade(
                symbol="BTCUSDT",
                side="LONG",
                price=100.0,
                stop=98.0,
                take_profit=104.0,
                qty=10.0,
                entry_reasons=["teste"],
                kronos_bias="BULL",
                strength_pct=1.0,
                confidence=0.7,
            )
            body = format_performance_ranking(journal.state)
            self.assertIn("Ranking COMBO5", body)
            self.assertIn("Abertos agora: 1", body)
            self.assertIn("Nº 1 BTCUSDT LONG", body)
            self.assertIn("Tudo: ainda sem trades fechados", body)


if __name__ == "__main__":
    unittest.main()
