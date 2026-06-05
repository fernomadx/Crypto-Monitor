"""Cache de viés por ticker/TF para alinhamento entre runs em horários diferentes."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CACHE_PATH = Path(os.environ.get("KRONOS_BIAS_CACHE", "/data/kronos_bias_cache.json"))

# Idade máxima para scorecard 4H usar viés cacheado de outros TFs
MAX_AGE_1H_SEC = int(os.environ.get("KRONOS_CACHE_MAX_AGE_1H", str(90 * 60)))
MAX_AGE_1D_SEC = int(os.environ.get("KRONOS_CACHE_MAX_AGE_1D", str(26 * 3600)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_cache() -> dict[str, dict[str, dict]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(data: dict[str, dict[str, dict]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2))


def update_from_results(results: list[dict], interval: str) -> None:
    data = load_cache()
    iv = interval.lower()
    for r in results:
        ticker = r["ticker"]
        data.setdefault(ticker, {})[iv] = {
            "bias": r.get("bias", "NEUTRO"),
            "at": _now_iso(),
        }
    save_cache(data)


def biases_dict(data: dict[str, dict[str, dict]] | None = None) -> dict[str, dict[str, str]]:
    """Converte cache para formato do kronos_alignment."""
    raw = data if data is not None else load_cache()
    out: dict[str, dict[str, str]] = {}
    for ticker, intervals in raw.items():
        out[ticker] = {iv: meta.get("bias", "NEUTRO") for iv, meta in intervals.items()}
    return out


def merge_with_results(
    results_by_interval: dict[str, list[dict]],
) -> dict[str, dict[str, str]]:
    merged = biases_dict()
    for interval, results in results_by_interval.items():
        for r in results:
            merged.setdefault(r["ticker"], {})[interval.lower()] = r.get("bias", "NEUTRO")
    return merged


def cache_fresh_for_scorecard(biases: dict[str, str]) -> tuple[bool, str]:
    """4H scorecard precisa de 1h e 1d recentes no cache/merge."""
    data = load_cache()
    missing = []
    for iv, max_age in (("1h", MAX_AGE_1H_SEC), ("1d", MAX_AGE_1D_SEC)):
        if iv not in biases or biases.get(iv) == "NEUTRO":
            missing.append(f"{iv.upper()} ausente")
            continue
    # checa idade no cache (qualquer ticker serve — mesma run)
    sample = next(iter(data.values()), {}) if data else {}
    for iv, max_age in (("1h", MAX_AGE_1H_SEC), ("1d", MAX_AGE_1D_SEC)):
        meta = sample.get(iv)
        if not meta:
            continue
        try:
            at = datetime.fromisoformat(meta["at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - at).total_seconds()
            if age > max_age:
                missing.append(f"{iv.upper()} cache antigo ({int(age // 60)}m)")
        except (ValueError, TypeError):
            missing.append(f"{iv.upper()} cache inválido")
    if missing:
        return False, "; ".join(missing)
    return True, "cache OK"


def format_cache_note(biases: dict[str, dict[str, str]], ran_intervals: set[str]) -> str:
    """Nota de quais TFs vieram desta run vs cache."""
    data = load_cache()
    parts = []
    for iv in ("1h", "4h", "1d"):
        if iv in ran_intervals:
            parts.append(f"{iv.upper()} agora")
        elif any(iv in t for t in data.values()):
            parts.append(f"{iv.upper()} cache")
        else:
            parts.append(f"{iv.upper()} —")
    return " · ".join(parts)
