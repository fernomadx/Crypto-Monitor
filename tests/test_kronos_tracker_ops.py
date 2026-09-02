#!/usr/bin/env python3
"""Scorecard Kronos: timestamps sem pandas, snapshot em texto."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_tracker import (  # noqa: E402
    _bars_delta,
    _parse_utc,
    write_scorecard_snapshot,
)


class ParseUtcTests(unittest.TestCase):
    def test_iso_z(self) -> None:
        ts = _parse_utc("2026-09-02T00:15:00Z")
        self.assertEqual(ts.tzinfo, timezone.utc)
        self.assertEqual(ts.hour, 0)
        self.assertEqual(ts.minute, 15)

    def test_naive_assumes_utc(self) -> None:
        ts = _parse_utc("2026-09-02T12:00:00")
        self.assertEqual(ts.tzinfo, timezone.utc)
        self.assertEqual(ts.hour, 12)

    def test_datetime_passthrough(self) -> None:
        src = datetime(2026, 8, 30, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(_parse_utc(src), src)


class BarsDeltaTests(unittest.TestCase):
    def test_4h_bars(self) -> None:
        self.assertEqual(_bars_delta("4h", 1).total_seconds(), 4 * 3600)
        self.assertEqual(_bars_delta("1h", 4).total_seconds(), 4 * 3600)


class SnapshotTests(unittest.TestCase):
    def test_strips_html_and_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "score.txt"
            write_scorecard_snapshot("<b>7 dias</b>: <i>ok</i>", dest)
            text = dest.read_text(encoding="utf-8")
            self.assertIn("7 dias: ok", text)
            self.assertNotIn("<b>", text)


class NoPandasImportTests(unittest.TestCase):
    def test_tracker_source_has_no_pandas(self) -> None:
        src = (REPO_ROOT / "lib" / "kronos_tracker.py").read_text(encoding="utf-8")
        self.assertNotIn("import pandas", src)
        self.assertNotIn("from pandas", src)


if __name__ == "__main__":
    unittest.main()
