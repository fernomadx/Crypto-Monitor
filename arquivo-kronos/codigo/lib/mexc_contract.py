"""Candles MEXC Futures (contract) — substituto robusto ao CCXT no BTCCURSOR."""

from __future__ import annotations

import logging
import os

import pandas as pd

from lib.mexc_http import MEXC_CONTRACT_BASE, MEXC_CONTRACT_FALLBACK, mexc_get

logger = logging.getLogger(__name__)

CONTRACT_INTERVAL_MAP = {
    "1h": "Min60",
    "1H": "Min60",
    "60m": "Min60",
    "4h": "Min240",
    "1d": "Day1",
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
            resp = mexc_get(url, params=params)
            body = resp.json()
            if not body.get("success", True) and body.get("code") not in (0, None):
                raise ValueError(f"MEXC contract code={body.get('code')}")
            data = body.get("data") if isinstance(body.get("data"), dict) else body
            return _parse_contract_payload(data)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            logger.warning("contract kline falhou %s: %s", sym, exc)
    raise RuntimeError("; ".join(errors))
