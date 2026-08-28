"""Intervalos e erros da API de futuros MEXC."""

from __future__ import annotations

import unittest

from lib.mexc_contract import _contract_error, contract_interval, contract_symbol


class ContractIntervalTests(unittest.TestCase):
    def test_4h_is_hour4_not_min240(self) -> None:
        self.assertEqual(contract_interval("4h"), "Hour4")
        self.assertEqual(contract_interval("4H"), "Hour4")
        self.assertEqual(contract_interval("Min240"), "Hour4")

    def test_1h_stays_min60(self) -> None:
        self.assertEqual(contract_interval("1h"), "Min60")
        self.assertEqual(contract_interval("60m"), "Min60")

    def test_symbol_underscore(self) -> None:
        self.assertEqual(contract_symbol("BTCUSDT"), "BTC_USDT")
        self.assertEqual(contract_symbol("BTC_USDT"), "BTC_USDT")

    def test_code_600_is_error(self) -> None:
        err = _contract_error({"success": False, "code": 600, "message": "Parameter error"})
        self.assertIsNotNone(err)
        self.assertIn("600", err or "")
        self.assertIn("Parameter error", err or "")

    def test_success_code_0(self) -> None:
        self.assertIsNone(_contract_error({"success": True, "code": 0, "data": {"time": [1]}}))


if __name__ == "__main__":
    unittest.main()
