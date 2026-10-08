"""
Loader de OHLCV BTC via Binance Vision (data.binance.vision).

MEXC/API Spot limitam histórico em TFs baixos; Vision entrega meses completos
desde 2017+ sem chave. Cache local em data/candle_dynamics/ (gitignored).
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

VISION_BASE = "https://data.binance.vision/data/spot/monthly/klines"
DEFAULT_CACHE = Path("data/candle_dynamics")
COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    """Lista (year, month) inclusiva de start até end."""
    y, m = start.year, start.month
    out: list[tuple[int, int]] = []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _vision_url(symbol: str, interval: str, year: int, month: int) -> str:
    return (
        f"{VISION_BASE}/{symbol}/{interval}/"
        f"{symbol}-{interval}-{year}-{month:02d}.zip"
    )


def _parse_csv_bytes(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return pd.DataFrame(columns=COLUMNS[:6])
    # Alguns zips antigos não têm header; outros têm.
    first = text.split("\n", 1)[0]
    has_header = first.lower().startswith("open_time") or not first[0].isdigit()
    df = pd.read_csv(
        io.StringIO(text),
        header=0 if has_header else None,
        names=None if has_header else COLUMNS,
    )
    # Normaliza nomes
    rename = {c: c.strip().lower() for c in df.columns}
    df = df.rename(columns=rename)
    if "open_time" not in df.columns:
        df.columns = COLUMNS[: len(df.columns)]
    keep = ["open_time", "open", "high", "low", "close", "volume"]
    df = df[keep].copy()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    # Vision às vezes usa µs (16+ dígitos) em meses recentes
    ot = df["open_time"].astype("int64")
    if ot.max() > 10_000_000_000_000:  # µs
        df["timestamps"] = pd.to_datetime(ot, unit="us", utc=True)
    else:
        df["timestamps"] = pd.to_datetime(ot, unit="ms", utc=True)
    df = df.dropna(subset=["timestamps", "open", "high", "low", "close"])
    return df.reset_index(drop=True)


def download_month(
    symbol: str,
    interval: str,
    year: int,
    month: int,
    *,
    cache_dir: Path,
    session: requests.Session | None = None,
    retries: int = 4,
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{symbol}-{interval}-{year}-{month:02d}.parquet"
    if cache_file.exists():
        return pd.read_parquet(cache_file)

    url = _vision_url(symbol, interval, year, month)
    sess = session or requests.Session()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=120)
            if resp.status_code == 404:
                logger.warning("Mês ausente %s %s-%02d", interval, year, month)
                empty = pd.DataFrame(
                    columns=["open_time", "open", "high", "low", "close", "volume", "timestamps"]
                )
                empty.to_parquet(cache_file, index=False)
                return empty
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = zf.namelist()[0]
                raw = zf.read(name)
            df = _parse_csv_bytes(raw)
            df.to_parquet(cache_file, index=False)
            return df
        except Exception as exc:  # noqa: BLE001 — retry de rede
            last_err = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Falha ao baixar {url}: {last_err}")


def load_klines(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    *,
    years: float = 5.0,
    end: date | None = None,
    cache_dir: Path | str | None = None,
    fill_recent_mexc: bool = True,
) -> pd.DataFrame:
    """
    Carrega OHLCV contínuo dos últimos `years` anos (meses Vision).
    Opcionalmente completa o mês corrente via API pública MEXC.
    """
    end_d = end or datetime.now(timezone.utc).date()
    # aproxima anos → meses
    start_month = end_d.month - int(years * 12)
    start_year = end_d.year
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start_d = date(start_year, start_month, 1)

    cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE / symbol / interval
    sess = requests.Session()
    frames: list[pd.DataFrame] = []
    months = month_range(start_d, end_d)
    logger.info("Baixando/carregando %s %s: %d meses (%s → %s)", symbol, interval, len(months), start_d, end_d)

    for i, (y, m) in enumerate(months):
        df = download_month(symbol, interval, y, m, cache_dir=cache, session=sess)
        if not df.empty:
            frames.append(df)
        if (i + 1) % 12 == 0:
            logger.info("  … %d/%d meses", i + 1, len(months))

    if not frames:
        raise ValueError(f"Sem candles para {symbol} {interval}")

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["timestamps"]).sort_values("timestamps")
    cutoff = pd.Timestamp(end_d, tz="UTC") - pd.Timedelta(days=int(years * 365.25))
    out["timestamps"] = pd.to_datetime(out["timestamps"], utc=True)
    out = out[out["timestamps"] >= cutoff].reset_index(drop=True)

    if fill_recent_mexc and not out.empty:
        last_ts = pd.Timestamp(out["timestamps"].iloc[-1])
        now = pd.Timestamp.now(tz="UTC")
        if now - last_ts > pd.Timedelta(hours=6):
            try:
                recent = _fetch_mexc_recent(symbol, interval, start=last_ts, session=sess)
                if not recent.empty:
                    out = (
                        pd.concat([out, recent], ignore_index=True)
                        .drop_duplicates(subset=["timestamps"])
                        .sort_values("timestamps")
                        .reset_index(drop=True)
                    )
                    logger.info("Completado com MEXC até %s (%d barras)", out["timestamps"].iloc[-1], len(out))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Fill MEXC falhou (seguindo só Vision): %s", exc)

    return out


def _fetch_mexc_recent(
    symbol: str,
    interval: str,
    *,
    start: pd.Timestamp,
    session: requests.Session,
    limit: int = 1000,
) -> pd.DataFrame:
    """Pagina klines MEXC a partir de start até agora (preenche mês corrente)."""
    url = "https://api.mexc.com/api/v3/klines"
    cursor = int(start.timestamp() * 1000) + 1
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows: list = []
    for _ in range(200):
        if cursor >= end_ms:
            break
        resp = session.get(
            url,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": min(limit, 500),
            },
            timeout=30,
        )
        resp.raise_for_status()
        chunk = resp.json()
        if not chunk:
            break
        rows.extend(chunk)
        cursor = int(chunk[-1][0]) + 1
        if len(chunk) < 100:
            break
        time.sleep(0.05)
    if not rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume", "timestamps"])
    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
        ],
    )
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[["open_time", "open", "high", "low", "close", "volume", "timestamps"]]


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Agrega OHLCV (timestamps UTC) para outro timeframe pandas."""
    if df.empty:
        return df.copy()
    x = df.copy()
    x["timestamps"] = pd.to_datetime(x["timestamps"], utc=True)
    x = x.set_index("timestamps").sort_index()
    agg = x.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return agg
