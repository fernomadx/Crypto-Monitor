"""Dynamic correlation and lead-lag features."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats


def returns_from_closes(closes: list[float]) -> np.ndarray:
    arr = np.asarray(closes, dtype=float)
    if len(arr) < 2:
        return np.array([])
    return np.diff(arr) / arr[:-1]


def rolling_correlation(a: np.ndarray, b: np.ndarray, window: int = 30) -> list[float]:
    n = min(len(a), len(b))
    if n < window:
        return []
    a, b = a[-n:], b[-n:]
    out: list[float] = []
    for i in range(window - 1, n):
        x = a[i - window + 1 : i + 1]
        y = b[i - window + 1 : i + 1]
        if np.std(x) == 0 or np.std(y) == 0:
            out.append(0.0)
        else:
            out.append(float(np.corrcoef(x, y)[0, 1]))
    return out


def cross_correlation_lags(
    a: np.ndarray,
    b: np.ndarray,
    max_lag: int = 10,
) -> dict[str, Any]:
    n = min(len(a), len(b))
    if n < max_lag * 2 + 5:
        return {"best_lag": 0, "best_corr": 0.0, "lags": {}}
    a, b = a[-n:], b[-n:]
    lags: dict[int, float] = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = a[:lag], b[-lag:]
        elif lag > 0:
            x, y = a[lag:], b[:-lag]
        else:
            x, y = a, b
        m = min(len(x), len(y))
        if m < 10 or np.std(x[:m]) == 0 or np.std(y[:m]) == 0:
            corr = 0.0
        else:
            corr = float(np.corrcoef(x[:m], y[:m])[0, 1])
        lags[lag] = corr
    best_lag = max(lags, key=lambda k: abs(lags[k]))
    return {"best_lag": best_lag, "best_corr": lags[best_lag], "lags": lags}


def relation_stability(corr_series: list[float]) -> dict[str, Any]:
    if len(corr_series) < 5:
        return {
            "stable": False,
            "mean": 0.0,
            "std": 0.0,
            "sign_changes": 0,
            "trend": "insufficient",
        }
    arr = np.asarray(corr_series, dtype=float)
    signs = np.sign(arr)
    sign_changes = int(np.sum(signs[1:] * signs[:-1] < 0))
    half = len(arr) // 2
    first, second = float(np.mean(arr[:half])), float(np.mean(arr[half:]))
    if second - first > 0.1:
        trend = "strengthening"
    elif first - second > 0.1:
        trend = "weakening"
    elif abs(second) < 0.1 and abs(first) >= 0.2:
        trend = "disappeared"
    elif first * second < 0 and abs(second) > 0.15:
        trend = "inverted"
    else:
        trend = "persistent"
    return {
        "stable": float(np.std(arr)) < 0.25 and sign_changes <= 2,
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "sign_changes": sign_changes,
        "trend": trend,
        "recent_mean": second,
        "prior_mean": first,
    }


def volatility_correlation(a: np.ndarray, b: np.ndarray, window: int = 20) -> float:
    if len(a) < window or len(b) < window:
        return 0.0
    va = np.array([np.std(a[i - window : i]) for i in range(window, len(a) + 1)])
    vb = np.array([np.std(b[i - window : i]) for i in range(window, len(b) + 1)])
    m = min(len(va), len(vb))
    if m < 5 or np.std(va[-m:]) == 0 or np.std(vb[-m:]) == 0:
        return 0.0
    return float(np.corrcoef(va[-m:], vb[-m:])[0, 1])


def structural_break_hint(corr_series: list[float]) -> bool:
    if len(corr_series) < 20:
        return False
    arr = np.asarray(corr_series, dtype=float)
    mid = len(arr) // 2
    t_stat, p_value = stats.ttest_ind(arr[:mid], arr[mid:], equal_var=False)
    return bool(p_value < 0.05 and abs(t_stat) > 2)


def analyze_pair(
    name: str,
    btc_closes: list[float],
    other_closes: list[float],
    window: int = 30,
    max_lag: int = 5,
) -> dict[str, Any]:
    a = returns_from_closes(btc_closes)
    b = returns_from_closes(other_closes)
    n = min(len(a), len(b))
    if n < window:
        return {
            "asset": name,
            "availability": "DATA_UNAVAILABLE",
            "reason": "insufficient overlapping returns",
        }
    a, b = a[-n:], b[-n:]
    rolling = rolling_correlation(a, b, window=window)
    xcorr = cross_correlation_lags(a, b, max_lag=max_lag)
    stability = relation_stability(rolling)
    vol_corr = volatility_correlation(a, b, window=min(20, window))
    static = float(np.corrcoef(a, b)[0, 1]) if np.std(a) and np.std(b) else 0.0
    return {
        "asset": name,
        "availability": "AVAILABLE",
        "static_corr": round(static, 4),
        "rolling_corr_latest": round(rolling[-1], 4) if rolling else 0.0,
        "rolling_corr_mean": round(float(np.mean(rolling)), 4) if rolling else 0.0,
        "vol_corr": round(vol_corr, 4),
        "lead_lag": {
            "best_lag": xcorr["best_lag"],
            "best_corr": round(float(xcorr["best_corr"]), 4),
            "interpretation": (
                f"Associação lead-lag detectada: lag={xcorr['best_lag']} "
                f"(positivo => {name} move depois do BTC; negativo => {name} precede)"
            ),
        },
        "stability": stability,
        "structural_break_hint": structural_break_hint(rolling),
        "disclaimer": "Precedência temporal não implica causalidade.",
    }
