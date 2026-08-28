"""Candles MEXC Futures (contract) — substituto robusto ao CCXT no BTCCURSOR."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from lib.mexc_http import MEXC_CONTRACT_BASE, MEXC_CONTRACT_FALLBACK, mexc_get

logger = logging.getLogger(__name__)

# Docs: Min1/5/15/30/60, Hour4/8, Day1, Week1 — Min240 devolve code=600.
CONTRACT_INTERVAL_MAP = {
    "1m": "Min1",
    "5m": "Min5",
    "15m": "Min15",
    "30m": "Min30",
    "1h": "Min60",
    "1H": "Min60",
    "60m": "Min60",
    "Min60": "Min60",
    "4h": "Hour4",
    "4H": "Hour4",
    "Min240": "Hour4",
    "8h": "Hour8",
    "1d": "Day1",
    "1D": "Day1",
}

CONTRACT_SYMBOL_MAP = {
    "BTCUSDT": "BTC_USDT",
    "ETHUSDT": "ETH_USDT",
    "SOLUSDT": "SOL_USDT",
}


def contract_symbol(symbol: str) -> str:
    s = symbol.upper().replace("-", "")
    if "_" in s:
        return s
    return CONTRACT_SYMBOL_MAP.get(s, s.replace("USDT", "_USDT"))


def contract_interval(interval: str) -> str:
    return CONTRACT_INTERVAL_MAP.get(interval, interval)


def _parse_contract_payload(data: dict) -> pd.DataFrame:
    if not data:
        raise ValueError("Resposta contract vazia")
    times = data.get("time") or []
    if not times:
        raise ValueError("Sem candles contract")
    df = pd.DataFrame(
        {
            "open_time": [int(t) * 1000 for t in times],
            "open": [float(x) for x in data["open"]],
            "high": [float(x) for x in data["high"]],
            "low": [float(x) for x in data["low"]],
            "close": [float(x) for x in data["close"]],
            "volume": [float(x) for x in data.get("vol", data.get("volume", []))],
        }
    )
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["amount"] = df["volume"]
    return df


def _contract_error(body: dict) -> str | None:
    code = body.get("code")
    success = body.get("success", True)
    if success is False or (code not in (0, None) and not body.get("data")):
        msg = body.get("message") or body.get("msg") or ""
        return f"MEXC contract code={code} {msg}".strip()
    return None


def _get_json(url: str, params: dict | None = None) -> dict[str, Any]:
    resp = mexc_get(url, params=params)
    body = resp.json()
    err = _contract_error(body) if isinstance(body, dict) else None
    if err:
        raise ValueError(err)
    if isinstance(body, dict) and "data" in body:
        return body
    return body if isinstance(body, dict) else {"data": body}


def fetch_contract_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 100,
) -> pd.DataFrame:
    """
    Klines futures MEXC. Tenta contract.mexc.com e fallback api.mexc.com.
    symbol: BTCUSDT ou BTC_USDT
    """
    sym = contract_symbol(symbol)
    iv = contract_interval(interval)
    safe_limit = min(max(int(limit), 1), 2000)
    params = {"interval": iv, "limit": safe_limit}
    paths = [
        f"{MEXC_CONTRACT_BASE}/api/v1/contract/kline/{sym}",
        f"{MEXC_CONTRACT_FALLBACK}/api/v1/contract/kline/{sym}",
    ]
    errors: list[str] = []
    for url in paths:
        try:
            body = _get_json(url, params)
            data = body.get("data") if isinstance(body.get("data"), dict) else body
            return _parse_contract_payload(data)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            logger.warning("contract kline falhou %s %s: %s", sym, iv, exc)
    raise RuntimeError("; ".join(errors))


def fetch_contract_ticker(symbol: str) -> dict[str, Any]:
    """Ticker 24h de futuros (last, high/low, holdVol, riseFallRate)."""
    sym = contract_symbol(symbol)
    paths = [
        f"{MEXC_CONTRACT_BASE}/api/v1/contract/ticker",
        f"{MEXC_CONTRACT_FALLBACK}/api/v1/contract/ticker",
    ]
    errors: list[str] = []
    for url in paths:
        try:
            body = _get_json(url, {"symbol": sym})
            data = body.get("data") or {}
            if isinstance(data, list):
                data = next((row for row in data if row.get("symbol") == sym), data[0] if data else {})
            if not data:
                raise ValueError("ticker vazio")
            return data
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            logger.warning("contract ticker falhou %s: %s", sym, exc)
    raise RuntimeError("; ".join(errors))


def fetch_funding_rate(symbol: str) -> dict[str, Any]:
    """Funding atual + próximo settle (epoch ms)."""
    sym = contract_symbol(symbol)
    paths = [
        f"{MEXC_CONTRACT_BASE}/api/v1/contract/funding_rate/{sym}",
        f"{MEXC_CONTRACT_FALLBACK}/api/v1/contract/funding_rate/{sym}",
    ]
    errors: list[str] = []
    for url in paths:
        try:
            body = _get_json(url)
            data = body.get("data") or body
            if not isinstance(data, dict):
                raise ValueError("funding vazio")
            return data
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            logger.warning("funding falhou %s: %s", sym, exc)
    raise RuntimeError("; ".join(errors))
