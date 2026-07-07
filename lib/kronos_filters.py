"""Filtros opcionais de entrada Kronos (Donchian, etc.)."""

from __future__ import annotations

import os

import pandas as pd

from lib.mexc_klines import fetch_klines


def donchian_bias(symbol: str, interval: str = "4h", bars: int | None = None, limit: int = 80) -> str:
    """
    Breakout Donchian: close >= máxima N barras → BULLISH; <= mínima → BEARISH.
    Inspirado em Jesse/Harvest — melhor modo no grid-search v5.
    """
    n = bars or int(os.environ.get("KRONOS_DONCHIAN_BARS", "20"))
    df = fetch_klines(symbol, interval, limit)
    if len(df) < n + 2:
        return "NEUTRO"
    window = df.iloc[-(n + 1) : -1]
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    close = float(df["close"].iloc[-1])
    if close >= hi:
        return "BULLISH"
    if close <= lo:
        return "BEARISH"
    return "NEUTRO"


def breakout_confirms(bias: str, symbol: str, interval: str = "4h") -> tuple[bool, str]:
    """True se Donchian confirma ou está neutro (sem breakout oposto)."""
    if bias not in ("BULLISH", "BEARISH"):
        return False, "sem viés"
    d = donchian_bias(symbol, interval)
    if d == "NEUTRO":
        return True, "Donchian neutro — OK"
    if d == bias:
        return True, f"Donchian confirma {bias}"
    return False, f"Donchian {d} contradiz {bias}"


def apply_breakout_filter(result: dict) -> None:
    """Ajusta tradeable se KRONOS_BREAKOUT_FILTER=1."""
    if os.environ.get("KRONOS_BREAKOUT_FILTER", "0").strip() not in ("1", "true", "yes"):
        return
    if not result.get("tradeable"):
        return
    ok, note = breakout_confirms(result.get("bias", ""), result.get("symbol", ""), result.get("interval", "4h"))
    if not ok:
        result["tradeable"] = False
        prev = result.get("align_note") or ""
        result["align_note"] = f"{prev} | breakout: {note}".strip(" |")
