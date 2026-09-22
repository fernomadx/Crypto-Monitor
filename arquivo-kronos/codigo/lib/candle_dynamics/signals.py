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

Versões:
  v1 — formalização ampla (baseline INVALIDATED)
  v2 — filtros corretivos: gap-retrace long restrito; short com impulso M30
  v2-short — igual v2 sem longs (só impulsão short)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

import numpy as np
import pandas as pd

StrategyVersion = Literal["v1", "v2", "v2-short"]


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


def _min_body_ok(open_: float, close: float, high: float, low: float, min_frac: float) -> bool:
    """Corpo do candle >= min_frac do range (filtra doji/ruído)."""
    rng = high - low
    if rng <= 0:
        return False
    return abs(close - open_) / rng >= min_frac


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
    version: StrategyVersion = "v1",
    stop_pct: float = 0.45,
    min_rr: float = 2.0,
    zone_tol_pct: float = 0.25,
    impulse_lookback_htf: int = 8,
    cooldown_bars: int | None = None,
    min_body_frac: float | None = None,
    gap_min_pct: float = 0.15,
) -> list[Signal]:
    """
    Percorre M5 fechado e emite setups alinhados à hierarquia da estratégia.

    v1: compra ampla em zona D/W + short em zona vendedora.
    v2: só long gap-retrace em fundo D/W; short exige impulso de alta no M30
        antes da microfalha M5; cooldown e corpo mínimo maiores.
    """
    if len(df_5m) < 200 or len(df_1d) < 30:
        return []

    if version in ("v2", "v2-short"):
        cooldown = cooldown_bars if cooldown_bars is not None else 72  # 6h
        body_frac = 0.35 if min_body_frac is None else min_body_frac
        gap_floor = max(gap_min_pct, 0.25)
        zone_tol = zone_tol_pct * 0.85
        rr = max(min_rr, 2.2)
        v2_mode = True
    else:
        cooldown = cooldown_bars if cooldown_bars is not None else 36
        body_frac = 0.0 if min_body_frac is None else min_body_frac
        gap_floor = gap_min_pct
        zone_tol = zone_tol_pct
        rr = min_rr
        v2_mode = False

    allow_longs = version != "v2-short"

    o = df_5m["open"].to_numpy(dtype=float)
    h = df_5m["high"].to_numpy(dtype=float)
    l = df_5m["low"].to_numpy(dtype=float)
    c = df_5m["close"].to_numpy(dtype=float)
    ts = pd.to_datetime(df_5m["timestamps"], utc=True)
    ts_ns = ts.astype("int64").to_numpy()

    d_hi, d_lo, d_mid = _swing_levels(df_1d, lookback=10)
    w_hi, w_lo, _w_mid = _swing_levels(df_1w, lookback=8)
    _h_hi, h_lo, h_mid = _swing_levels(df_1h, lookback=impulse_lookback_htf)
    _m_hi, m_lo, m_mid = _swing_levels(df_30m, lookback=impulse_lookback_htf)

    m30_high = df_30m["high"].to_numpy(dtype=float)
    m30_low = df_30m["low"].to_numpy(dtype=float)

    gaps = _daily_gaps(df_1d, min_gap_pct=gap_floor)
    gap_down = gaps["gap_down"].fillna(False).to_numpy()
    gap_prev_close = gaps["prev_close"].to_numpy(dtype=float)

    d_ns = _ts_ns(df_1d["timestamps"])
    w_ns = _ts_ns(df_1w["timestamps"])
    h_ns = _ts_ns(df_1h["timestamps"])
    m_ns = _ts_ns(df_30m["timestamps"])

    h_close = df_1h["close"].to_numpy(dtype=float)
    # Duração H1 em ns — close da barra corrente no resample full-history é FUTURO
    # enquanto a hora não fechou (look-ahead). Bias HTF só com H1 já fechado.
    H1_NS = np.int64(3_600_000_000_000)

    signals: list[Signal] = []
    cooldown_until = -1
    # 1 setup por zona D/W (v2): evita reentrar no mesmo swing
    last_long_zone_key: tuple[int, int] | None = None
    last_short_zone_key: tuple[int, int] | None = None

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

        d_range_pct = (float(d_hi[di]) - float(d_lo[di])) / price * 100.0
        if d_range_pct < 0.8:
            continue

        if body_frac > 0 and not _min_body_ok(float(o[i]), float(c[i]), float(h[i]), float(l[i]), body_frac):
            continue

        near_daily_low = abs(price - float(d_lo[di])) / price * 100 <= zone_tol * 1.5 or price <= float(d_lo[di]) * 1.003
        near_daily_high = abs(price - float(d_hi[di])) / price * 100 <= zone_tol * 1.5 or price >= float(d_hi[di]) * 0.997
        near_weekly_low = abs(price - float(w_lo[wi])) / price * 100 <= zone_tol * 2.5 or price <= float(w_lo[wi]) * 1.005
        near_weekly_high = abs(price - float(w_hi[wi])) / price * 100 <= zone_tol * 2.5 or price >= float(w_hi[wi]) * 0.995
        near_d_mid = abs(price - float(d_mid[di])) / price * 100 <= zone_tol
        near_h_mid = abs(price - float(h_mid[hi])) / price * 100 <= zone_tol
        near_m_mid = abs(price - float(m_mid[mi])) / price * 100 <= zone_tol

        if v2_mode:
            # Compra só em fundo D/W (não no 50% diário genérico)
            at_buy_zone = near_daily_low or near_weekly_low
            # Venda: 50% M30/H1 + resistência D/W (sem mid diário sozinho)
            at_sell_zone = (near_h_mid or near_m_mid) and (near_daily_high or near_weekly_high)
        else:
            at_buy_zone = near_daily_low or near_weekly_low or near_d_mid
            at_sell_zone = (near_h_mid or near_m_mid) and (near_daily_high or near_weekly_high or near_d_mid)

        bull_fail = is_bullish_failure(h, l, c, i)
        bear_fail = is_bearish_failure(h, l, c, i)

        # Viés H1: nunca usar close da hora ainda aberta (look-ahead no resample)
        hi_closed = hi if t_ns >= int(h_ns[hi]) + H1_NS else hi - 1
        if hi_closed < 0 or np.isnan(h_mid[hi_closed]):
            continue
        htf_bull = float(h_close[hi_closed]) > float(h_mid[hi_closed])
        htf_bear = float(h_close[hi_closed]) < float(h_mid[hi_closed])

        day_gap_down = bool(gap_down[di]) if di < len(gap_down) else False
        # Impulso de alta no M30 (hierarquia) — candle M30 já fechado = mi
        m30_up_impulse = detect_up_impulse(m30_high, mi, lookback=5)
        m30_down_impulse = detect_down_impulse(m30_low, mi, lookback=5)

        sig: Signal | None = None

        # --- LONG ---
        if allow_longs and bull_fail and at_buy_zone:
            allow_long = True
            if v2_mode:
                # Só gap-retrace (seção B) ou fundo semanal com impulso de baixa M30
                allow_long = day_gap_down or (near_weekly_low and m30_down_impulse)
                if allow_long and htf_bear and not day_gap_down:
                    allow_long = near_weekly_low
                zone_key = (di, wi)
                if allow_long and last_long_zone_key == zone_key:
                    allow_long = False

            if allow_long:
                entry = float(c[i])
                target_candidates = [float(d_mid[di]), float(h_mid[hi])]
                if day_gap_down and not np.isnan(gap_prev_close[di]):
                    target_candidates.append(float(gap_prev_close[di]))
                above = [x for x in target_candidates if x > entry]
                stop = min(float(l[i]), float(l[i - 1])) * (1 - 0.0005)
                risk = entry - stop
                if risk > 0 and (risk / entry * 100) <= stop_pct * 2.5:
                    target = max(above) if above else entry + risk * rr
                    if (target - entry) / risk < rr:
                        target = entry + risk * rr
                    counter = htf_bear
                    if v2_mode and counter:
                        target = fib_mid(entry, target) if above else entry + risk * 1.2
                        partial = None
                    else:
                        partial = fib_mid(entry, target) if counter else None
                    kind = SetupKind.GAP_RETRACE_LONG if day_gap_down else SetupKind.FAILURE_LONG
                    reason = (
                        f"microfalha_baixa M5 + zona_compra"
                        f"{' + gap_down' if day_gap_down else ''}"
                        f"{' + m30_down' if v2_mode and m30_down_impulse else ''}"
                        f" | HTF={'bear' if htf_bear else 'bull'} | {version}"
                    )
                    sig = Signal(
                        bar_idx=i,
                        ts=t,
                        side=Side.LONG,
                        kind=kind,
                        entry=entry,
                        stop=stop,
                        target=target,
                        partial_target=partial,
                        is_counter_trend=counter,
                        reason=reason,
                    )
                    if v2_mode:
                        last_long_zone_key = (di, wi)

        # --- SHORT (impulsão a favor) ---
        elif bear_fail and at_sell_zone and htf_bear:
            if day_gap_down and (near_daily_low or near_weekly_low):
                continue
            allow_short = True
            if v2_mode:
                allow_short = m30_up_impulse
                zone_key = (di, wi)
                if allow_short and last_short_zone_key == zone_key:
                    allow_short = False

            if allow_short:
                entry = float(c[i])
                target_candidates = [float(h_lo[hi]), float(m_lo[mi]), float(d_lo[di])]
                below = [x for x in target_candidates if x < entry and not np.isnan(x)]
                stop = max(float(h[i]), float(h[i - 1])) * (1 + 0.0005)
                risk = stop - entry
                if risk > 0 and (risk / entry * 100) <= stop_pct * 2.5:
                    if below:
                        target = min(below)
                        if (entry - target) / risk < rr:
                            target = entry - risk * rr
                    else:
                        target = entry - risk * rr
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
                        reason=(
                            "microfalha_alta M5 + zona_vendedora_50% HTF + resistência D/W"
                            f"{' + m30_up' if v2_mode else ''}"
                            f" | {version}"
                        ),
                    )
                    if v2_mode:
                        last_short_zone_key = (di, wi)

        if sig is not None:
            signals.append(sig)
            cooldown_until = i + cooldown

    return signals
