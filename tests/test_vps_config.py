#!/usr/bin/env python3
"""Slots de sync BTCCURSOR vs ATLAS e routing /vps."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import vps_config  # noqa: E402
from vps.quant_bot import _handle_vps  # noqa: E402


class RecordSyncSlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._old = vps_config.CONFIG_PATH
        vps_config.CONFIG_PATH = Path(self._tmp.name)
        os.environ.pop("VPS_HOST", None)
        os.environ.pop("VPS_ATLAS_HOST", None)
        os.environ.pop("VPS_SSH_PRIVATE_KEY", None)

    def tearDown(self) -> None:
        vps_config.CONFIG_PATH = self._old
        Path(self._tmp.name).unlink(missing_ok=True)
        os.environ.pop("VPS_HOST", None)
        os.environ.pop("VPS_ATLAS_HOST", None)
        os.environ.pop("VPS_SSH_PRIVATE_KEY", None)

    def test_atlas_does_not_overwrite_btccursor_slot(self) -> None:
        vps_config.record_sync(ok=False, summary="204 falhou", host="204.168.179.200")
        vps_config.record_sync(ok=True, summary="77 ok", host="77.42.126.222")
        data = vps_config.load()
        self.assertFalse(data["last_sync_btccursor_ok"])
        self.assertTrue(data["last_sync_atlas_ok"])
        text = vps_config.status_text()
        self.assertIn("BTCCURSOR", text)
        self.assertIn("ATLAS", text)
        self.assertIn("204 falhou", text)
        self.assertIn("77 ok", text)
        self.assertIn("❌", text)
        self.assertIn("✅", text)


class HandleVpsRoutingTests(unittest.TestCase):
    def test_atlas_ip_does_not_set_btccursor_host(self) -> None:
        with mock.patch("vps.hetzner_remote.heal_atlas", return_value="ATLAS-ONLY") as atlas, mock.patch(
            "vps.hetzner_remote.sync_and_test"
        ) as sync, mock.patch("lib.vps_config.set_host") as set_host:
            body = _handle_vps("77.42.126.222")
        self.assertEqual(body, "ATLAS-ONLY")
        atlas.assert_called_once_with("77.42.126.222")
        sync.assert_not_called()
        set_host.assert_not_called()

    def test_btccursor_ip_still_syncs(self) -> None:
        with mock.patch("vps.hetzner_remote.heal_atlas") as atlas, mock.patch(
            "vps.hetzner_remote.sync_and_test", return_value="BTC-OK"
        ) as sync, mock.patch("lib.vps_config.set_host") as set_host:
            body = _handle_vps("204.168.179.200")
        self.assertEqual(body, "BTC-OK")
        sync.assert_called_once_with("204.168.179.200")
        set_host.assert_called_once_with("204.168.179.200")
        atlas.assert_not_called()


if __name__ == "__main__":
    unittest.main()
