"""Estado compartilhado de contexto QUANT (notícias de impacto + pesquisa)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_SEEN_URLS = int(os.environ.get("QUANT_MAX_SEEN_URLS", "500"))


def _state_path() -> Path:
    return Path(os.environ.get("QUANT_STATE_PATH", "/data/quant_state.json"))


def _empty() -> dict[str, Any]:
    return {
        "updated_at": None,
        "global_bias": "NEUTRAL",
        "impact_score": 0.0,
        "headline": None,
        "summary": None,
        "url": None,
        "tickers": {},
        "seen_urls": [],
        "last_research": None,
    }


def load() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text())
        for key, default in _empty().items():
            data.setdefault(key, default if not isinstance(default, dict) else {})
        return data
    except (json.JSONDecodeError, OSError):
        return _empty()


def save(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def remember_url(data: dict[str, Any], url: str) -> None:
    if not url:
        return
    seen: list[str] = data.setdefault("seen_urls", [])
    if url in seen:
        return
    seen.append(url)
    if len(seen) > MAX_SEEN_URLS:
        data["seen_urls"] = seen[-MAX_SEEN_URLS:]


def url_seen(data: dict[str, Any], url: str) -> bool:
    return bool(url) and url in data.get("seen_urls", [])


def set_ticker_impact(
    data: dict[str, Any],
    ticker: str,
    *,
    bias: str,
    impact_score: float,
    headline: str,
    summary: str,
    url: str | None = None,
) -> None:
    tickers = data.setdefault("tickers", {})
    tickers[ticker.upper()] = {
        "bias": bias,
        "impact_score": round(impact_score, 3),
        "headline": headline[:300],
        "summary": summary[:500],
        "url": url,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if impact_score >= float(os.environ.get("QUANT_GLOBAL_IMPACT_MIN", "0.65")):
        data["global_bias"] = bias
        data["impact_score"] = round(impact_score, 3)
        data["headline"] = headline[:300]
        data["summary"] = summary[:500]
        data["url"] = url


def set_last_research(data: dict[str, Any], query: str, answer: str) -> None:
    data["last_research"] = {
        "query": query[:500],
        "answer": answer[:3000],
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
