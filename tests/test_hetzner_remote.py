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
        else_branch = hetzner_remote.REMOTE_BOOTSTRAP.split("else", 1)[1]
        disable_at = else_branch.find("hetzner_disable_kronos.sh")
        bots_at = else_branch.find("hetzner-heal-bots.sh")
        self.assertGreater(disable_at, -1)
        self.assertGreater(bots_at, -1)
        self.assertLess(disable_at, bots_at)
        self.assertIn("hetzner-heal-bots.sh | bash || true", else_branch)

    def test_default_btccursor_ignores_persisted_atlas(self) -> None:
        os.environ.pop("VPS_HOST", None)
        with mock.patch("lib.vps_config.get_host", return_value="77.42.126.222"):
            self.assertEqual(
                hetzner_remote.default_btccursor_host(),
                hetzner_remote.DEFAULT_BTCCURSOR_HOST,
            )
        os.environ["VPS_HOST"] = "77.42.126.222"
        self.assertEqual(
            hetzner_remote.default_btccursor_host(),
            hetzner_remote.DEFAULT_BTCCURSOR_HOST,
        )

    def test_sync_and_test_routes_atlas_to_heal_atlas(self) -> None:
        with mock.patch.object(
            hetzner_remote, "heal_atlas", return_value="ATLAS-ONLY"
        ) as atlas, mock.patch.object(hetzner_remote, "ssh_run") as ssh:
            body = hetzner_remote.sync_and_test("77.42.126.222")
        self.assertEqual(body, "ATLAS-ONLY")
        atlas.assert_called_once_with("77.42.126.222")
        ssh.assert_not_called()

    def test_is_atlas_host(self) -> None:
        self.assertTrue(hetzner_remote.is_atlas_host("atlas"))
        self.assertTrue(hetzner_remote.is_atlas_host("77"))
        self.assertTrue(hetzner_remote.is_atlas_host(hetzner_remote.DEFAULT_ATLAS_HOST))
        self.assertFalse(hetzner_remote.is_atlas_host(hetzner_remote.DEFAULT_BTCCURSOR_HOST))
        self.assertFalse(hetzner_remote.is_atlas_host(""))
        os.environ["VPS_ATLAS_HOST"] = "10.0.0.77"
        self.assertTrue(hetzner_remote.is_atlas_host("10.0.0.77"))

    def test_heal_204_does_not_restart_legacy_ccxt(self) -> None:
        script = (REPO_ROOT / "scripts" / "hetzner-heal-204.sh").read_text()
        self.assertIn(
            "for svc in nginx caddy streamlit crypto-web crypto-dashboard; do",
            script,
        )
        self.assertNotIn("crypto-chart-analyzer", script)
        self.assertNotRegex(script, r"grep -iE '[^']*\|chart")

    def test_heal_bots_crontab_drops_kronos(self) -> None:
        script = (REPO_ROOT / "scripts" / "hetzner-heal-bots.sh").read_text()
        self.assertIn("kronos|run_kronos", script)


if __name__ == "__main__":
    unittest.main()
