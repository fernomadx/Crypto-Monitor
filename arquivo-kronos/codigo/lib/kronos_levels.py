"""
Níveis de trade Kronos: alvo (take profit) e stop com R:R mínimo.

Viés continua no horizonte curto; alvo de operação usa mais barras e
distância mínima em % para evitar alvo minúsculo com risco grande no vencimento.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd

MIN_TARGET_PCT = float(os.environ.get("KRONOS_MIN_TARGET_PCT", "0.5"))
MIN_RR = float(os.environ.get("KRONOS_MIN_RR", "1.5"))
MAX_STOP_PCT = float(os.environ.get("KRONOS_MAX_STOP_PCT", "1.2"))


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


def compute_trade_levels(
    *,
    entry: float,
    pred_df: pd.DataFrame,
    bias: str,
    target_bar_index: int,
    min_target_pct: float = MIN_TARGET_PCT,
    min_rr: float = MIN_RR,
    max_stop_pct: float = MAX_STOP_PCT,
) -> TradeLevels | None:
    """
    Define alvo e stop a favor do viés.
    - Alvo: close previsto na barra target_bar_index, com piso de min_target_pct.
    - Stop: distância = alvo/min_rr (R:R mínimo), teto max_stop_pct.
    """
    if bias == "NEUTRO" or entry <= 0 or pred_df.empty:
        return None

    idx = min(max(target_bar_index, 0), len(pred_df) - 1)
    raw_target = float(pred_df["close"].iloc[idx])
    long_target = float(pred_df["close"].iloc[-1])
    raw_pct = _pct_move(entry, raw_target)
    long_pct = _pct_move(entry, long_target)

    # Modelo prevê movimento oposto no horizonte do alvo → sem trade
    if bias == "BULLISH" and raw_pct < 0 and long_pct < 0:
        return None
    if bias == "BEARISH" and raw_pct > 0 and long_pct > 0:
        return None

    if bias == "BULLISH":
        move_pct = max(_pct_move(entry, raw_target), _pct_move(entry, long_target), min_target_pct)
        move_pct = min(move_pct, max_stop_pct * min_rr)
        target = entry * (1 + move_pct / 100.0)
        reward = target - entry
        risk = min(reward / min_rr, entry * max_stop_pct / 100.0)
        stop = entry - risk
        stop_pct = -risk / entry * 100.0
        target_pct = move_pct
    else:
        p_raw = _pct_move(entry, raw_target)
        p_long = _pct_move(entry, long_target)
        move_pct = min(p_raw, p_long)
        if move_pct > -min_target_pct:
            move_pct = -min_target_pct
        move_pct = max(move_pct, -max_stop_pct * min_rr)
        target = entry * (1 + move_pct / 100.0)
        reward = entry - target
        risk = min(reward / min_rr, entry * max_stop_pct / 100.0)
        stop = entry + risk
        stop_pct = risk / entry * 100.0
        target_pct = move_pct

    rr = (reward / risk) if risk > 0 else 0.0
    return TradeLevels(
        target=target,
        stop=stop,
        target_pct=round(target_pct, 3),
        stop_pct=round(stop_pct, 3),
        rr=round(rr, 2),
        target_bars=idx + 1,
    )


def compute_stop_from_target(entry: float, target: float, bias: str, min_rr: float = MIN_RR) -> float | None:
    """Recalcula stop a partir de entrada/alvo gravados (previsões antigas)."""
    if bias == "NEUTRO":
        return None
    if bias == "BULLISH":
        reward = target - entry
        if reward <= 0:
            return None
        risk = reward / min_rr
        return entry - risk
    reward = entry - target
    if reward <= 0:
        return None
    risk = reward / min_rr
    return entry + risk
