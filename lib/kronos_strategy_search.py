"""
Pesquisa e grid-search de estratégias Kronos (MEXC BTC 4H).

Estratégias inspiradas em literatura:
  - MTF EMA trend (Jesse, ai-auto-trader)
  - Regime ATR/ADX (quantsarahz regime-aware)
  - 4H+1D consenso sem 1H (reduz conflito intraday)
  - R:R alto + stop apertado (Harvest 2:1+)
  - Pullback: 4H trend + 1H contra-tendência de curto prazo
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

import pandas as pd

from lib.kronos_backtest import StrategyParams, _simulate_trade, _fetch_multi, _apply_ml_noise
from lib.kronos_levels import compute_trade_levels, limit_entry_price, min_profitable_move_pct
from lib.mexc_klines import fetch_klines


class SignalMode(str, Enum):
    MOMENTUM_3TF = "momentum_3tf"       # v4 baseline
    MOMENTUM_4H_1D = "momentum_4h_1d"   # ignora 1H (menos conflito)
    EMA_MTF = "ema_mtf"                 # EMA9/21 4H+1D alinhado
    EMA_STRENGTH = "ema_strength"       # EMA spread >= min em 4H
    ADX_TREND = "adx_trend"             # ADX>threshold + direção
    PULLBACK = "pullback"               # 4H+1D trend, 1H pullback oposto
    DONCHIAN = "donchian"               # breakout 20 barras 4H


@dataclass(frozen=True)
class SearchParams(StrategyParams):
    signal_mode: SignalMode = SignalMode.MOMENTUM_3TF
    ema_fast: int = 9
    ema_slow: int = 21
    min_ema_spread_pct: float = 0.35
    adx_period: int = 14
    adx_min: float = 22.0
    donchian_bars: int = 20
    pullback_1h_pct: float = 0.25


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 2:
        return 0.0
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return float(adx.iloc[-1])


def _momentum(closes: pd.Series, bars: int, th: float) -> str:
    if len(closes) < bars + 1:
        return "NEUTRO"
    pct = (float(closes.iloc[-1]) - float(closes.iloc[-1 - bars])) / float(closes.iloc[-1 - bars]) * 100
    if pct > th:
        return "BULLISH"
    if pct < -th:
        return "BEARISH"
    return "NEUTRO"


def _ema_bias(df: pd.DataFrame, fast: int, slow: int, min_spread: float) -> str:
    if len(df) < slow + 5:
        return "NEUTRO"
    e_fast = _ema(df["close"], fast)
    e_slow = _ema(df["close"], slow)
    f, s = float(e_fast.iloc[-1]), float(e_slow.iloc[-1])
    spread = abs(f - s) / s * 100
    if spread < min_spread:
        return "NEUTRO"
    return "BULLISH" if f > s else "BEARISH"


def _slice_at(df: pd.DataFrame, ts: pd.Timestamp) -> pd.DataFrame:
    return df[df["timestamps"] <= ts].copy()


def _signal(
    params: SearchParams,
    *,
    df4: pd.DataFrame,
    df1: pd.DataFrame,
    df1d: pd.DataFrame,
    i: int,
    ts: pd.Timestamp,
) -> str | None:
    sub4 = df4.iloc[: i + 1]
    sub1 = _slice_at(df1, ts)
    sub1d = _slice_at(df1d, ts)
    th = params.bias_threshold_pct
    mode = params.signal_mode

    if mode == SignalMode.MOMENTUM_3TF:
        b4 = _momentum(sub4["close"], params.bias_bars_4h, th)
        if b4 == "NEUTRO":
            return None
        b1 = _momentum(sub1["close"], 4, th) if len(sub1) > 8 else "NEUTRO"
        bd = _momentum(sub1d["close"], 3, th) if len(sub1d) > 6 else "NEUTRO"
        return b4 if b4 == b1 == bd else None

    if mode == SignalMode.MOMENTUM_4H_1D:
        b4 = _momentum(sub4["close"], params.bias_bars_4h, th)
        bd = _momentum(sub1d["close"], 3, th) if len(sub1d) > 6 else "NEUTRO"
        return b4 if b4 != "NEUTRO" and b4 == bd else None

    if mode in (SignalMode.EMA_MTF, SignalMode.EMA_STRENGTH):
        spread = params.min_ema_spread_pct if mode == SignalMode.EMA_STRENGTH else 0.15
        b4 = _ema_bias(sub4, params.ema_fast, params.ema_slow, spread)
        if b4 == "NEUTRO":
            return None
        bd = _ema_bias(sub1d, params.ema_fast, params.ema_slow, spread * 0.8) if len(sub1d) > 25 else "NEUTRO"
        return b4 if b4 == bd else None

    if mode == SignalMode.ADX_TREND:
        if _adx(sub4, params.adx_period) < params.adx_min:
            return None
        b4 = _ema_bias(sub4, params.ema_fast, params.ema_slow, 0.1)
        bd = _ema_bias(sub1d, params.ema_fast, params.ema_slow, 0.1) if len(sub1d) > 25 else "NEUTRO"
        return b4 if b4 != "NEUTRO" and b4 == bd else None

    if mode == SignalMode.PULLBACK:
        b4 = _momentum(sub4["close"], params.bias_bars_4h, th)
        bd = _momentum(sub1d["close"], 3, th) if len(sub1d) > 6 else "NEUTRO"
        if b4 == "NEUTRO" or b4 != bd:
            return None
        # 1H pullback contra 4H (entrada melhor)
        if len(sub1) < 6:
            return None
        pct1 = (float(sub1["close"].iloc[-1]) - float(sub1["close"].iloc[-4])) / float(sub1["close"].iloc[-4]) * 100
        if b4 == "BULLISH" and pct1 <= -params.pullback_1h_pct:
            return b4
        if b4 == "BEARISH" and pct1 >= params.pullback_1h_pct:
            return b4
        return None

    if mode == SignalMode.DONCHIAN:
        n = params.donchian_bars
        if len(sub4) < n + 2:
            return None
        window = sub4.iloc[-(n + 1) : -1]
        hi, lo = float(window["high"].max()), float(window["low"].min())
        c = float(sub4["close"].iloc[-1])
        if c >= hi:
            return "BULLISH"
        if c <= lo:
            return "BEARISH"
        return None

    return None


_KLINE_CACHE: dict[tuple[str, int], dict[str, pd.DataFrame]] = {}


def _get_data(symbol: str, limit: int) -> dict[str, pd.DataFrame]:
    key = (symbol, limit)
    if key not in _KLINE_CACHE:
        _KLINE_CACHE[key] = _fetch_multi(symbol, limit)
    return _KLINE_CACHE[key]


def run_search(params: SearchParams, *, limit: int = 500, seed: int = 42) -> dict[str, Any]:
    os.environ["KRONOS_MIN_TARGET_PCT"] = str(params.min_target_pct)
    os.environ["KRONOS_MIN_RR"] = str(params.min_rr)
    os.environ["KRONOS_MAX_STOP_PCT_4H"] = str(params.max_stop_pct_4h)
    os.environ["KRONOS_LIMIT_ENTRY_OFFSET_PCT"] = str(params.entry_offset_pct)

    rng = random.Random(seed)
    trades: list[dict] = []
    capital = 1000.0
    min_capital = 1000.0
    skipped = 0

    for symbol in params.symbols:
        data = _get_data(symbol, limit)
        df4, df1, df1d = data["4h"], data["1h"], data["1d"]
        if len(df4) < 80:
            continue

        for i in range(60, len(df4) - params.target_bars_4h - 3):
            row = df4.iloc[i]
            ts = pd.Timestamp(row["timestamps"]).tz_convert("UTC")
            true_bias = _signal(params, df4=df4, df1=df1, df1d=df1d, i=i, ts=ts)
            if not true_bias:
                skipped += 1
                continue

            bias = _apply_ml_noise(true_bias, params.ml_accuracy, rng)
            last_close = float(row["close"])
            entry = limit_entry_price(last_close, bias)
            target_pct = max(params.min_target_pct, min_profitable_move_pct() + 0.15)
            pred_df = pd.DataFrame({"close": [entry * (1 + (1 if bias == "BULLISH" else -1) * target_pct / 100)]})

            levels = compute_trade_levels(
                entry=entry,
                pred_df=pred_df,
                bias=bias,
                target_bar_index=0,
                interval="4h",
                min_target_pct=params.min_target_pct,
                min_rr=params.min_rr,
                max_stop_pct=params.max_stop_pct_4h,
            )
            if levels is None:
                continue

            due_i = i + params.target_bars_4h
            due_close = float(df4.iloc[due_i]["close"])
            bars_after = [
                {"open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
                for _, r in df4.iloc[i + 1 : due_i + 1].iterrows()
            ]
            sim = _simulate_trade(
                params=params, bias=bias, entry=entry, target=levels.target, stop=levels.stop,
                bars_after=bars_after, due_close=due_close,
            )
            if sim["result"] == "no_fill":
                continue
            capital += sim["pnl"]
            min_capital = min(min_capital, capital)
            trades.append(sim)
            if capital <= 0:
                break

    if not trades:
        return {"params": params, "n": 0, "pnl": 0.0, "win_rate": 0.0, "pf": 0.0, "equity": 1000.0, "min_equity": 1000.0, "signals_skipped": skipped}

    gains = [t for t in trades if t["result"] == "gain"]
    losses = [t for t in trades if t["result"] == "loss"]
    total_pnl = sum(t["pnl"] for t in trades)
    gross_win = sum(t["pnl"] for t in gains)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    ret_pct = total_pnl / 10.0  # on $1000

    return {
        "params": params,
        "mode": params.signal_mode.value,
        "n": len(trades),
        "gains": len(gains),
        "losses": len(losses),
        "win_rate": round(100 * len(gains) / len(trades), 1),
        "pnl": round(total_pnl, 2),
        "return_pct": round(ret_pct, 2),
        "equity": round(1000 + total_pnl, 2),
        "min_equity": round(min_capital, 2),
        "max_dd_pct": round(100 * (1000 - min_capital) / 1000, 2),
        "pf": round(pf, 2),
        "avg_gain": round(sum(t["pnl"] for t in gains) / len(gains), 2) if gains else 0,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0,
        "signals_skipped": skipped,
    }


def grid_search(*, limit: int = 500, ml_accuracy: float = 0.58) -> list[dict]:
    """Grid sobre modos de sinal + parâmetros de execução."""
    candidates: list[SearchParams] = []

    base_exec = dict(
        margin_usdc=100.0, symbols=("BTCUSDT",),
        fee_maker_pct=0.02, fee_taker_pct=0.05, target_bars_4h=6,
        ml_accuracy=ml_accuracy, require_3tf=False,
    )

    for mode in SignalMode:
        for min_tgt in (1.0, 1.2, 1.5):
            for stop in (0.55, 0.65):
                for rr in (2.5, 3.5):
                    for lev in (3, 4):
                        th_opts = (0.35, 0.45) if mode in (SignalMode.MOMENTUM_3TF, SignalMode.MOMENTUM_4H_1D) else (0.30,)
                        for th in th_opts:
                            candidates.append(SearchParams(
                                **base_exec,
                                signal_mode=mode,
                                min_target_pct=min_tgt,
                                max_stop_pct_4h=stop,
                                min_rr=rr,
                                leverage=lev,
                                bias_threshold_pct=th,
                                entry_offset_pct=0.08,
                                limit_entry_bars=4,
                                bias_bars_4h=4,
                            ))

    results: list[dict] = []
    for p in candidates:
        try:
            r = run_search(p, limit=limit)
            if r["n"] >= 6:
                results.append(r)
        except Exception:
            continue

    results.sort(key=lambda x: (-x["pnl"], -x["pf"], -x["win_rate"], x["max_dd_pct"]))
    return results


def format_report(top: list[dict], baseline: dict | None = None) -> str:
    lines = ["# Kronos Strategy Search — BTC MEXC 4H\n"]
    if baseline:
        lines.append(
            f"**Baseline v4:** n={baseline['n']} WR={baseline['win_rate']}% "
            f"PnL=${baseline['pnl']:+.2f} PF={baseline['pf']} DD={baseline.get('max_dd_pct',0)}%\n"
        )
    lines.append("| # | Modo | Lev | Tgt | Stop | RR | n | WR% | PnL | PF | DD% |")
    lines.append("|---|------|-----|-----|------|----|---|-----|-----|----|-----|")
    for i, r in enumerate(top[:15], 1):
        p = r["params"]
        lines.append(
            f"| {i} | {r['mode']} | {p.leverage}x | {p.min_target_pct}% | {p.max_stop_pct_4h}% | "
            f"{p.min_rr} | {r['n']} | {r['win_rate']} | ${r['pnl']:+.0f} | {r['pf']} | {r['max_dd_pct']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print("Grid search (~{} combos)...".format(len(SignalMode) * 4 * 3 * 3 * 2 * 3))
    baseline = run_search(SearchParams(
        signal_mode=SignalMode.MOMENTUM_3TF,
        leverage=3, min_target_pct=1.0, max_stop_pct_4h=0.8, min_rr=3.0,
        bias_threshold_pct=0.40, ml_accuracy=0.58, require_3tf=True,
    ), limit=500)
    print("Baseline v4:", baseline)

    top = grid_search(limit=500, ml_accuracy=0.58)[:20]
    print(format_report(top, baseline))
    print("\n=== TOP 5 ===")
    for i, r in enumerate(top[:5], 1):
        p = r["params"]
        print(
            f"{i}. {r['mode']} | {p.leverage}x tgt{p.min_target_pct} stop{p.max_stop_pct_4h} RR{p.min_rr} "
            f"th{p.bias_threshold_pct} | n={r['n']} WR={r['win_rate']}% PnL=${r['pnl']:+.0f} "
            f"PF={r['pf']} DD={r['max_dd_pct']}%"
        )
