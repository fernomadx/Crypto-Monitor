"""
Backtest offline das regras de execução Kronos (scorecard) em candles MEXC.

Calibra alavancagem, stops e filtros. Usa momentum como proxy de viés;
alvos derivados do mesmo viés (não usa preço futuro como oráculo).
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Any

import pandas as pd

from lib.kronos_levels import compute_trade_levels, limit_entry_price, min_profitable_move_pct
from lib.mexc_klines import fetch_klines


@dataclass(frozen=True)
class StrategyParams:
    leverage: float = 3.0
    margin_usdc: float = 100.0
    min_target_pct: float = 1.0
    min_rr: float = 2.5
    max_stop_pct_4h: float = 0.9
    bias_threshold_pct: float = 0.45
    entry_offset_pct: float = 0.10
    limit_entry_bars: int = 4
    require_3tf: bool = True
    symbols: tuple[str, ...] = ("BTCUSDT",)
    fee_maker_pct: float = 0.02
    fee_taker_pct: float = 0.05
    target_bars_4h: int = 6
    bias_bars_4h: int = 4
    ml_accuracy: float = 1.0  # 1.0 = viés perfeito; 0.55 = ML erra ~45%


def _momentum_bias(closes: pd.Series, bars: int, threshold: float) -> str:
    if len(closes) < bars + 1:
        return "NEUTRO"
    pct = (float(closes.iloc[-1]) - float(closes.iloc[-1 - bars])) / float(closes.iloc[-1 - bars]) * 100
    if pct > threshold:
        return "BULLISH"
    if pct < -threshold:
        return "BEARISH"
    return "NEUTRO"


def _bias_at_ts(df: pd.DataFrame, ts: pd.Timestamp, bars: int, threshold: float) -> str:
    """Viés no último candle fechado <= ts."""
    sub = df[df["timestamps"] <= ts]
    if len(sub) < bars + 5:
        return "NEUTRO"
    return _momentum_bias(sub["close"], bars, threshold)


def _synthetic_pred_df(entry: float, bias: str, target_pct: float) -> pd.DataFrame:
    """DataFrame mínimo para compute_trade_levels (alvo coerente com viés)."""
    sign = 1 if bias == "BULLISH" else -1
    close = entry * (1 + sign * target_pct / 100.0)
    return pd.DataFrame({"close": [close]})


def _simulate_trade(
    *,
    params: StrategyParams,
    bias: str,
    entry: float,
    target: float,
    stop: float,
    bars_after: list[dict],
    due_close: float,
) -> dict[str, Any]:
    notional = params.margin_usdc * params.leverage
    side = "long" if bias == "BULLISH" else "short"

    def fee(pct: float) -> float:
        return notional * (pct / 100.0)

    entry_ok = False
    entry_px = entry
    entry_idx = -1
    for i, b in enumerate(bars_after[: params.limit_entry_bars]):
        if side == "long" and b["low"] <= entry:
            entry_ok, entry_px, entry_idx = True, entry, i
            break
        if side == "short" and b["high"] >= entry:
            entry_ok, entry_px, entry_idx = True, entry, i
            break
    if not entry_ok:
        return {"result": "no_fill", "pnl": 0.0}

    exit_bars = bars_after[entry_idx + 1 :]
    exit_px = due_close
    exit_type = "market_due"
    for b in exit_bars:
        stop_hit = (side == "long" and b["low"] <= stop) or (side == "short" and b["high"] >= stop)
        tgt_hit = (side == "long" and b["high"] >= target) or (side == "short" and b["low"] <= target)
        if stop_hit:
            exit_px, exit_type = stop, "stop_loss"
            break
        if tgt_hit:
            exit_px, exit_type = target, "limit_target"
            break

    if side == "long":
        gross_pct = (exit_px - entry_px) / entry_px * 100.0
    else:
        gross_pct = (entry_px - exit_px) / entry_px * 100.0

    total_fee = fee(params.fee_maker_pct) + fee(
        params.fee_maker_pct if exit_type == "limit_target" else params.fee_taker_pct
    )
    pnl = notional * (gross_pct / 100.0) - total_fee
    pnl = max(-params.margin_usdc, pnl)

    if pnl > 0.05:
        res = "gain"
    elif pnl < -0.05:
        res = "loss"
    else:
        res = "flat"
    return {"result": res, "pnl": pnl, "exit_type": exit_type}


def _fetch_multi(symbol: str, limit: int = 500) -> dict[str, pd.DataFrame]:
    return {
        "4h": fetch_klines(symbol, "4h", limit),
        "1h": fetch_klines(symbol, "1h", min(limit * 4, 1000)),
        "1d": fetch_klines(symbol, "1d", min(limit // 6 + 30, 200)),
    }


def _apply_ml_noise(true_bias: str, accuracy: float, rng: random.Random) -> str:
    if true_bias == "NEUTRO" or accuracy >= 1.0:
        return true_bias
    if rng.random() > accuracy:
        return "BEARISH" if true_bias == "BULLISH" else "BULLISH"
    return true_bias


def run_backtest(params: StrategyParams, *, limit: int = 400, seed: int = 42) -> dict[str, Any]:
    os.environ["KRONOS_MIN_TARGET_PCT"] = str(params.min_target_pct)
    os.environ["KRONOS_MIN_RR"] = str(params.min_rr)
    os.environ["KRONOS_MAX_STOP_PCT_4H"] = str(params.max_stop_pct_4h)
    os.environ["KRONOS_LIMIT_ENTRY_OFFSET_PCT"] = str(params.entry_offset_pct)

    rng = random.Random(seed)
    trades: list[dict] = []
    capital = 1000.0
    min_capital = 1000.0

    for symbol in params.symbols:
        data = _fetch_multi(symbol, limit)
        df4 = data["4h"]
        df1 = data["1h"]
        df1d = data["1d"]
        if len(df4) < 80:
            continue

        for i in range(60, len(df4) - params.target_bars_4h - 3):
            row = df4.iloc[i]
            ts = pd.Timestamp(row["timestamps"]).tz_convert("UTC")
            true_bias = _momentum_bias(
                df4.iloc[: i + 1]["close"], params.bias_bars_4h, params.bias_threshold_pct
            )
            if true_bias == "NEUTRO":
                continue

            if params.require_3tf:
                b1 = _bias_at_ts(df1, ts, 4, params.bias_threshold_pct)
                b4 = true_bias
                b_d = _bias_at_ts(df1d, ts, 3, params.bias_threshold_pct)
                if not (b4 == b1 == b_d and b4 in ("BULLISH", "BEARISH")):
                    continue

            bias = _apply_ml_noise(true_bias, params.ml_accuracy, rng)
            if bias == "NEUTRO":
                continue

            last_close = float(row["close"])
            entry = limit_entry_price(last_close, bias)

            # Alvo sintético: min_target + buffer (simula previsão ML conservadora)
            target_pct = max(params.min_target_pct, min_profitable_move_pct() + 0.2)
            pred_df = _synthetic_pred_df(entry, bias, target_pct)

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
                {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
                for _, r in df4.iloc[i + 1 : due_i + 1].iterrows()
            ]

            sim = _simulate_trade(
                params=params,
                bias=bias,
                entry=entry,
                target=levels.target,
                stop=levels.stop,
                bars_after=bars_after,
                due_close=due_close,
            )
            if sim["result"] == "no_fill":
                continue
            capital += sim["pnl"]
            min_capital = min(min_capital, capital)
            trades.append({"symbol": symbol, "ts": ts, "bias": bias, **sim})
            if capital <= 0:
                break
        if capital <= 0:
            break

    if not trades:
        return {"params": params, "n": 0, "pnl": 0.0, "win_rate": 0.0, "pf": 0.0, "equity": 1000.0}

    gains = [t for t in trades if t["result"] == "gain"]
    losses = [t for t in trades if t["result"] == "loss"]
    total_pnl = sum(t["pnl"] for t in trades)
    gross_win = sum(t["pnl"] for t in gains)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)

    return {
        "params": params,
        "n": len(trades),
        "gains": len(gains),
        "losses": len(losses),
        "win_rate": round(100 * len(gains) / len(trades), 1),
        "pnl": round(total_pnl, 2),
        "equity": round(1000 + total_pnl, 2),
        "min_equity": round(min_capital, 2),
        "pf": round(pf, 2),
        "avg_gain": round(sum(t["pnl"] for t in gains) / len(gains), 2) if gains else 0,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0,
    }


def compare_strategies(limit: int = 400) -> None:
    v33 = StrategyParams(
        leverage=10,
        min_target_pct=0.5,
        max_stop_pct_4h=1.8,
        min_rr=2.0,
        require_3tf=True,
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        entry_offset_pct=0.15,
        limit_entry_bars=6,
        bias_threshold_pct=0.30,
        ml_accuracy=0.55,
    )
    v40 = StrategyParams(
        leverage=3,
        min_target_pct=1.0,
        max_stop_pct_4h=0.8,
        min_rr=3.0,
        require_3tf=True,
        symbols=("BTCUSDT",),
        entry_offset_pct=0.10,
        limit_entry_bars=4,
        bias_threshold_pct=0.40,
        ml_accuracy=0.55,
    )

    print("Comparação v3.3 vs v4.0 (ML ~55% acerto, 3TF, MEXC 4H)\n")
    for label, p in [("v3.3 (10x)", v33), ("v4.0 (3x BTC)", v40)]:
        r = run_backtest(p, limit=limit)
        print(
            f"{label}: trades={r['n']} WR={r['win_rate']}% PnL=${r['pnl']:+.0f} "
            f"equity=${r['equity']:.0f} min=${r.get('min_equity', r['equity']):.0f} "
            f"PF={r['pf']} avg+={r.get('avg_gain',0)} avg-={r.get('avg_loss',0)}"
        )


if __name__ == "__main__":
    compare_strategies()
