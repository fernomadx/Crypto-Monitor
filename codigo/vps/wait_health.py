#!/usr/bin/env python3
"""Espera /health no PORT antes do supercronic (healthcheck Railway)."""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request


def _port() -> int:
    raw = os.environ.get("PORT", "8080").strip()
    return int(raw) if raw.isdigit() else 8080


def main() -> int:
    port = _port()
    for i in range(25):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                if resp.status == 200:
                    print(f"wait_health: ok :{port} ({i + 1}s)", flush=True)
                    return 0
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(1)
    print(f"wait_health: timeout :{port} — seguindo mesmo assim", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
