"""Formatação da MEXC Análise (sem rede)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from lib.mexc_analise import MexcReport, TfSlice, _bias_from_slices, format_telegram, resolve_symbols


class MexcAnaliseTests(unittest.TestCase):
    def test_resolve_symbols(self) -> None:
        self.assertEqual(resolve_symbols("BTC"), ["BTCUSDT"])
        self.assertEqual(resolve_symbols("eth,sol"), ["ETHUSDT", "SOLUSDT"])

    def test_bias_prefers_4h(self) -> None:
        slices = [
            TfSlice("1h", "futures", 1.0, 0.1, 55.0, "BUY", "EMA12>EMA26"),
            TfSlice("4h", "futures", 1.0, 1.0, 62.0, "BUY", "EMA12>EMA26"),
        ]
        bias, reasons = _bias_from_slices(slices, funding=0.00006, basis=-0.02)
        self.assertEqual(bias, "ALTA")
        self.assertTrue(any("funding calmo" in r for r in reasons))

    def test_format_includes_header(self) -> None:
        report = MexcReport(
            symbol="BTC",
            spot=81140.19,
            futures=81097.1,
            basis_pct=-0.053,
            change_24h_pct=1.02,
            high_24h=81145.0,
            low_24h=78524.8,
            funding_rate=0.000062,
            next_settle_utc="08:00 UTC",
            hold_vol=1.0,
            slices=[
                TfSlice("1h", "futures", 81130.0, 0.2, 58.0, "BUY", "EMA12>EMA26"),
                TfSlice("4h", "futures", 81126.9, 1.1, 54.0, "HOLD", "meio"),
            ],
            bias="NEUTRO",
            reasons=["1H futures EMA12>EMA26"],
        )
        html = format_telegram(report, now=datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc))
        self.assertIn("📊 <b>MEXC Análise</b>", html)
        self.assertIn("BTC", html)
        self.assertIn("Funding", html)
        self.assertIn("08:00 UTC", html)


if __name__ == "__main__":
    unittest.main()
