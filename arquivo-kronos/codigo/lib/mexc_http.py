"""HTTP MEXC com retry — spot e futures (evita RequestTimeout intermitente)."""

from __future__ import annotations

import logging
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

MEXC_SPOT_BASE = os.environ.get("MEXC_SPOT_BASE", "https://api.mexc.com").rstrip("/")
MEXC_CONTRACT_BASE = os.environ.get("MEXC_CONTRACT_BASE", "https://contract.mexc.com").rstrip("/")
MEXC_CONTRACT_FALLBACK = os.environ.get(
    "MEXC_CONTRACT_FALLBACK", "https://api.mexc.com"
).rstrip("/")

TIMEOUT = float(os.environ.get("MEXC_HTTP_TIMEOUT_SEC", "45"))
RETRIES = int(os.environ.get("MEXC_HTTP_RETRIES", "4"))
BACKOFF = float(os.environ.get("MEXC_HTTP_BACKOFF_SEC", "1.5"))

_session: requests.Session | None = None


def _build_session() -> requests.Session:
    retry = Retry(
        total=RETRIES,
        connect=RETRIES,
        read=RETRIES,
        backoff_factor=BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "Crypto-Monitor/1.0"})
    return session


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def mexc_get(url: str, *, params: dict | None = None, timeout: float | None = None) -> requests.Response:
    """GET com retry; levanta último erro após esgotar tentativas."""
    session = get_session()
    t = timeout if timeout is not None else TIMEOUT
    last_exc: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.get(url, params=params or {}, timeout=t)
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            logger.warning("MEXC timeout tentativa %d/%d: %s", attempt, RETRIES, url)
            if attempt < RETRIES:
                time.sleep(BACKOFF * attempt)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (429, 500, 502, 503, 504):
                last_exc = exc
                logger.warning("MEXC HTTP %s tentativa %d/%d", exc.response.status_code, attempt, RETRIES)
                if attempt < RETRIES:
                    time.sleep(BACKOFF * attempt)
                continue
            raise
    raise last_exc or RuntimeError(f"MEXC falhou: {url}")
