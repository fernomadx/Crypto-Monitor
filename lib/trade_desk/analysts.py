from __future__ import annotations

import pandas as pd

from lib.trade_desk.indicators import enrich
from lib.trade_desk.models import AnalystReport, Side


def technical_report(df: pd.DataFrame) -> AnalystReport:
    data = enrich(df).dropna()
    if len(data) < 30:
        return AnalystReport("technical", Side.HOLD, 0.0, "Candles insuficientes")

    row, prev = data.iloc[-1], data.iloc[-2]
    score = 0.0
    reasons: list[str] = []

    if row["ema_fast"] > row["ema_slow"]:
        score += 1.0
        reasons.append("EMA12>EMA26")
    else:
        score -= 1.0
        reasons.append("EMA12<EMA26")

    if row["rsi"] < 30:
        score += 1.2
        reasons.append(f"RSI oversold {row['rsi']:.0f}")
    elif row["rsi"] > 70:
        score -= 1.2
        reasons.append(f"RSI overbought {row['rsi']:.0f}")
    elif row["rsi"] >= 50:
        score += 0.3
    else:
        score -= 0.3

    if prev["hist"] <= 0 < row["hist"]:
        score += 1.0
        reasons.append("MACD↑")
    elif prev["hist"] >= 0 > row["hist"]:
        score -= 1.0
        reasons.append("MACD↓")
    elif row["hist"] > 0:
        score += 0.4
    else:
        score -= 0.4

    if row.get("vol_sma") and row["volume"] > 1.2 * row["vol_sma"]:
        score *= 1.1
        reasons.append("vol↑")

    conf = min(1.0, abs(score) / 3.5)
    if score > 0.4:
        side = Side.BUY
    elif score < -0.4:
        side = Side.SELL
    else:
        side = Side.HOLD
        conf = max(conf, 0.35)

    return AnalystReport(
        "technical",
        side,
        round(conf, 3),
        "; ".join(reasons),
        {"rsi": float(row["rsi"]), "raw_score": round(float(score), 3)},
    )


def momentum_report(df: pd.DataFrame) -> AnalystReport:
    if len(df) < 24:
        return AnalystReport("sentiment", Side.HOLD, 0.0, "Sem histórico")
    recent = df.tail(24)
    ret = float(recent["close"].iloc[-1] / recent["close"].iloc[0] - 1)
    vol_ratio = float(recent["volume"].tail(6).mean() / max(recent["volume"].mean(), 1e-12))
    score = 0.0
    notes = [f"24b {ret:+.2%}"]
    if ret > 0.02:
        score += 1.0
    elif ret < -0.02:
        score -= 1.0
    if vol_ratio > 1.3:
        score += 0.5 if ret > 0 else -0.5
        notes.append("vol fear/fomo")
    conf = min(1.0, abs(score) / 1.5)
    side = Side.BUY if score > 0.3 else Side.SELL if score < -0.3 else Side.HOLD
    return AnalystReport("sentiment", side, round(conf, 3), "; ".join(notes), {"return_24": ret})


def structure_report(df: pd.DataFrame) -> AnalystReport:
    if len(df) < 50:
        return AnalystReport("structure", Side.HOLD, 0.0, "Sem histórico")
    closes = df["close"]
    vol = float(closes.pct_change().tail(48).std())
    high = float(df["high"].tail(48).max())
    low = float(df["low"].tail(48).min())
    last = float(closes.iloc[-1])
    mid = (high + low) / 2
    pos = (last - low) / max(high - low, 1e-12)
    notes = [f"vol={vol:.4f}", f"range={pos:.2f}"]
    if vol < 0.01:
        if pos < 0.25:
            side, conf = Side.BUY, 0.55
            notes.append("calmo perto do low")
        elif pos > 0.75:
            side, conf = Side.SELL, 0.55
            notes.append("calmo perto do high")
        else:
            side, conf = Side.HOLD, 0.4
            notes.append("meio de range")
    else:
        if last > mid:
            side, conf = Side.BUY, min(0.7, 0.4 + vol * 10)
            notes.append("vol alta + acima mid")
        else:
            side, conf = Side.SELL, min(0.7, 0.4 + vol * 10)
            notes.append("vol alta + abaixo mid")
    return AnalystReport("structure", side, round(conf, 3), "; ".join(notes), {"volatility": vol})


def kronos_as_report(bias: str | None, pct_short: float | None, tradeable: bool | None) -> AnalystReport | None:
    if not bias:
        return None
    b = bias.upper()
    if b.startswith("BULL"):
        side = Side.BUY
    elif b.startswith("BEAR"):
        side = Side.SELL
    else:
        side = Side.HOLD
    conf = 0.55
    if pct_short is not None:
        conf = min(0.95, 0.45 + abs(float(pct_short)) / 4.0)
    if tradeable is False:
        conf *= 0.6
    return AnalystReport(
        "kronos",
        side,
        round(conf, 3),
        f"Kronos {bias}" + (f" {pct_short:+.2f}%" if pct_short is not None else ""),
        {"bias": bias, "pct_short": pct_short, "tradeable": tradeable},
    )