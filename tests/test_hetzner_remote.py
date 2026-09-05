#!/usr/bin/env python3
"""Testes do heal Hetzner (sem SSH real)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vps import hetzner_remote  # noqa: E402


class HealRoutingTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in ("VPS_HOST", "VPS_ATLAS_HOST"):
            os.environ.pop(key, None)

    def test_default_hosts(self) -> None:
        os.environ.pop("VPS_HOST", None)
        os.environ.pop("VPS_ATLAS_HOST", None)
        with mock.patch("lib.vps_config.get_host", return_value=""):
            self.assertEqual(
                hetzner_remote.default_btccursor_host(),
                hetzner_remote.DEFAULT_BTCCURSOR_HOST,
            )
        self.assertEqual(
            hetzner_remote.default_atlas_host(),
            hetzner_remote.DEFAULT_ATLAS_HOST,
        )

    def test_heal_all_runs_both_hosts(self) -> None:
        with mock.patch.object(
            hetzner_remote, "sync_and_test", return_value="BTCCURSOR-OK"
        ) as sync, mock.patch.object(
            hetzner_remote, "heal_atlas", return_value="ATLAS-OK"
        ) as atlas:
            body = hetzner_remote.heal_all()
        sync.assert_called_once_with(hetzner_remote.DEFAULT_BTCCURSOR_HOST)
        atlas.assert_called_once_with(hetzner_remote.DEFAULT_ATLAS_HOST)
        self.assertIn("BTCCURSOR-OK", body)
        self.assertIn("ATLAS-OK", body)

    def test_auth_hint_only_on_auth_failure(self) -> None:
        ok_text = hetzner_remote._format_host_result(
            "BTCCURSOR", "204.168.179.200", 1, "=== RESULTADO: 1 problema(s)", ""
        )
        self.assertIn("SSH autenticou", ok_text)
        self.assertNotIn("SSH recusado", ok_text)

        auth_text = hetzner_remote._format_host_result(
            "ATLAS", "77.42.126.222", 1, "", "Authentication failed"
        )
        self.assertIn("SSH recusado", auth_text)

    def test_bootstrap_heals_combo5_and_http(self) -> None:
        self.assertIn("hetzner-heal-bots.sh", hetzner_remote.REMOTE_BOOTSTRAP)
        self.assertIn("hetzner-heal-204.sh", hetzner_remote.REMOTE_BOOTSTRAP)
        self.assertIn("hetzner_disable_kronos.sh", hetzner_remote.REMOTE_BOOTSTRAP)


if __name__ == "__main__":
    unittest.main()
