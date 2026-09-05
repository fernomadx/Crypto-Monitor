#!/usr/bin/env python3
"""Testes unitários do webhook URL + dispatch do quant_bot (sem Telegram)."""
from __future__ import annotations

import os
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vps.quant_bot import GET_UPDATES_LONG_POLL_SEC, _dispatch, get_updates_http_timeout, webhook_public_url  # noqa: E402


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


class HttpTests(unittest.TestCase):
    def test_health_endpoint(self) -> None:
        from vps.quant_bot import _start_http

        server = _start_http(18765)
        self.assertIsNotNone(server)
        try:
            with urllib.request.urlopen("http://127.0.0.1:18765/health", timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.read(), b"quant-bot ok\n")
            with urllib.request.urlopen("http://127.0.0.1:18765/ping", timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.read(), b"quant-bot ok\n")
            try:
                urllib.request.urlopen("http://127.0.0.1:18765/telegram", timeout=2)
                self.fail("GET /telegram should be 405")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 405)
        finally:
            server.shutdown()
            server.server_close()


class GetUpdatesTimeoutTests(unittest.TestCase):
    def test_http_read_exceeds_telegram_long_poll(self) -> None:
        _connect, read = get_updates_http_timeout()
        self.assertGreater(read, GET_UPDATES_LONG_POLL_SEC)
        self.assertGreaterEqual(_connect, 1)


if __name__ == "__main__":
    unittest.main()
