#!/usr/bin/env python3
"""Testes unitários do webhook URL + dispatch do quant_bot (sem Telegram)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vps.quant_bot import _dispatch, webhook_public_url  # noqa: E402


class WebhookUrlTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "QUANT_WEBHOOK_URL",
            "RAILWAY_PUBLIC_DOMAIN",
            "RAILWAY_STATIC_URL",
        ):
            os.environ.pop(key, None)

    def test_empty_without_domain(self) -> None:
        self.assertEqual(webhook_public_url(), "")

    def test_railway_domain(self) -> None:
        os.environ["RAILWAY_PUBLIC_DOMAIN"] = "crypto.up.railway.app"
        self.assertEqual(
            webhook_public_url(), "https://crypto.up.railway.app/telegram"
        )

    def test_explicit_url_appends_path(self) -> None:
        os.environ["QUANT_WEBHOOK_URL"] = "https://example.com"
        self.assertEqual(webhook_public_url(), "https://example.com/telegram")

    def test_http_upgraded_to_https(self) -> None:
        os.environ["QUANT_WEBHOOK_URL"] = "http://example.com/telegram"
        self.assertEqual(webhook_public_url(), "https://example.com/telegram")


class DispatchTests(unittest.TestCase):
    def test_help_and_unknown(self) -> None:
        help_text = _dispatch("/help")
        self.assertIn("QUANT", help_text)
        self.assertEqual(_dispatch("/nope"), help_text)

    def test_ping_mentions_combo5(self) -> None:
        sys.modules.setdefault("feedparser", mock.MagicMock())
        with mock.patch.dict(
            os.environ,
            {"QUANT_KRONOS_MODE": "warn", "QUANT_IMPACT_THRESHOLD": "0.70"},
            clear=False,
        ):
            with mock.patch("lib.llmquant_client.configured", return_value=False):
                body = _dispatch("/ping")
        self.assertIn("QUANT online", body)
        self.assertIn("/combo5", body)
        self.assertIn("/c5score", body)


class Combo5RankingDispatchTests(unittest.TestCase):
    def test_help_mentions_combo5_ranking(self) -> None:
        help_text = _dispatch("/help")
        self.assertIn("/combo5 ranking", help_text)
        self.assertIn("/c5score", help_text)

    def test_combo5_ranking_does_not_call_analyze(self) -> None:
        ranking = "📊 Ranking COMBO5 (paper)\nTudo: ainda sem trades fechados"
        fake = mock.MagicMock()
        fake.ranking_now.return_value = ranking
        fake.analyze_now.side_effect = AssertionError("analyze_now não deve rodar")
        with mock.patch.dict(sys.modules, {"vps.combo5_signal": fake}):
            for cmd in (
                "/combo5 ranking",
                "/combo5 rank",
                "/combo5 performance",
                "/c5score",
                "/combo5ranking",
            ):
                with self.subTest(cmd=cmd):
                    fake.analyze_now.reset_mock()
                    body = _dispatch(cmd)
                    fake.analyze_now.assert_not_called()
                    self.assertIn("Ranking COMBO5", body)
                    self.assertIn("[COMBO5]", body)

    def test_combo5_ticker_still_analyzes(self) -> None:
        fake = mock.MagicMock()
        fake.analyze_now.return_value = "análise BTCUSDT"
        fake.ranking_now.side_effect = AssertionError("ranking_now não deve rodar")
        with mock.patch.dict(sys.modules, {"vps.combo5_signal": fake}):
            body = _dispatch("/combo5 BTC")
        fake.analyze_now.assert_called_once_with("BTC")
        self.assertIn("análise BTCUSDT", body)


class HttpTests(unittest.TestCase):
    def test_health_endpoint(self) -> None:
        from vps.quant_bot import _start_http

        server = _start_http(18765)
        self.assertIsNotNone(server)
        try:
            import urllib.request

            with urllib.request.urlopen("http://127.0.0.1:18765/health", timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.read(), b"quant-bot ok\n")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
