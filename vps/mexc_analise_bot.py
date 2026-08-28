#!/usr/bin/env python3
"""Daemon 📊 MEXC Análise — poll 15s, alerts Telegram, sem CCXT / sem ordem live."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.mexc_analise_bot import (  # noqa: E402
    INTERVAL,
    POLL_SEC,
    SYMBOL_CCXT,
    BotState,
    boot_banner,
    tick,
)
from lib.mexc_contract import fetch_contract_klines, fetch_contract_ticker  # noqa: E402
from lib.telegram import send  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATE_DIR = Path(os.environ.get("MEXC_ANALISE_STATE", "/data/mexc_analise"))
SYMBOL = os.environ.get("MEXC_ANALISE_SYMBOL", "BTCUSDT")


def _enabled() -> bool:
    return os.environ.get("MEXC_ANALISE_BOT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


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


def _load_state() -> BotState:
    path = STATE_DIR / "state.json"
    if not path.is_file():
        return BotState()
    try:
        return BotState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return BotState()


def _save_state(state: BotState) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "state.json").write_text(
        json.dumps(state.to_dict(), indent=2), encoding="utf-8"
    )
    (STATE_DIR / "last_ok.txt").write_text(state.last_ok or "", encoding="utf-8")


def _emit(text: str) -> None:
    print(text, flush=True)
    html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    send(f"<pre>{html}</pre>")


def run_once(state: BotState) -> BotState:
    df = fetch_contract_klines(SYMBOL, INTERVAL, limit=120)
    tick_data = fetch_contract_ticker(SYMBOL)
    last = float(tick_data.get("lastPrice") or df["close"].iloc[-1])
    now = datetime.now(timezone.utc)
    new_state, msgs = tick(state=state, df=df, last_price=last, now=now)
    for msg in msgs:
        _emit(msg)
    _save_state(new_state)
    return new_state


def main() -> int:
    _load_env()
    if not _enabled():
        logger.info("MEXC_ANALISE_BOT=0 — daemon desligado")
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _emit(boot_banner())
    state = _load_state()
    logger.info("MEXC Análise daemon %s poll=%ss", SYMBOL_CCXT, POLL_SEC)
    while True:
        try:
            state = run_once(state)
        except Exception as exc:
            logger.exception("ciclo: %s", exc)
            err = f"📊 MEXC Análise\nErro\n{type(exc).__name__}: {exc}"
            try:
                marker = STATE_DIR / "last_error_alert.txt"
                now = time.time()
                last = float(marker.read_text()) if marker.is_file() else 0.0
                if now - last > 1800:
                    _emit(err)
                    marker.write_text(str(now))
            except Exception:
                pass
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
