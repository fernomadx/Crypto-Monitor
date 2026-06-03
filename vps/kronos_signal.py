#!/usr/bin/env python3
"""
vps/kronos_signal.py — Previsão Kronos na VPS → Telegram [KRONOS] + gráficos.

Gera análise em 1H, 4H e Diário (configurável), envia resumo em texto
e um gráfico por timeframe (histórico + trilha preditiva).

Cron sugerido (a cada 4h):
    0 */4 * * * cd /opt/crypto-monitor && ... python vps/kronos_signal.py
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

KRONOS_ROOT = Path(os.environ.get("KRONOS_PATH", REPO_ROOT / "Kronos"))
sys.path.insert(0, str(KRONOS_ROOT))

from lib.telegram import send_kronos_alert, send_kronos_photo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MEXC_BASE = "https://api.mexc.com"
CHART_DIR = Path(os.environ.get("KRONOS_CHART_DIR", REPO_ROOT / "vps" / "charts"))

KRONOS_MODEL = os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-mini")
KRONOS_TOKENIZER = os.environ.get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-2k")
KRONOS_MAX_CONTEXT = int(os.environ.get("KRONOS_MAX_CONTEXT", "2048"))
def resolve_mexc_symbols() -> list[str]:
    """
    Usa as mesmas moedas do crypto-monitor (TICKERS=BTC,ETH,SOL no Railway).
    KRONOS_TICKERS opcional sobrescreve (ex.: BTCUSDT,ETHUSDT).
    """
    if os.environ.get("KRONOS_TICKERS"):
        raw = os.environ["KRONOS_TICKERS"]
    else:
        raw = os.environ.get("TICKERS", "BTC,ETH,SOL")
    symbols = []
    for part in raw.split(","):
        t = part.strip().upper()
        if not t:
            continue
        symbols.append(t if t.endswith("USDT") else f"{t}USDT")
    return symbols
KRONOS_TIMEFRAMES = os.environ.get("KRONOS_TIMEFRAMES", "1h,4h,1d")
KRONOS_SAMPLE_COUNT = int(os.environ.get("KRONOS_SAMPLE_COUNT", "4"))
KRONOS_TEMPERATURE = float(os.environ.get("KRONOS_TEMPERATURE", "1.0"))
KRONOS_TOP_P = float(os.environ.get("KRONOS_TOP_P", "0.9"))

INTERVAL_DELTAS = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


@dataclass(frozen=True)
class TimeframeConfig:
    interval: str
    label: str
    lookback: int
    pred_len: int
    chart_bars: int


TIMEFRAME_PRESETS: dict[str, TimeframeConfig] = {
    "1h": TimeframeConfig("1h", "1H", lookback=300, pred_len=24, chart_bars=72),
    "4h": TimeframeConfig("4h", "4H", lookback=200, pred_len=18, chart_bars=48),
    "1d": TimeframeConfig("1d", "Diário", lookback=120, pred_len=14, chart_bars=60),
}


def parse_timeframes() -> list[TimeframeConfig]:
    keys = [k.strip().lower() for k in KRONOS_TIMEFRAMES.split(",") if k.strip()]
    configs = []
    for key in keys:
        if key not in TIMEFRAME_PRESETS:
            raise ValueError(f"Timeframe desconhecido: {key}. Use: 1h, 4h, 1d")
        configs.append(TIMEFRAME_PRESETS[key])
    return configs


def fetch_mexc_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
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
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume",
        ],
    )
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["amount"] = df["quote_volume"].astype(float)
    return df


def future_timestamps(last_ts: pd.Timestamp, pred_len: int, interval: str) -> pd.Series:
    delta = INTERVAL_DELTAS.get(interval)
    if delta is None:
        raise ValueError(f"Intervalo não suportado: {interval}")
    return pd.Series([last_ts + delta * (i + 1) for i in range(pred_len)])


def bias_from_pct(pct: float) -> tuple[str, str]:
    if pct > 0.15:
        return "BULLISH", "🟢"
    if pct < -0.15:
        return "BEARISH", "🔴"
    return "NEUTRO", "⚪"


def analyze_symbol(predictor, symbol: str, tf: TimeframeConfig) -> dict:
    need = tf.lookback + 5
    df = fetch_mexc_klines(symbol, tf.interval, limit=min(need, 1000))

    if len(df) < tf.lookback + 1:
        raise ValueError(f"{symbol}@{tf.interval}: candles insuficientes ({len(df)} < {tf.lookback})")

    hist = df.iloc[-tf.lookback:].reset_index(drop=True)
    last_close = float(hist["close"].iloc[-1])
    last_ts = hist["timestamps"].iloc[-1]

    x_df = hist[["open", "high", "low", "close", "volume", "amount"]]
    y_timestamp = future_timestamps(last_ts, tf.pred_len, tf.interval)

    pred_df = predictor.predict(
        df=x_df,
        x_timestamp=hist["timestamps"],
        y_timestamp=y_timestamp,
        pred_len=tf.pred_len,
        T=KRONOS_TEMPERATURE,
        top_p=KRONOS_TOP_P,
        sample_count=KRONOS_SAMPLE_COUNT,
        verbose=False,
    )

    pred_close = float(pred_df["close"].iloc[-1])
    pct = (pred_close - last_close) / last_close * 100
    bias, icon = bias_from_pct(pct)
    ticker = symbol.replace("USDT", "")

    chart_hist = hist.iloc[-tf.chart_bars:][["timestamps", "open", "high", "low", "close"]].copy()

    return {
        "ticker": ticker,
        "symbol": symbol,
        "timeframe": tf.label,
        "interval": tf.interval,
        "last_close": last_close,
        "pred_close": pred_close,
        "pct": pct,
        "bias": bias,
        "icon": icon,
        "pred_len": tf.pred_len,
        "chart_hist": chart_hist,
        "pred_df": pred_df,
        "split_ts": last_ts,
    }


def _candle_width_days(timestamps: pd.Series) -> float:
    if len(timestamps) < 2:
        return 0.04
    nums = mdates.date2num(pd.to_datetime(timestamps))
    step = float(nums[1] - nums[0])
    return max(step * 0.65, 0.01)


def plot_candles(ax, df: pd.DataFrame, color_up: str, color_down: str, alpha: float = 1.0) -> None:
    """Candles simplificados (corpo + pavio)."""
    if df.empty:
        return
    width = _candle_width_days(df["timestamps"])
    for _, row in df.iterrows():
        ts = mdates.date2num(pd.Timestamp(row["timestamps"]))
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = color_up if c >= o else color_down
        ax.plot([ts, ts], [l, h], color=color, linewidth=0.9, alpha=alpha)
        body_bottom = min(o, c)
        body_height = abs(c - o) or max(c * 1e-6, 1e-8)
        ax.bar(ts, body_height, bottom=body_bottom, width=width, color=color, alpha=alpha, align="center")


def render_timeframe_chart(analyses: list[dict], tf_label: str, out_path: Path) -> None:
    n = len(analyses)
    fig, axes = plt.subplots(n, 1, figsize=(11, 3.2 * n), facecolor="#0f172a")
    if n == 1:
        axes = [axes]

    for ax, item in analyses:
        ax.set_facecolor("#1e293b")
        hist = item["chart_hist"]
        pred = item["pred_df"].copy()
        pred["timestamps"] = pd.to_datetime(pred.index)

        plot_candles(ax, hist, "#22c55e", "#ef4444", alpha=0.95)
        plot_candles(ax, pred, "#60a5fa", "#f97316", alpha=0.88)

        split = item["split_ts"]
        ax.axvline(split, color="#fbbf24", linestyle="--", linewidth=1.2, alpha=0.9, label="Agora → previsto")

        sign = "+" if item["pct"] >= 0 else ""
        ax.set_title(
            f"{item['ticker']}  {item['icon']} {item['bias']}  "
            f"${item['last_close']:,.2f} → ${item['pred_close']:,.2f} ({sign}{item['pct']:.2f}%)",
            color="white",
            fontsize=11,
            pad=8,
        )
        ax.tick_params(colors="#94a3b8", labelsize=8)
        ax.grid(True, color="#334155", alpha=0.4)
        for spine in ax.spines.values():
            spine.set_color("#475569")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        fig.autofmt_xdate()

    fig.suptitle(
        f"Kronos — {tf_label}  |  verde/vermelho = real  |  azul/laranja = previsto",
        color="white",
        fontsize=12,
        fontweight="bold",
        y=1.002,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)
    logger.info("Gráfico salvo: %s", out_path)


def format_timeframe_summary(tf_label: str, results: list[dict]) -> str:
    lines = [f"<b>━━ {tf_label} ━━</b>  (horizonte: {results[0]['pred_len']} barras)"]
    for r in results:
        sign = "+" if r["pct"] >= 0 else ""
        lines.append(
            f"{r['icon']} <b>{r['ticker']}</b> {r['bias']}: "
            f"${r['last_close']:,.2f} → ${r['pred_close']:,.2f} ({sign}{r['pct']:.2f}%)"
        )
    return "\n".join(lines)


def format_full_report(sections: list[str]) -> str:
    header = f"Modelo: <code>{KRONOS_MODEL}</code>"
    return header + "\n\n" + "\n\n".join(sections)


def load_predictor():
    if not KRONOS_ROOT.is_dir():
        raise FileNotFoundError(f"Kronos não encontrado em {KRONOS_ROOT}")

    import torch
    from model import Kronos, KronosTokenizer, KronosPredictor

    device = os.environ.get("KRONOS_DEVICE") or ("cuda:0" if torch.cuda.is_available() else "cpu")
    logger.info("Carregando %s em %s ...", KRONOS_MODEL, device)
    tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER)
    model = Kronos.from_pretrained(KRONOS_MODEL)
    return KronosPredictor(model, tokenizer, device=device, max_context=KRONOS_MAX_CONTEXT)


def run() -> None:
    symbols = resolve_mexc_symbols()
    send_kronos_alert(
        "Processando",
        f"Gerando previsões para: <code>{', '.join(symbols)}</code>\n"
        f"Timeframes: <code>{KRONOS_TIMEFRAMES}</code>",
    )
    timeframes = parse_timeframes()
    if not symbols or not timeframes:
        raise RuntimeError("KRONOS_TICKERS ou KRONOS_TIMEFRAMES vazio")

    predictor = load_predictor()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M")
    summary_sections: list[str] = []
    all_errors: list[str] = []

    for tf in timeframes:
        results: list[dict] = []
        tf_errors: list[str] = []

        for symbol in symbols:
            try:
                results.append(analyze_symbol(predictor, symbol, tf))
                logger.info("OK %s @ %s", symbol, tf.interval)
            except Exception as exc:
                logger.exception("%s @ %s: %s", symbol, tf.interval, exc)
                tf_errors.append(f"{symbol}@{tf.interval}: {exc}")

        if results:
            summary_sections.append(format_timeframe_summary(tf.label, results))
            chart_path = CHART_DIR / f"kronos_{tf.interval}_{stamp}.png"
            try:
                render_timeframe_chart(results, tf.label, chart_path)
                send_kronos_photo(
                    str(chart_path),
                    f"Gráfico {tf.label} — {now.strftime('%Y-%m-%d %H:%M UTC')}",
                )
            except Exception as exc:
                logger.exception("Gráfico %s falhou: %s", tf.label, exc)
                tf_errors.append(f"gráfico {tf.label}: {exc}")

        all_errors.extend(tf_errors)

    if not summary_sections:
        send_kronos_alert("Erro — sem previsões", "\n".join(all_errors) or "Falha desconhecida")
        return

    title = f"Previsão multi-timeframe — {now.strftime('%Y-%m-%d %H:%M UTC')}"
    body = format_full_report(summary_sections)
    if all_errors:
        body += "\n\n⚠️ Erros:\n" + "\n".join(all_errors[:10])

    send_kronos_alert(title, body)
    logger.info("Relatório [KRONOS] enviado (%d timeframes)", len(summary_sections))


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
