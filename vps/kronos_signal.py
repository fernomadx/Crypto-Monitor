#!/usr/bin/env python3
"""
vps/kronos_signal.py — Previsão Kronos na VPS → Telegram [KRONOS] + gráficos.

Por padrão gera 1H, 4H e Diário. Com --tf roda só um timeframe (cron no
fechamento do candle MEXC/UTC):

    2 * * * * kronos_run.sh ... 1h          # de hora em hora
    2 0,4,8,12,16,20 * * * kronos_run.sh 4h   # a cada 4h
    5 0 * * * kronos_run.sh ... 1d            # diário
"""

from __future__ import annotations

import argparse
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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_config import apply_v31_defaults  # noqa: E402

apply_v31_defaults()

KRONOS_ROOT = Path(os.environ.get("KRONOS_PATH", REPO_ROOT / "Kronos"))
sys.path.insert(0, str(KRONOS_ROOT))

from lib.kronos_config import format_config_footer  # noqa: E402
from lib.kronos_alignment import (  # noqa: E402
    format_alignment_report,
    should_log_to_scorecard,
    tradeable_for_interval,
)
from lib.kronos_bias_cache import (  # noqa: E402
    format_cache_note,
    merge_with_results,
    update_from_results,
)
from lib.kronos_levels import compute_trade_levels, limit_entry_price  # noqa: E402
from lib.kronos_tracker import format_scorecard_brief, log_predictions, new_run_id  # noqa: E402
from lib.mexc_klines import INTERVAL_DELTAS, MEXC_KLINES_MAX_LIMIT, fetch_klines  # noqa: E402
from lib.kronos_quant import apply_to_results, format_kronos_footer  # noqa: E402
from lib.telegram import send_kronos_alert, send_kronos_photo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class CandleNotReadyError(Exception):
    """MEXC ainda não publicou o candle fechado."""

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
KRONOS_TEMPERATURE = float(os.environ.get("KRONOS_TEMPERATURE", "0.65"))
KRONOS_BIAS_THRESHOLD_PCT = float(os.environ.get("KRONOS_BIAS_THRESHOLD_PCT", "0.30"))
KRONOS_TOP_P = float(os.environ.get("KRONOS_TOP_P", "0.9"))
# Viés = poucas barras; alvo de trade = mais barras (evita alvo minúsculo)
KRONOS_BIAS_BARS = int(os.environ.get("KRONOS_BIAS_BARS", os.environ.get("KRONOS_SHORT_BARS", "4")))
KRONOS_TARGET_BARS = int(os.environ.get("KRONOS_TARGET_BARS", "8"))

@dataclass(frozen=True)
class TimeframeConfig:
    interval: str
    label: str
    lookback: int
    pred_len: int
    chart_bars: int


def _target_bars_for(tf_key: str, pred_len: int) -> int:
    """Barras do alvo por timeframe (sobrescreve KRONOS_TARGET_BARS se definido por TF)."""
    defaults = {"1h": 8, "4h": 6, "1d": 4}
    base = int(os.environ.get(f"KRONOS_TARGET_BARS_{tf_key.upper()}", defaults.get(tf_key, KRONOS_TARGET_BARS)))
    return min(max(base, 2), pred_len)


TIMEFRAME_PRESETS: dict[str, TimeframeConfig] = {
    "1h": TimeframeConfig("1h", "1H", lookback=250, pred_len=12, chart_bars=72),
    "4h": TimeframeConfig("4h", "4H", lookback=200, pred_len=12, chart_bars=48),
    "1d": TimeframeConfig("1d", "Diário", lookback=120, pred_len=7, chart_bars=60),
}


def parse_timeframes() -> list[TimeframeConfig]:
    keys = [k.strip().lower() for k in KRONOS_TIMEFRAMES.split(",") if k.strip()]
    configs = []
    for key in keys:
        if key not in TIMEFRAME_PRESETS:
            raise ValueError(f"Timeframe desconhecido: {key}. Use: 1h, 4h, 1d")
        configs.append(TIMEFRAME_PRESETS[key])
    return configs


def resolve_timeframes(tf_filter: str | None) -> list[TimeframeConfig]:
    if tf_filter:
        key = tf_filter.strip().lower()
        if key not in TIMEFRAME_PRESETS:
            raise ValueError(f"Timeframe desconhecido: {key}. Use: 1h, 4h, 1d")
        return [TIMEFRAME_PRESETS[key]]
    return parse_timeframes()


def _as_utc_ts(value) -> pd.Timestamp:
    """Normaliza datetime/Timestamp para UTC (evita tz= em valor já aware)."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def expected_last_candle_open(wake_at: datetime, interval: str) -> pd.Timestamp:
    """open_time do último candle fechado no instante wake_at (UTC)."""
    boundary = wake_at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    delta = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}
    if interval not in delta:
        raise ValueError(interval)
    return _as_utc_ts(boundary - delta[interval])


def _interval_delta(interval: str) -> timedelta:
    delta = INTERVAL_DELTAS.get(interval)
    if delta is None:
        raise ValueError(f"Intervalo não suportado: {interval}")
    return delta


def _is_candle_closed(open_ts: pd.Timestamp, interval: str, *, grace_sec: int = 3) -> bool:
    now = datetime.now(timezone.utc)
    close_at = _as_utc_ts(open_ts) + _interval_delta(interval)
    return close_at <= now - timedelta(seconds=grace_sec)


def _closed_candle_end_index(
    df: pd.DataFrame,
    interval: str,
    expected_open: pd.Timestamp | None = None,
) -> int:
    """
    Índice do último candle FECHADO no DataFrame MEXC.

    Após :00 UTC a API costuma incluir o candle novo (ainda aberto) como última linha.
    """
    if df.empty:
        raise CandleNotReadyError("sem candles MEXC")

    delta = _interval_delta(interval)
    exp = _as_utc_ts(expected_open) if expected_open is not None else None

    if exp is not None:
        for i in range(len(df) - 1, -1, -1):
            open_ts = _as_utc_ts(df["timestamps"].iloc[i])
            if abs((open_ts - exp).total_seconds()) > 90:
                continue
            if _is_candle_closed(open_ts, interval):
                return i
            raise CandleNotReadyError(
                f"candle {interval.upper()} {open_ts} ainda aberto (aguardando fechamento)"
            )

        last_open = _as_utc_ts(df["timestamps"].iloc[-1])
        # Última barra = candle seguinte ao esperado (comum logo após fechar)
        if abs((last_open - (exp + delta)).total_seconds()) <= 90 and len(df) >= 2:
            prev_i = len(df) - 2
            prev_open = _as_utc_ts(df["timestamps"].iloc[prev_i])
            if abs((prev_open - exp).total_seconds()) <= 90 and _is_candle_closed(prev_open, interval):
                return prev_i

        raise CandleNotReadyError(
            f"esperado candle {exp}, MEXC último {_as_utc_ts(df['timestamps'].iloc[-1])}"
        )

    for i in range(len(df) - 1, -1, -1):
        if _is_candle_closed(df["timestamps"].iloc[i], interval):
            return i
    raise CandleNotReadyError(f"nenhum candle {interval.upper()} fechado na resposta MEXC")


def verify_last_candle_closed(last_ts: pd.Timestamp, interval: str) -> None:
    if not _is_candle_closed(last_ts, interval):
        now = datetime.now(timezone.utc)
        close_at = _as_utc_ts(last_ts) + _interval_delta(interval)
        raise CandleNotReadyError(
            f"candle {interval.upper()} ainda aberto (fecha em {int((close_at - now).total_seconds())}s)"
        )


def future_timestamps(last_ts: pd.Timestamp, pred_len: int, interval: str) -> pd.Series:
    delta = INTERVAL_DELTAS.get(interval)
    if delta is None:
        raise ValueError(f"Intervalo não suportado: {interval}")
    return pd.Series([last_ts + delta * (i + 1) for i in range(pred_len)])


def bias_from_pct(pct: float) -> tuple[str, str]:
    th = KRONOS_BIAS_THRESHOLD_PCT
    if pct > th:
        return "BULLISH", "🟢"
    if pct < -th:
        return "BEARISH", "🔴"
    return "NEUTRO", "⚪"


def pct_change_to_bar(pred_df: pd.DataFrame, last_close: float, bar_index: int) -> float:
    """Variação % até a barra N da previsão (0 = primeira barra futura)."""
    idx = min(max(bar_index, 0), len(pred_df) - 1)
    pred_close = float(pred_df["close"].iloc[idx])
    return (pred_close - last_close) / last_close * 100


def hist_return_correlation(results: list[dict]) -> dict[str, float]:
    """Correlação dos retornos recentes vs BTC (quanto o par costuma seguir o BTC)."""
    btc = next((r for r in results if r["ticker"] == "BTC"), None)
    if not btc or len(btc["chart_hist"]) < 20:
        return {}
    btc_ret = btc["chart_hist"]["close"].astype(float).pct_change().dropna()
    out: dict[str, float] = {"BTC": 1.0}
    for r in results:
        if r["ticker"] == "BTC":
            continue
        ret = r["chart_hist"]["close"].astype(float).pct_change().dropna()
        n = min(len(btc_ret), len(ret), 60)
        if n < 15:
            continue
        c = btc_ret.iloc[-n:].corr(ret.iloc[-n:])
        if c == c:  # not NaN
            out[r["ticker"]] = float(c)
    return out


def coherence_notes(results: list[dict], corrs: dict[str, float]) -> list[str]:
    """
    Alerta quando o modelo prevê movimentos opostos fortes entre pares correlacionados.
    """
    notes: list[str] = []
    btc = next((r for r in results if r["ticker"] == "BTC"), None)
    if not btc:
        return notes

    btc_pct = btc["pct_short"]
    for r in results:
        if r["ticker"] == "BTC":
            continue
        alt_pct = r["pct_short"]
        corr = corrs.get(r["ticker"], 0.5)
        opposite = btc_pct * alt_pct < 0
        strong = abs(btc_pct) >= 1.0 and abs(alt_pct) >= 2.0
        if opposite and strong and corr >= 0.45:
            notes.append(
                f"⚠️ <b>{r['ticker']}</b> diverge do BTC (corr. recente {corr:.2f}): "
                f"BTC {btc_pct:+.1f}% vs {r['ticker']} {alt_pct:+.1f}% no curto prazo — "
                f"<i>baixa confiança / possível ruído do modelo</i>"
            )
    if len(notes) >= 2:
        notes.insert(
            0,
            "⚠️ <b>Cenário cruzado improvável</b>: altcoins e BTC raramente divergem tanto "
            "no mesmo período. Não use como trade isolado.",
        )
    return notes


def analyze_symbol(
    predictor,
    symbol: str,
    tf: TimeframeConfig,
    *,
    expected_candle_open: pd.Timestamp | None = None,
) -> dict:
    need = tf.lookback + 5
    df = fetch_klines(symbol, tf.interval, limit=min(need, MEXC_KLINES_MAX_LIMIT))

    end_i = _closed_candle_end_index(df, tf.interval, expected_candle_open)
    closed = df.iloc[: end_i + 1]
    if len(closed) < tf.lookback + 1:
        raise CandleNotReadyError(
            f"{symbol}@{tf.interval}: candles fechados insuficientes ({len(closed)} < {tf.lookback + 1})"
        )

    hist = closed.iloc[-tf.lookback:].reset_index(drop=True)
    last_close = float(hist["close"].iloc[-1])
    last_ts = hist["timestamps"].iloc[-1]
    verify_last_candle_closed(last_ts, tf.interval)

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

    bias_idx = min(KRONOS_BIAS_BARS - 1, len(pred_df) - 1)
    target_idx = min(_target_bars_for(tf.interval, tf.pred_len) - 1, len(pred_df) - 1)
    pct_short = pct_change_to_bar(pred_df, last_close, bias_idx)
    pct_long = pct_change_to_bar(pred_df, last_close, len(pred_df) - 1)
    bias, icon = bias_from_pct(pct_short)
    entry_limit = limit_entry_price(last_close, bias)

    levels = compute_trade_levels(
        entry=entry_limit,
        pred_df=pred_df,
        bias=bias,
        target_bar_index=target_idx,
        interval=tf.interval,
    )
    pred_close_short = levels.target if levels else float(pred_df["close"].iloc[target_idx])
    pred_close_long = float(pred_df["close"].iloc[-1])
    ticker = symbol.replace("USDT", "")

    chart_hist = hist.iloc[-tf.chart_bars:][["timestamps", "open", "high", "low", "close"]].copy()
    candle_ts = _as_utc_ts(last_ts)

    return {
        "ticker": ticker,
        "symbol": symbol,
        "timeframe": tf.label,
        "interval": tf.interval,
        "last_close": last_close,
        "entry_limit": entry_limit,
        "candle_time": candle_ts,
        "pred_close": pred_close_short,
        "pred_close_long": pred_close_long,
        "stop_price": levels.stop if levels else last_close,
        "target_pct": levels.target_pct if levels else pct_change_to_bar(pred_df, last_close, target_idx),
        "stop_pct": levels.stop_pct if levels else 0.0,
        "trade_rr": levels.rr if levels else 0.0,
        "pct": pct_long,
        "pct_short": pct_short,
        "pct_long": pct_long,
        "bias": bias,
        "icon": icon,
        "pred_len": tf.pred_len,
        "short_bars": (levels.target_bars if levels else target_idx + 1),
        "bias_bars": bias_idx + 1,
        "chart_hist": chart_hist,
        "pred_df": pred_df,
        "split_ts": last_ts,
        "has_levels": levels is not None,
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

    for ax, item in zip(axes, analyses):
        ax.set_facecolor("#1e293b")
        hist = item["chart_hist"]
        pred = item["pred_df"].copy()
        pred["timestamps"] = pd.to_datetime(pred.index)

        plot_candles(ax, hist, "#22c55e", "#ef4444", alpha=0.95)
        plot_candles(ax, pred, "#60a5fa", "#f97316", alpha=0.88)

        split = item["split_ts"]
        ax.axvline(split, color="#fbbf24", linestyle="--", linewidth=1.2, alpha=0.9, label="Agora → previsto")

        sign = "+" if item["pct_short"] >= 0 else ""
        ax.set_title(
            f"{item['ticker']} {item['icon']} {item['bias']}  |  "
            f"Base ${item['last_close']:,.2f}  →  Alvo ${item['pred_close']:,.2f} "
            f"({sign}{item.get('target_pct', item['pct_short']):.2f}%)",
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


def _fmt_price(value: float) -> str:
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.4f}"


def _fmt_ts(ts: pd.Timestamp) -> str:
    return ts.strftime("%d/%m/%Y %H:%M UTC")


def format_timeframe_summary(tf_label: str, results: list[dict], analysis_time: datetime) -> str:
    pred_len = results[0]["pred_len"]
    target_bars = results[0]["short_bars"]
    bias_bars = results[0].get("bias_bars", KRONOS_BIAS_BARS)
    lines = [
        f"<b>━━ {tf_label} ━━</b>",
        f"🕐 Análise gerada: <b>{analysis_time.strftime('%d/%m/%Y %H:%M UTC')}</b>",
        f"<i>Viés = {bias_bars} barras | Alvo trade = {target_bars} barras | Máx. = {pred_len} barras</i>",
        "",
    ]
    corrs = hist_return_correlation(results)
    for r in results:
        ss = "+" if r["pct_short"] >= 0 else ""
        sl = "+" if r["pct_long"] >= 0 else ""
        corr_txt = ""
        if r["ticker"] != "BTC" and r["ticker"] in corrs:
            corr_txt = f" (corr. BTC {corrs[r['ticker']]:.2f})"
        now_p = _fmt_price(r["last_close"])
        ent_p = _fmt_price(r.get("entry_limit", r["last_close"]))
        tgt = _fmt_price(r["pred_close"])
        tgt_long = _fmt_price(r["pred_close_long"])
        stp = _fmt_price(r.get("stop_price", r["last_close"]))
        tp = r.get("target_pct", r["pct_short"])
        sp = r.get("stop_pct", 0.0)
        rr = r.get("trade_rr", 0.0)
        candle = _fmt_ts(r["candle_time"])
        trade_badge = ""
        if r.get("tradeable"):
            trade_badge = " · ✅ <i>operável</i>"
        elif r.get("align_note"):
            trade_badge = f" · ⚠️ <i>{r['align_note']}</i>"
        lines.append(
            f"{r['icon']} <b>{r['ticker']}</b> — {r['bias']}{corr_txt}{trade_badge}\n"
            f"  📍 <b>Preço base:</b> {now_p}\n"
            f"  💰 <b>Entrada limite:</b> {ent_p}\n"
            f"     <i>último candle MEXC: {candle}</i>\n"
            f"  🎯 <b>Alvo</b> ({target_bars} barras): {tgt} ({'+' if tp >= 0 else ''}{tp:.2f}%)\n"
            f"  🛑 <b>Stop</b> (R:R {rr:.1f}): {stp} ({sp:+.2f}%)\n"
            f"  📐 Viés curto ({bias_bars}b): {ss}{r['pct_short']:.2f}% · "
            f"ref. longo ({pred_len}b): {tgt_long} ({sl}{r['pct_long']:.2f}%)"
        )
    for note in coherence_notes(results, corrs):
        lines.append("")
        lines.append(note)
    return "\n".join(lines)


def format_full_report(sections: list[str]) -> str:
    header = (
        f"Modelo: <code>{KRONOS_MODEL}</code>\n"
        "<i>Previsão estatística (ML), não análise fundamental. "
        "Cripto costuma mover em bloco — divergências fortes costumam ser ruído.</i>"
    )
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


def _touch_last_ok() -> None:
    stamp = Path(os.environ.get("KRONOS_LAST_OK", "/data/kronos.last_ok"))
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    except OSError as e:
        logger.warning("Não gravou kronos.last_ok: %s", e)


def execute_run(
    predictor,
    tf_filter: str | None = None,
    *,
    candle_wake_at: datetime | None = None,
    text_before_chart: bool = True,
) -> None:
    symbols = resolve_mexc_symbols()
    timeframes = resolve_timeframes(tf_filter)
    if not symbols or not timeframes:
        raise RuntimeError("KRONOS_TICKERS ou KRONOS_TIMEFRAMES vazio")

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M")
    run_id = new_run_id()
    summary_sections: list[str] = []
    all_errors: list[str] = []
    results_by_interval: dict[str, list[dict]] = {}
    ran_intervals: set[str] = set()

    for tf in timeframes:
        results: list[dict] = []
        expected_open = (
            expected_last_candle_open(candle_wake_at, tf.interval) if candle_wake_at else None
        )

        for symbol in symbols:
            try:
                results.append(
                    analyze_symbol(
                        predictor, symbol, tf, expected_candle_open=expected_open
                    )
                )
                logger.info("OK %s @ %s", symbol, tf.interval)
            except CandleNotReadyError:
                raise
            except Exception as exc:
                logger.exception("%s @ %s: %s", symbol, tf.interval, exc)
                all_errors.append(f"{symbol}@{tf.interval}: {exc}")

        if results:
            results_by_interval[tf.interval] = results
            update_from_results(results, tf.interval)
            ran_intervals.add(tf.interval.lower())

    biases_by_ticker = merge_with_results(results_by_interval)
    for interval, results in results_by_interval.items():
        for r in results:
            ok, note = tradeable_for_interval(r["ticker"], interval, biases_by_ticker[r["ticker"]])
            r["tradeable"] = ok
            r["align_note"] = note

    apply_to_results(results_by_interval)

    chart_jobs: list[tuple] = []

    for tf in timeframes:
        results = results_by_interval.get(tf.interval, [])
        if not results:
            continue

        to_log = [
            r for r in results
            if should_log_to_scorecard(tf.interval, r.get("tradeable", False), r)
        ]
        if to_log:
            log_predictions(
                run_id, now, tf.label, tf.interval,
                to_log[0]["short_bars"], to_log[0]["pred_len"], to_log,
            )
            logger.info("Catálogo %s: %d/%d operáveis", tf.interval, len(to_log), len(results))
        summary_sections.append(format_timeframe_summary(tf.label, results, now))
        chart_jobs.append((tf, results))

    if not summary_sections:
        send_kronos_alert("Erro — sem previsões", "\n".join(all_errors) or "Falha desconhecida")
        return

    if len(timeframes) == 1:
        title = f"Previsão {timeframes[0].label} — {now.strftime('%d/%m/%Y %H:%M UTC')}"
    else:
        title = f"Previsão — {now.strftime('%d/%m/%Y %H:%M UTC')}"
    body = format_full_report(summary_sections)
    body = (
        f"📍 <b>Referência:</b> preço base = último candle MEXC fechado; entrada limite com pullback "
        f"{os.environ.get('KRONOS_LIMIT_ENTRY_OFFSET_PCT', '0.15')}%.\n"
        f"🎯 <b>Alvo / 🛑 Stop:</b> previsto em mais barras, com R:R mínimo "
        f"(stop menor que o alvo em distância %).\n\n"
        + body
    )
    if all_errors:
        body += "\n\n⚠️ Erros:\n" + "\n".join(all_errors[:10])

    if biases_by_ticker:
        body += "\n\n" + format_alignment_report(biases_by_ticker)
    if tf_filter or len(timeframes) > 1:
        body += f"\n<i>TFs: {format_cache_note(biases_by_ticker, ran_intervals)}</i>"
    show_scorecard = tf_filter in (None, "4h") or (
        len(timeframes) > 1 and "4h" in results_by_interval
    )
    if show_scorecard:
        body += f"\n\n{format_scorecard_brief(7)}"
    body += f"\n\n{format_kronos_footer()}"
    body += f"\n<i>Run ID: {run_id}</i>\n{format_config_footer()}"

    if not text_before_chart:
        for tf, results in chart_jobs:
            chart_path = CHART_DIR / f"kronos_{tf.interval}_{stamp}.png"
            try:
                render_timeframe_chart(results, tf.label, chart_path)
                send_kronos_photo(
                    str(chart_path),
                    f"Gráfico {tf.label} — {now.strftime('%Y-%m-%d %H:%M UTC')}",
                )
            except Exception as exc:
                logger.exception("Gráfico %s falhou: %s", tf.label, exc)
                all_errors.append(f"gráfico {tf.label}: {exc}")

    send_kronos_alert(title, body)
    _touch_last_ok()
    logger.info("Texto [KRONOS] enviado (%d timeframes)", len(summary_sections))

    if text_before_chart:
        for tf, results in chart_jobs:
            chart_path = CHART_DIR / f"kronos_{tf.interval}_{stamp}.png"
            try:
                render_timeframe_chart(results, tf.label, chart_path)
                send_kronos_photo(
                    str(chart_path),
                    f"Gráfico {tf.label} — {now.strftime('%Y-%m-%d %H:%M UTC')}",
                )
            except Exception as exc:
                logger.exception("Gráfico %s falhou: %s", tf.label, exc)


def run(
    tf_filter: str | None = None,
    *,
    predictor=None,
    notify_processing: bool = True,
    candle_wake_at: datetime | None = None,
    text_before_chart: bool = True,
) -> None:
    symbols = resolve_mexc_symbols()
    timeframes = resolve_timeframes(tf_filter)
    if not symbols or not timeframes:
        raise RuntimeError("KRONOS_TICKERS ou KRONOS_TIMEFRAMES vazio")

    if predictor is None:
        if notify_processing:
            tf_names = ", ".join(tf.label for tf in timeframes)
            send_kronos_alert(
                "Processando",
                f"Gerando previsões para: <code>{', '.join(symbols)}</code>\n"
                f"Timeframe(s): <code>{tf_names}</code>\n"
                f"<i>Carregando modelo ML (pode levar vários minutos)...</i>",
            )
        predictor = load_predictor()

    execute_run(
        predictor,
        tf_filter,
        candle_wake_at=candle_wake_at,
        text_before_chart=text_before_chart,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Previsão Kronos → Telegram [KRONOS]")
    parser.add_argument(
        "--tf",
        choices=["1h", "4h", "1d"],
        default=None,
        help="Roda só este timeframe (cron no fechamento do candle)",
    )
    args = parser.parse_args()
    try:
        run(tf_filter=args.tf)
    except CandleNotReadyError as exc:
        logger.warning("candle não pronto: %s", exc)
        sys.exit(2)
    except Exception as exc:
        logger.exception("kronos_signal abortado: %s", exc)
        try:
            send_kronos_alert("Erro fatal", str(exc)[:500])
        except Exception:
            pass
        sys.exit(1)
