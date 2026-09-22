"""
Geração de sinais — Candle Dynamics.

Definições operacionais (candles FECHADOS apenas):

Microfalha de BAIXA (sinal de compra):
  - Impulsão de baixa recente (mínimas descendentes)
  - Candle fecha sem romper a mínima do gatilho anterior, OU
    fecha DENTRO do range do gatilho anterior

Microfalha de ALTA (sinal de venda):
  - Impulsão de alta recente (máximas ascendentes)
  - Candle fecha sem romper a máxima do gatilho anterior, OU
    fecha DENTRO do range do gatilho anterior

Zonas (D/W e M30/H1):
  - Alvo/suporte diário-semanal: extremos e 50% Fibonacci do swing
  - Zona vendedora: preço na região de 50% do movimento do TF estrutural

Gap diário (BTC 00:00 UTC):
  - Gap de baixa + preço em alvo D/W → NÃO vender no fundo
  - Após finalização da impulsão de baixa + microfalha M5 → compra na retração
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class SetupKind(str, Enum):
    GAP_RETRACE_LONG = "gap_retrace_long"
    IMPULSE_SHORT = "impulse_short"
    FAILURE_LONG = "failure_long"
    FAILURE_SHORT = "failure_short"


@dataclass(frozen=True)
class Signal:
    bar_idx: int  # índice no TF de confirmação (M5)
    ts: pd.Timestamp
    side: Side
    kind: SetupKind
    entry: float
    stop: float
    target: float
    partial_target: float | None
    is_counter_trend: bool
    reason: str


def fib_mid(high: float, low: float) -> float:
    return (high + low) / 2.0


def _asof_idx(htf_ns: np.ndarray, t_ns: int) -> int:
    """Último candle HTF com open <= t (ns UTC)."""
    i = int(np.searchsorted(htf_ns, t_ns, side="right")) - 1
    return max(i, 0)


def _ts_ns(series: pd.Series) -> np.ndarray:
    return pd.to_datetime(series, utc=True).astype("int64").to_numpy()


def detect_down_impulse(lows: np.ndarray, i: int, lookback: int = 4) -> bool:
    """Impulsão de baixa nos candles anteriores a i (mínimas em queda)."""
    if i < lookback:
        return False
    window = lows[i - lookback : i]
    descending = int(np.sum(window[1:] <= window[:-1])) >= max(1, lookback // 2)
    return bool(window[-1] < window[0] and descending)


def detect_up_impulse(highs: np.ndarray, i: int, lookback: int = 4) -> bool:
    """Impulsão de alta nos candles anteriores a i (máximas em alta)."""
    if i < lookback:
        return False
    window = highs[i - lookback : i]
    ascending = int(np.sum(window[1:] >= window[:-1])) >= max(1, lookback // 2)
    return bool(window[-1] > window[0] and ascending)


def is_bullish_failure(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    i: int,
) -> bool:
    """Falha da impulsão de baixa no candle i (já fechado)."""
    if i < 1:
        return False
    if not detect_down_impulse(low, i):
        return False
    inside = low[i - 1] < close[i] < high[i - 1]
    fail_low = low[i] >= low[i - 1]
    reclaim = close[i] > fib_mid(high[i - 1], low[i - 1])
    # Exige reclaim + (inside OU falha de mínima)
    return bool(reclaim and (inside or fail_low))


def is_bearish_failure(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    i: int,
) -> bool:
    """Falha da impulsão de alta (microfalha de alta) no candle i."""
    if i < 1:
        return False
    if not detect_up_impulse(high, i):
        return False
    inside = low[i - 1] < close[i] < high[i - 1]
    fail_high = high[i] <= high[i - 1]
    reject = close[i] < fib_mid(high[i - 1], low[i - 1])
    return bool(reject and (inside or fail_high))


def _swing_levels(df: pd.DataFrame, lookback: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Swing high/low rolling e 50% fib do swing (shift 1 = só candles fechados)."""
    hi = df["high"].rolling(lookback, min_periods=lookback).max().shift(1)
    lo = df["low"].rolling(lookback, min_periods=lookback).min().shift(1)
    mid = (hi + lo) / 2.0
    return hi.to_numpy(), lo.to_numpy(), mid.to_numpy()


def _daily_gaps(df_1d: pd.DataFrame, min_gap_pct: float = 0.15) -> pd.DataFrame:
    """Marca gaps diários (open vs close anterior)."""
    d = df_1d.copy()
    d["prev_close"] = d["close"].shift(1)
    d["gap_pct"] = (d["open"] - d["prev_close"]) / d["prev_close"] * 100.0
    d["gap_down"] = d["gap_pct"] <= -min_gap_pct
    d["gap_up"] = d["gap_pct"] >= min_gap_pct
    return d


def generate_signals(
    df_5m: pd.DataFrame,
    df_30m: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    df_1w: pd.DataFrame,
    *,
    stop_pct: float = 0.45,
    min_rr: float = 2.0,
    zone_tol_pct: float = 0.25,
    impulse_lookback_htf: int = 8,
    cooldown_bars: int = 36,  # 3h em M5 — paciência / evita overtrade
) -> list[Signal]:
    """
    Percorre M5 fechado e emite setups alinhados à hierarquia da estratégia.

    Paciência: só entra em zona D/W (compra) ou zona vendedora 50% M30/H1
    coincidente com resistência D/W (venda). Sem atalho só com 50% H1.
    """
    if len(df_5m) < 200 or len(df_1d) < 30:
        return []

    h = df_5m["high"].to_numpy(dtype=float)
    l = df_5m["low"].to_numpy(dtype=float)
    c = df_5m["close"].to_numpy(dtype=float)
    ts = pd.to_datetime(df_5m["timestamps"], utc=True)
    ts_ns = ts.astype("int64").to_numpy()

    d_hi, d_lo, d_mid = _swing_levels(df_1d, lookback=10)
    w_hi, w_lo, _w_mid = _swing_levels(df_1w, lookback=8)
    _h_hi, h_lo, h_mid = _swing_levels(df_1h, lookback=impulse_lookback_htf)
    _m_hi, m_lo, m_mid = _swing_levels(df_30m, lookback=impulse_lookback_htf)

    gaps = _daily_gaps(df_1d)
    gap_down = gaps["gap_down"].fillna(False).to_numpy()
    gap_prev_close = gaps["prev_close"].to_numpy(dtype=float)

    d_ns = _ts_ns(df_1d["timestamps"])
    w_ns = _ts_ns(df_1w["timestamps"])
    h_ns = _ts_ns(df_1h["timestamps"])
    m_ns = _ts_ns(df_30m["timestamps"])

    h_close = df_1h["close"].to_numpy(dtype=float)

    signals: list[Signal] = []
    cooldown_until = -1

    for i in range(30, len(df_5m) - 1):
        if i <= cooldown_until:
            continue

        t = pd.Timestamp(ts.iloc[i])
        t_ns = int(ts_ns[i])
        price = float(c[i])

        di = _asof_idx(d_ns, t_ns)
        wi = _asof_idx(w_ns, t_ns)
        hi = _asof_idx(h_ns, t_ns)
        mi = _asof_idx(m_ns, t_ns)

        if di < 2 or wi < 2 or hi < 5 or mi < 5:
            continue
        if np.isnan(d_lo[di]) or np.isnan(w_lo[wi]) or np.isnan(h_mid[hi]) or np.isnan(m_mid[mi]):
            continue

        # Amplitude mínima do swing diário (filtra mercado morto / zona irrelevante)
        d_range_pct = (float(d_hi[di]) - float(d_lo[di])) / price * 100.0
        if d_range_pct < 0.8:
            continue

        near_daily_low = abs(price - float(d_lo[di])) / price * 100 <= zone_tol_pct * 1.5 or price <= float(d_lo[di]) * 1.003
        near_daily_high = abs(price - float(d_hi[di])) / price * 100 <= zone_tol_pct * 1.5 or price >= float(d_hi[di]) * 0.997
        near_weekly_low = abs(price - float(w_lo[wi])) / price * 100 <= zone_tol_pct * 2.5 or price <= float(w_lo[wi]) * 1.005
        near_weekly_high = abs(price - float(w_hi[wi])) / price * 100 <= zone_tol_pct * 2.5 or price >= float(w_hi[wi]) * 0.995
        near_d_mid = abs(price - float(d_mid[di])) / price * 100 <= zone_tol_pct
        near_h_mid = abs(price - float(h_mid[hi])) / price * 100 <= zone_tol_pct
        near_m_mid = abs(price - float(m_mid[mi])) / price * 100 <= zone_tol_pct

        # Compra: alvo D/W no fundo ou 50% diário (retração de gap / impulso)
        at_buy_zone = near_daily_low or near_weekly_low or near_d_mid
        # Venda: zona 50% M30/H1 E resistência D/W (não vende no meio do nada)
        at_sell_zone = (near_h_mid or near_m_mid) and (near_daily_high or near_weekly_high or near_d_mid)

        bull_fail = is_bullish_failure(h, l, c, i)
        bear_fail = is_bearish_failure(h, l, c, i)

        htf_bull = float(h_close[hi]) > float(h_mid[hi])
        htf_bear = float(h_close[hi]) < float(h_mid[hi])

        day_gap_down = bool(gap_down[di]) if di < len(gap_down) else False

        sig: Signal | None = None

        # B) Compra na retração do gap / alvo D/W no fundo
        if bull_fail and at_buy_zone:
            entry = float(c[i])
            target_candidates = [float(d_mid[di]), float(h_mid[hi])]
            if day_gap_down and not np.isnan(gap_prev_close[di]):
                target_candidates.append(float(gap_prev_close[di]))
            above = [x for x in target_candidates if x > entry]
            stop = min(float(l[i]), float(l[i - 1])) * (1 - 0.0005)
            risk = entry - stop
            if risk <= 0:
                continue
            # Stop máximo relativo
            if (risk / entry * 100) > stop_pct * 2.5:
                continue
            target = max(above) if above else entry + risk * min_rr
            if (target - entry) / risk < min_rr:
                target = entry + risk * min_rr
            partial = fib_mid(entry, target)
            counter = htf_bear
            kind = SetupKind.GAP_RETRACE_LONG if day_gap_down else SetupKind.FAILURE_LONG
            reason = (
                f"microfalha_baixa M5 + zona_compra"
                f"{' + gap_down' if day_gap_down else ''}"
                f" | HTF={'bear' if htf_bear else 'bull'}"
            )
            sig = Signal(
                bar_idx=i,
                ts=t,
                side=Side.LONG,
                kind=kind,
                entry=entry,
                stop=stop,
                target=target,
                partial_target=partial if counter else None,
                is_counter_trend=counter,
                reason=reason,
            )

        # C) Venda na impulsão — zona vendedora 50% + microfalha de alta
        # Regra A: não vender no fundo após gap down em alvo D/W
        elif bear_fail and at_sell_zone and htf_bear:
            if day_gap_down and (near_daily_low or near_weekly_low):
                continue
            entry = float(c[i])
            target_candidates = [float(h_lo[hi]), float(m_lo[mi]), float(d_lo[di])]
            below = [x for x in target_candidates if x < entry]
            stop = max(float(h[i]), float(h[i - 1])) * (1 + 0.0005)
            risk = stop - entry
            if risk <= 0 or (risk / entry * 100) > stop_pct * 2.5:
                continue
            target = min(below) if below else entry - risk * min_rr
            if (entry - target) / risk < min_rr:
                target = entry - risk * min_rr
            sig = Signal(
                bar_idx=i,
                ts=t,
                side=Side.SHORT,
                kind=SetupKind.IMPULSE_SHORT,
                entry=entry,
                stop=stop,
                target=target,
                partial_target=None,
                is_counter_trend=False,
                reason="microfalha_alta M5 + zona_vendedora_50% HTF + resistência D/W",
            )

        if sig is not None:
            signals.append(sig)
            cooldown_until = i + cooldown_bars

    return signals
