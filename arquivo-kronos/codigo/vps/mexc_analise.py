#!/usr/bin/env python3
"""
vps/mexc_analise.py — 📊 MEXC Análise (spot + futuros) sem CCXT.

Uso:
  python vps/mexc_analise.py              # BTC,ETH,SOL (TICKERS)
  python vps/mexc_analise.py BTC
  python vps/mexc_analise.py --telegram   # envia ao bot QUANT/monitor
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.mexc_analise import analyze_now  # noqa: E402
from lib.telegram import send  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_env() -> None:
    for env_path in (REPO_ROOT / "vps" / ".env", REPO_ROOT / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, val = line.partition("=")
            os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    p = argparse.ArgumentParser(description="MEXC Análise — spot + futures")
    p.add_argument("symbol", nargs="?", default=None, help="BTC, ETHUSDT, …")
    p.add_argument("--telegram", action="store_true", help="Envia 📊 MEXC Análise ao chat")
    args = p.parse_args()
    body = analyze_now(args.symbol)
    print(body.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    if args.telegram:
        ok = send(body)
        logger.info("Telegram %s", "OK" if ok else "FALHOU")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
