"""COMBO5 signal: Kronos 3TF momentum proxy + desk veto + strength/EMA/ATR/conf."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from lib.trade_desk.analysts import momentum_report, structure_report, technical_report
from lib.trade_desk.engine import consensus
from lib.trade_desk.indicators import enrich
from lib.trade_desk.models import Side


@dataclass
class Combo5Signal:
    ok: bool
    side: Side
    symbol: str
    price: float
    stop_price: float
    take_profit_price: float
    sl_pct: float
    tp_pct: float
    confidence: float
    kronos_bias: str
    strength_pct: float
    reasons: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


def _momentum_bias(closes: pd.Series, bars: int, thr: float) -> tuple[str, float]:
    if len(closes) < bars + 1:
        return "NEUTRO", 0.0
    pct = (float(closes.iloc[-1]) - float(closes.iloc[-1 - bars])) / float(closes.iloc[-1 - bars]) * 100
    if pct > thr:
        return "BULLISH", pct
    if pct < -thr:
        return "BEARISH", pct
    return "NEUTRO", pct


def _bias_at(df: pd.DataFrame, ts: pd.Timestamp, bars: int, thr: float) -> str:
    sub = df[df.index <= ts] if isinstance(df.index, pd.DatetimeIndex) else df
    if not isinstance(df.index, pd.DatetimeIndex):
        if len(df) < bars + 5:
            return "NEUTRO"
        return _momentum_bias(df["close"], bars, thr)[0]
    if len(sub) < bars + 5:
        return "NEUTRO"
    return _momentum_bias(sub["close"], bars, thr)[0]


def _desk_side_conf(df_1h: pd.DataFrame) -> tuple[Side, float, str]:
    reports = [
        technical_report(df_1h),
        momentum_report(df_1h),
        structure_report(df_1h),
    ]
    max_size = float(os.environ.get("TRADE_DESK_MAX_POSITION_PCT", "0.25"))
    side, conf, _size, detail = consensus(reports, max_size)
    return side, conf, detail


def evaluate_combo5(
    *,
    symbol: str,
    df_1h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_1d: pd.DataFrame,
) -> Combo5Signal:
    thr = float(os.environ.get("COMBO5_KRONOS_THR_PCT", "0.35"))
    min_strength = float(os.environ.get("COMBO5_MIN_STRENGTH_PCT", "0.8"))
    min_conf = float(os.environ.get("COMBO5_MIN_DESK_CONF", "0.65"))
    atr_lo = float(os.environ.get("COMBO5_ATR_MIN_PCT", "0.5"))
    atr_hi = float(os.environ.get("COMBO5_ATR_MAX_PCT", "1.1"))
    rr = float(os.environ.get("COMBO5_RR", "2.0"))
    atr_sl_mult = float(os.environ.get("COMBO5_ATR_SL_MULT", "2.0"))
    sl_floor = float(os.environ.get("COMBO5_SL_FLOOR", "0.02"))
    sl_cap = float(os.environ.get("COMBO5_SL_CAP", "0.045"))

    empty = Combo5Signal(
        False, Side.HOLD, symbol, 0.0, 0.0, 0.0, 0.03, 0.06, 0.0, "NEUTRO", 0.0, [], ["no data"]
    )
    if df_1h is None or df_4h is None or df_1d is None:
        return empty

    def _prep(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "timestamps" in out.columns and not isinstance(out.index, pd.DatetimeIndex):
            out = out.set_index("timestamps")
        return enrich(out).dropna()

    d1 = _prep(df_1h)
    d4 = _prep(df_4h)
    d1d = _prep(df_1d)
    if len(d1) < 80 or len(d4) < 40 or len(d1d) < 20:
        return Combo5Signal(
            False, Side.HOLD, symbol, 0.0, 0.0, 0.0, 0.03, 0.06, 0.0, "NEUTRO", 0.0, [], ["insufficient history"]
        )

    ts = d4.index[-1]
    if isinstance(d1.index, pd.DatetimeIndex):
        d1 = d1[d1.index <= ts]
    if isinstance(d1d.index, pd.DatetimeIndex):
        d1d = d1d[d1d.index <= ts]
    if len(d1) < 80:
        return empty

    bias4, strength_signed = _momentum_bias(d4["close"], 4, thr)
    strength = abs(strength_signed)
    blocks: list[str] = []
    reasons: list[str] = []
    price = float(d1["close"].iloc[-1])

    if bias4 == "NEUTRO":
        blocks.append(f"Kronos 4h NEUTRO (thr ±{thr}%)")
        return Combo5Signal(False, Side.HOLD, symbol, price, 0.0, 0.0, 0.03, 0.06, 0.0, bias4, strength, reasons, blocks)

    b1 = _bias_at(d1, ts, 4, thr)
    bd = _bias_at(d1d, ts, 3, thr)
    if not (bias4 == b1 == bd):
        blocks.append(f"3TF desalinhado (4h={bias4}, 1h={b1}, 1d={bd})")
        return Combo5Signal(False, Side.HOLD, symbol, price, 0.0, 0.0, 0.03, 0.06, 0.0, bias4, strength, reasons, blocks)
    reasons.append(f"Kronos 3TF alinhado {bias4} (força {strength:.2f}%)")

    if strength < min_strength:
        blocks.append(f"força {strength:.2f}% < mínimo {min_strength}%")

    row4 = d4.iloc[-1]
    ema4_ok = (bias4 == "BULLISH" and row4["ema_fast"] > row4["ema_slow"]) or (
        bias4 == "BEARISH" and row4["ema_fast"] < row4["ema_slow"]
    )
    if not ema4_ok:
        blocks.append("EMA 4h não alinhada ao viés Kronos")
    else:
        reasons.append("EMA 4h alinhada")

    desk_side, desk_conf, desk_detail = _desk_side_conf(d1)
    want = Side.BUY if bias4 == "BULLISH" else Side.SELL
    if desk_side != want:
        blocks.append(f"desk {desk_side.value} diverge de Kronos {bias4}")
    if desk_conf < min_conf:
        blocks.append(f"desk conf {desk_conf:.2f} < {min_conf}")
    else:
        reasons.append(f"desk conf {desk_conf:.2f} ({desk_detail[:80]})")

    atr_pct = float(d1["atr"].iloc[-1] / price * 100) if "atr" in d1.columns else 1.0
    if atr_pct < atr_lo or atr_pct > atr_hi:
        blocks.append(f"ATR% {atr_pct:.2f} fora de [{atr_lo},{atr_hi}]")
    else:
        reasons.append(f"ATR% {atr_pct:.2f} ok")

    sl_pct = max(sl_floor, min(sl_cap, (atr_pct / 100.0) * atr_sl_mult))
    tp_pct = sl_pct * rr
    if want == Side.BUY:
        stop = price * (1 - sl_pct)
        tp = price * (1 + tp_pct)
    else:
        stop = price * (1 + sl_pct)
        tp = price * (1 - tp_pct)

    ok = len(blocks) == 0
    return Combo5Signal(
        ok=ok,
        side=want if ok else Side.HOLD,
        symbol=symbol,
        price=price,
        stop_price=stop,
        take_profit_price=tp,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        confidence=desk_conf,
        kronos_bias=bias4,
        strength_pct=strength,
        reasons=reasons,
        blocks=blocks,
    )
