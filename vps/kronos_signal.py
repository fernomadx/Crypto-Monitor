#!/usr/bin/env python3
"""
vps/kronos_signal.py — Previsão Kronos na VPS → alerta Telegram separado.

Roda na VPS (ex.: BTCCURSOR), fora do Railway. Usa o MESMO bot/chat do crypto-monitor,
mas mensagens com prefixo [KRONOS] via lib.telegram.send_kronos_alert.

Cron sugerido (a cada 4h):
    0 */4 * * * cd /opt/crypto-monitor && /opt/crypto-monitor/vps/.venv/bin/python vps/kronos_signal.py >> /var/log/kronos_signal.log 2>&1

Variáveis: ver vps/.env.example
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

# Repo crypto-monitor (lib.telegram)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

KRONOS_ROOT = Path(os.environ.get("KRONOS_PATH", REPO_ROOT / "Kronos"))
sys.path.insert(0, str(KRONOS_ROOT))

from lib.telegram import send_kronos_alert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MEXC_BASE = "https://api.mexc.com"

# Defaults — sobrescreva via env
KRONOS_MODEL = os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-mini")
KRONOS_TOKENIZER = os.environ.get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-2k")
KRONOS_MAX_CONTEXT = int(os.environ.get("KRONOS_MAX_CONTEXT", "2048"))
KRONOS_INTERVAL = os.environ.get("KRONOS_INTERVAL", "15m")
KRONOS_LOOKBACK = int(os.environ.get("KRONOS_LOOKBACK", "400"))
KRONOS_PRED_LEN = int(os.environ.get("KRONOS_PRED_LEN", "12"))
KRONOS_TICKERS = os.environ.get("KRONOS_TICKERS", "BTCUSDT,ETHUSDT,SOLUSDT")
KRONOS_SAMPLE_COUNT = int(os.environ.get("KRONOS_SAMPLE_COUNT", "4"))
KRONOS_TEMPERATURE = float(os.environ.get("KRONOS_TEMPERATURE", "1.0"))
KRONOS_TOP_P = float(os.environ.get("KRONOS_TOP_P", "0.9"))


def fetch_mexc_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """OHLCV da MEXC (endpoint público)."""
    resp = requests.get(
        f"{MEXC_BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise ValueError(f"Sem candles para {symbol}")

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
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["amount"] = df["quote_volume"].astype(float)
    return df


def future_timestamps(last_ts: pd.Timestamp, pred_len: int, interval: str) -> pd.Series:
    """Gera timestamps futuros alinhados ao intervalo MEXC."""
    delta = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }.get(interval)
    if delta is None:
        raise ValueError(f"Intervalo não suportado: {interval}")

    stamps = [last_ts + delta * (i + 1) for i in range(pred_len)]
    return pd.Series(stamps)


def analyze_symbol(predictor, symbol: str) -> dict:
    """Uma previsão por par USDT."""
    need = KRONOS_LOOKBACK + 5
    df = fetch_mexc_klines(symbol, KRONOS_INTERVAL, limit=min(need, 1000))

    if len(df) < KRONOS_LOOKBACK + 1:
        raise ValueError(f"{symbol}: candles insuficientes ({len(df)} < {KRONOS_LOOKBACK})")

    hist = df.iloc[-KRONOS_LOOKBACK:].reset_index(drop=True)
    last_close = float(hist["close"].iloc[-1])
    last_ts = hist["timestamps"].iloc[-1]

    x_df = hist[["open", "high", "low", "close", "volume", "amount"]]
    x_timestamp = hist["timestamps"]
    y_timestamp = future_timestamps(last_ts, KRONOS_PRED_LEN, KRONOS_INTERVAL)

    pred_df = predictor.predict(
        df=x_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=KRONOS_PRED_LEN,
        T=KRONOS_TEMPERATURE,
        top_p=KRONOS_TOP_P,
        sample_count=KRONOS_SAMPLE_COUNT,
        verbose=False,
    )

    pred_close = float(pred_df["close"].iloc[-1])
    pct = (pred_close - last_close) / last_close * 100

    if pct > 0.15:
        bias = "BULLISH"
        icon = "🟢"
    elif pct < -0.15:
        bias = "BEARISH"
        icon = "🔴"
    else:
        bias = "NEUTRO"
        icon = "⚪"

    ticker = symbol.replace("USDT", "")
    return {
        "ticker": ticker,
        "last_close": last_close,
        "pred_close": pred_close,
        "pct": pct,
        "bias": bias,
        "icon": icon,
        "horizon_bars": KRONOS_PRED_LEN,
    }


def format_report(results: list[dict]) -> str:
    lines = [
        f"Intervalo: <code>{KRONOS_INTERVAL}</code> | Lookback: {KRONOS_LOOKBACK} | Horizonte: {KRONOS_PRED_LEN} barras",
        f"Modelo: <code>{KRONOS_MODEL}</code>",
        "",
    ]
    for r in results:
        sign = "+" if r["pct"] >= 0 else ""
        lines.append(
            f"<b>{r['ticker']}</b> {r['icon']} {r['bias']}\n"
            f"  Agora: ${r['last_close']:,.2f}\n"
            f"  Previsto (fim do horizonte): ${r['pred_close']:,.2f} ({sign}{r['pct']:.2f}%)"
        )
        lines.append("")
    return "\n".join(lines).strip()


def load_predictor():
    if not KRONOS_ROOT.is_dir():
        raise FileNotFoundError(
            f"Kronos não encontrado em {KRONOS_ROOT}. "
            "Clone: git clone https://github.com/shiyu-coder/Kronos.git"
        )

    import torch
    from model import Kronos, KronosTokenizer, KronosPredictor

    device = os.environ.get("KRONOS_DEVICE")
    if not device:
        if torch.cuda.is_available():
            device = "cuda:0"
        else:
            device = "cpu"

    logger.info("Carregando modelo %s em %s ...", KRONOS_MODEL, device)
    tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER)
    model = Kronos.from_pretrained(KRONOS_MODEL)
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=KRONOS_MAX_CONTEXT)
    return predictor


def run() -> None:
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        raise RuntimeError("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (mesmo bot do crypto-monitor)")

    symbols = [s.strip().upper() for s in KRONOS_TICKERS.split(",") if s.strip()]
    if not symbols:
        raise RuntimeError("KRONOS_TICKERS vazio")

    predictor = load_predictor()
    results = []
    errors = []

    for symbol in symbols:
        try:
            results.append(analyze_symbol(predictor, symbol))
            logger.info("OK %s", symbol)
        except Exception as exc:
            logger.exception("%s falhou: %s", symbol, exc)
            errors.append(f"{symbol}: {exc}")

    if not results:
        send_kronos_alert("Erro — sem previsões", "\n".join(errors) or "Falha desconhecida")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"Sinal {KRONOS_INTERVAL} — {now}"
    body = format_report(results)
    if errors:
        body += "\n\n⚠️ Erros:\n" + "\n".join(errors)

    ok = send_kronos_alert(title, body)
    if ok:
        logger.info("Alerta [KRONOS] enviado ao Telegram")
    else:
        logger.error("Falha ao enviar Telegram")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logger.exception("kronos_signal abortado: %s", exc)
        try:
            send_kronos_alert("Erro fatal", str(exc)[:500])
        except Exception:
            pass
        sys.exit(1)
