#!/usr/bin/env python3
"""Kronos paper só no Railway — Hetzner/GHA/local não disparam."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_config import kronos_allowed_here, require_railway_or_exit  # noqa: E402


class KronosRuntimeTests(unittest.TestCase):
    def test_railway_allowed(self) -> None:
        with mock.patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "production"}, clear=False):
            os.environ.pop("KRONOS_ALLOW_LOCAL", None)
            self.assertTrue(kronos_allowed_here())

    def test_hetzner_blocked(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in {"RAILWAY_ENVIRONMENT", "KRONOS_ALLOW_LOCAL"}}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(kronos_allowed_here())
            with self.assertRaises(SystemExit) as ctx:
                require_railway_or_exit()
            self.assertEqual(ctx.exception.code, 0)

    def test_local_opt_in(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "RAILWAY_ENVIRONMENT"}
        env["KRONOS_ALLOW_LOCAL"] = "1"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(kronos_allowed_here())


if __name__ == "__main__":
    unittest.main()
