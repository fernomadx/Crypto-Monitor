"""
Smart Money Concepts (SMC) — detecção simplificada para backtest.

Regras aproximadas (não reproduzem 100% um setup ICT manual):
  - Swing high/low por fractais
  - BOS / CHoCH por rompimento de swings
  - FVG clássico de 3 candles
  - Entrada: reteste de FVG a favor da estrutura após CHoCH
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Trend(str, Enum):
    UP = "up"
    DOWN = "down"
    RANGE = "range"


class SignalType(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class FVG:
    direction: str  # "bull" | "bear"
    top: float
    bottom: float
    formed_idx: int
    filled: bool = False


@dataclass
class TradeSignal:
    bar_idx: int
    side: SignalType
    entry: float
    stop: float
    target: float
    reason: str


def add_swing_points(df: pd.DataFrame, wing: int = 2) -> pd.DataFrame:
    out = df.copy()
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    sh = [False] * n
    sl = [False] * n
    for i in range(wing, n - wing):
        if all(highs[i] >= highs[i - j] for j in range(1, wing + 1)) and all(
            highs[i] >= highs[i + j] for j in range(1, wing + 1)
        ):
            sh[i] = True
        if all(lows[i] <= lows[i - j] for j in range(1, wing + 1)) and all(
            lows[i] <= lows[i + j] for j in range(1, wing + 1)
        ):
            sl[i] = True
    out["swing_high"] = sh
    out["swing_low"] = sl
    return out


def detect_fvgs(df: pd.DataFrame) -> list[FVG]:
    fvgs: list[FVG] = []
    for i in range(2, len(df)):
        h2 = float(df.iloc[i - 2]["high"])
        l0 = float(df.iloc[i]["low"])
        l2 = float(df.iloc[i - 2]["low"])
        h0 = float(df.iloc[i]["high"])
        if l0 > h2:
            fvgs.append(FVG("bull", top=l0, bottom=h2, formed_idx=i))
        if h0 < l2:
            fvgs.append(FVG("bear", top=l2, bottom=h0, formed_idx=i))
    return fvgs


def _infer_trend(swing_highs: list[tuple[int, float]], swing_lows: list[tuple[int, float]]) -> Trend:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return Trend.RANGE
    hh = swing_highs[-1][1] > swing_highs[-2][1]
    hl = swing_lows[-1][1] > swing_lows[-2][1]
    lh = swing_highs[-1][1] < swing_highs[-2][1]
    ll = swing_lows[-1][1] < swing_lows[-2][1]
    if hh and hl:
        return Trend.UP
    if lh and ll:
        return Trend.DOWN
    return Trend.RANGE


def generate_signals(df: pd.DataFrame, rr: float = 2.0) -> list[TradeSignal]:
    """
    Gera sinais bar-a-bar sem lookahead na formação do FVG.
    CHoCH: rompimento do último swing contra a tendência anterior.
    Entrada: primeiro reteste do FVG a favor do novo viés.
    """
    df = add_swing_points(df)
    fvgs = detect_fvgs(df)
    signals: list[TradeSignal] = []

    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []
    trend = Trend.RANGE
    last_choch_side: SignalType | None = None
    used_fvg: set[int] = set()

    for i in range(len(df)):
        row = df.iloc[i]
        if row["swing_high"]:
            swing_highs.append((i, float(row["high"])))
        if row["swing_low"]:
            swing_lows.append((i, float(row["low"])))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            continue

        close = float(row["close"])
        prev_trend = trend
        trend = _infer_trend(swing_highs, swing_lows)
        last_sh = swing_highs[-2][1]
        last_sl = swing_lows[-2][1]

        # CHoCH bullish: estava em baixa/range e fecha acima do último swing high relevante
        if prev_trend in (Trend.DOWN, Trend.RANGE) and close > last_sh:
            last_choch_side = SignalType.LONG
        # CHoCH bearish
        if prev_trend in (Trend.UP, Trend.RANGE) and close < last_sl:
            last_choch_side = SignalType.SHORT

        if last_choch_side is None:
            continue

        for j, fvg in enumerate(fvgs):
            if j in used_fvg or fvg.formed_idx > i:
                continue
            if last_choch_side == SignalType.LONG and fvg.direction != "bull":
                continue
            if last_choch_side == SignalType.SHORT and fvg.direction != "bear":
                continue

            low = float(row["low"])
            high = float(row["high"])
            in_zone = low <= fvg.top and high >= fvg.bottom
            if not in_zone:
                continue

            if last_choch_side == SignalType.LONG:
                entry = fvg.top
                stop = fvg.bottom * 0.999
                risk = entry - stop
                if risk <= 0:
                    continue
                target = entry + rr * risk
            else:
                entry = fvg.bottom
                stop = fvg.top * 1.001
                risk = stop - entry
                if risk <= 0:
                    continue
                target = entry - rr * risk

            signals.append(
                TradeSignal(
                    bar_idx=i,
                    side=last_choch_side,
                    entry=entry,
                    stop=stop,
                    target=target,
                    reason=f"CHoCH+{fvg.direction}_FVG",
                )
            )
            used_fvg.add(j)
            last_choch_side = None
            break

    return signals
