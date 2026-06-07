"""
Níveis de trade Kronos: alvo (take profit) e stop com R:R mínimo.

Regra: |alvo| >= MIN_RR × |stop| sempre (ex. R:R 2:1 → alvo 2× o stop).
Se o modelo não prevê edge suficiente → sem trade.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd

MIN_TARGET_PCT = float(os.environ.get("KRONOS_MIN_TARGET_PCT", "0.5"))
MIN_RR = float(os.environ.get("KRONOS_MIN_RR", "2.0"))
MAX_STOP_PCT = float(os.environ.get("KRONOS_MAX_STOP_PCT", "1.5"))


def max_stop_pct_for_interval(interval: str) -> float:
    iv = interval.lower()
    env_key = f"KRONOS_MAX_STOP_PCT_{iv.upper()}"
    if os.environ.get(env_key):
        return float(os.environ[env_key])
    defaults = {"4h": 1.8, "1h": 1.5, "1d": 2.5}
    return float(os.environ.get("KRONOS_MAX_STOP_PCT", str(defaults.get(iv, MAX_STOP_PCT))))


@dataclass(frozen=True)
class TradeLevels:
    target: float
    stop: float
    target_pct: float
    stop_pct: float
    rr: float
    target_bars: int


def _pct_move(entry: float, price: float) -> float:
    return (price - entry) / entry * 100.0


def _risk_from_reward(reward: float, entry: float, min_rr: float, stop_cap_pct: float) -> float | None:
    """Stop = alvo / MIN_RR. Rejeita se stop exceder teto do timeframe."""
    if reward <= 0 or min_rr <= 0:
        return None
    risk = reward / min_rr
    cap = entry * stop_cap_pct / 100.0
    if risk > cap + 1e-12:
        return None
    return risk


def compute_trade_levels(
    *,
    entry: float,
    pred_df: pd.DataFrame,
    bias: str,
    target_bar_index: int,
    interval: str = "4h",
    min_target_pct: float = MIN_TARGET_PCT,
    min_rr: float = MIN_RR,
    max_stop_pct: float | None = None,
) -> TradeLevels | None:
    """
    Define alvo e stop a favor do viés.
    - Alvo: movimento do modelo (limitado a stop_cap × R:R).
    - Stop: exatamente alvo / MIN_RR (nunca maior que o alvo).
    """
    if bias == "NEUTRO" or entry <= 0 or pred_df.empty:
        return None

    stop_cap = max_stop_pct if max_stop_pct is not None else max_stop_pct_for_interval(interval)
    max_move = stop_cap * min_rr

    idx = min(max(target_bar_index, 0), len(pred_df) - 1)
    raw_target = float(pred_df["close"].iloc[idx])
    long_target = float(pred_df["close"].iloc[-1])
    raw_pct = _pct_move(entry, raw_target)
    long_pct = _pct_move(entry, long_target)

    if bias == "BULLISH" and raw_pct < 0 and long_pct < 0:
        return None
    if bias == "BEARISH" and raw_pct > 0 and long_pct > 0:
        return None

    if bias == "BULLISH":
        natural = max(raw_pct, long_pct)
        if natural < min_target_pct:
            return None
        move_pct = min(natural, max_move)
        if move_pct < min_target_pct:
            return None
        target = entry * (1 + move_pct / 100.0)
        reward = target - entry
        risk = _risk_from_reward(reward, entry, min_rr, stop_cap)
        if risk is None:
            return None
        stop = entry - risk
        stop_pct = -risk / entry * 100.0
        target_pct = move_pct
    else:
        natural = min(raw_pct, long_pct)
        if natural > -min_target_pct:
            return None
        move_pct = max(natural, -max_move)
        if move_pct > -min_target_pct:
            return None
        target = entry * (1 + move_pct / 100.0)
        reward = entry - target
        risk = _risk_from_reward(reward, entry, min_rr, stop_cap)
        if risk is None:
            return None
        stop = entry + risk
        stop_pct = risk / entry * 100.0
        target_pct = move_pct

    rr = (reward / risk) if risk > 0 else 0.0
    if rr < min_rr - 0.05:
        return None

    return TradeLevels(
        target=target,
        stop=stop,
        target_pct=round(target_pct, 3),
        stop_pct=round(stop_pct, 3),
        rr=round(rr, 2),
        target_bars=idx + 1,
    )


def compute_stop_from_target(
    entry: float,
    target: float,
    bias: str,
    min_rr: float = MIN_RR,
    max_stop_pct: float = MAX_STOP_PCT,
) -> float | None:
    """Recalcula stop a partir de entrada/alvo gravados (previsões antigas)."""
    if bias == "NEUTRO" or entry <= 0:
        return None
    if bias == "BULLISH":
        reward = target - entry
        if reward <= 0:
            return None
        risk = _risk_from_reward(reward, entry, min_rr, max_stop_pct)
        return None if risk is None else entry - risk
    reward = entry - target
    if reward <= 0:
        return None
    risk = _risk_from_reward(reward, entry, min_rr, max_stop_pct)
    return None if risk is None else entry + risk


def limit_entry_price(last_close: float, bias: str) -> float:
    """Entrada limite com pequeno pullback (long abaixo, short acima)."""
    offset = float(os.environ.get("KRONOS_LIMIT_ENTRY_OFFSET_PCT", "0.15")) / 100.0
    if bias == "BULLISH":
        return last_close * (1 - offset)
    if bias == "BEARISH":
        return last_close * (1 + offset)
    return last_close


def pct_from_entry(entry: float, price: float, bias: str) -> float:
    """% assinado da entrada até o preço (alvo/stop)."""
    pct = _pct_move(entry, price)
    if bias == "BEARISH":
        return -pct if price < entry else pct
    return pct
