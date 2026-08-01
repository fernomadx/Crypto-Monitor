#!/usr/bin/env python3
"""
vps/trade_desk_signal.py — Roda a mesa multi-agente sozinha (cron) e manda [DESK] no Telegram.

Usa os mesmos tickers/timeframes do Kronos. Pode rodar junto do cron Kronos
(depois do sinal) ou independente.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.trade_desk import evaluate_symbol, format_desk_section  # noqa: E402
from lib.telegram import send_kronos_alert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def resolve_symbols() -> list[str]:
    if os.environ.get("KRONOS_TICKERS"):
        raw = os.environ["KRONOS_TICKERS"]
    else:
        raw = os.environ.get("TICKERS", "BTC,ETH,SOL")
    out = []
    for part in raw.split(","):
        t = part.strip().upper()
        if not t:
            continue
        out.append(t if t.endswith("USDT") else f"{t}USDT")
    return out


def main(tf: str = "1h") -> None:
    if os.environ.get("TRADE_DESK_ENABLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("TRADE_DESK_ENABLED=0 — saindo")
        return

    symbols = resolve_symbols()
    verdicts = []
    for symbol in symbols:
        v = evaluate_symbol(symbol=symbol, interval=tf, kronos_result=None)
        verdicts.append(v)
        logger.info("%s -> %s conf=%.2f", symbol, v.side.value, v.confidence)

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    body = format_desk_section(verdicts) or "Sem veredictos"
    body += f"\n\n<i>TF={tf} · standalone desk (sem forecast Kronos neste ciclo)</i>"
    send_kronos_alert(f"Trade Desk — {now}", body)
    logger.info("Alerta [DESK] enviado")


if __name__ == "__main__":
    # Load vps/.env if present
    env_path = REPO_ROOT / "vps" / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, val = line.partition("=")
            os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))

    parser = argparse.ArgumentParser()
    parser.add_argument("--tf", default=os.environ.get("TRADE_DESK_TF", "1h"), choices=["1h", "4h", "1d"])
    args = parser.parse_args()
    try:
        main(tf=args.tf)
    except Exception as exc:
        logger.exception("trade_desk_signal falhou: %s", exc)
        try:
            send_kronos_alert("Trade Desk erro", str(exc)[:400])
        except Exception:
            pass
        sys.exit(1)