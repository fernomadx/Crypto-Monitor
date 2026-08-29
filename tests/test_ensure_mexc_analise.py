"""Watchdog 📊 MEXC Análise — não relança se o daemon já está no ar."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENSURE = REPO_ROOT / "vps" / "ensure_mexc_analise.sh"


def _matching_pids(marker: str) -> list[str]:
    pids: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return pids
    for dirent in proc.iterdir():
        if not dirent.name.isdigit():
            continue
        cmdline = dirent / "cmdline"
        try:
            raw = cmdline.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if marker in raw:
            pids.append(dirent.name)
    return pids


def _run_ensure(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ENSURE)],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


class EnsureMexcAnaliseTests(unittest.TestCase):
    def test_second_ensure_does_not_spawn_another(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bot = tmp_path / "mexc_analise_bot.py"
            bot.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
            log = tmp_path / "daemon.log"
            env = {
                **os.environ,
                "BOT": str(bot),
                "PYTHON": sys.executable,
                "MEXC_ANALISE_BOT": "1",
                "MEXC_ANALISE_STATE": str(tmp_path / "state"),
                "MEXC_ANALISE_LOG": str(log),
                "MEXC_ANALISE_NOTIFY": "0",
            }
            marker = str(bot)
            spawned: list[str] = []
            try:
                first = _run_ensure(env)
                self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
                self.assertIn("iniciado pid", first.stdout)
                time.sleep(0.3)
                spawned = _matching_pids(marker)
                self.assertEqual(len(spawned), 1, spawned)

                second = _run_ensure(env)
                self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
                self.assertIn("já rodando", second.stdout)
                self.assertNotIn("iniciado pid", second.stdout)
                time.sleep(0.2)
                self.assertEqual(_matching_pids(marker), spawned)
            finally:
                for pid in _matching_pids(marker):
                    try:
                        os.kill(int(pid), 9)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
