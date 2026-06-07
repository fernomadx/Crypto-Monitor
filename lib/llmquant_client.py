"""Cliente HTTP para LLMQuant Data (QuantMind / Quant Wiki / papers / crypto)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("LLMQUANT_BASE_URL", "https://api.llmquantdata.com").rstrip("/")
TIMEOUT = int(os.environ.get("LLMQUANT_TIMEOUT_SEC", "20"))


_PLACEHOLDERS = frozenset(
    {
        "",
        "your_llmquant_api_key",
        "your_llmquant_key",
        "changeme",
        "xxx",
    }
)


def _api_key() -> str | None:
    key = os.environ.get("LLMQUANT_API_KEY", "").strip()
    if not key or key.lower() in _PLACEHOLDERS or key.startswith("your_"):
        return None
    return key


def configured() -> bool:
    return _api_key() is not None


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        raise RuntimeError("LLMQUANT_API_KEY não configurado")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params or {}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: dict) -> dict[str, Any]:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def wiki_search(query: str, top_k: int = 5) -> list[dict]:
    data = _post("/api/wiki/search", {"query": query, "topK": min(max(top_k, 1), 10)})
    return data.get("data") or []


def wiki_read(wiki_item_id: str, max_length: int = 2000) -> dict | None:
    data = _get(f"/api/wiki/items/{wiki_item_id}", {"max_length": max_length})
    return data.get("data")


def paper_search(query: str, top_k: int = 3) -> list[dict]:
    data = _post("/api/paper/search", {"query": query, "topK": min(max(top_k, 1), 10)})
    return data.get("data") or []


def paper_read(paper_card_id: str, sections: list[str] | None = None) -> dict | None:
    payload: dict[str, Any] = {"paperCardId": paper_card_id}
    if sections:
        payload["sections"] = sections
    data = _post("/api/paper/read", payload)
    return data.get("data")


def crypto_snapshot(ticker: str) -> dict | None:
    """ticker: BTC-USD, ETH-USD, SOL-USD"""
    data = _get("/api/crypto/snapshot", {"ticker": ticker})
    return data.get("data")
