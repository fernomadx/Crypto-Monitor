"""Análise MEXC (spot + futuros) — substitui o bot CCXT `📊 MEXC Análise`."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from lib.mexc_contract import (
    fetch_contract_klines,
    fetch_contract_ticker,
    fetch_funding_rate,
)
from lib.mexc_klines import fetch_klines
from lib.trade_desk.analysts import technical_report
from lib.trade_desk.indicators import enrich
from lib.trade_desk.models import Side

logger = logging.getLogger(__name__)

INTERVALS = ("1h", "4h")


@dataclass
class TfSlice:
    interval: str
    source: str
    close: float
    change_pct: float
    rsi: float | None
    side: str
    detail: str


@dataclass
class MexcReport:
    symbol: str
    spot: float | None
    futures: float | None
    basis_pct: float | None
    change_24h_pct: float | None
    high_24h: float | None
    low_24h: float | None
    funding_rate: float | None
    next_settle_utc: str | None
    hold_vol: float | None
    slices: list[TfSlice] = field(default_factory=list)
    bias: str = "NEUTRO"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_symbols(raw: str | None = None) -> list[str]:
    text = (raw or os.environ.get("MEXC_ANALISE_TICKERS") or os.environ.get("TICKERS") or "BTC").strip()
    out: list[str] = []
    for part in text.replace(";", ",").split(","):
        t = part.strip().upper()
        if not t:
            continue
        out.append(t if t.endswith("USDT") else f"{t}USDT")
    return out or ["BTCUSDT"]


def _pct(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return (a / b - 1.0) * 100.0


def _fmt_px(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:,.4f}"
    return f"{v:.6g}"


def _fmt_pct(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{digits}f}%"


def _side_icon(side: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(side, "⚪")


def _bias_from_slices(slices: list[TfSlice], funding: float | None, basis: float | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    score = 0.0
    by_tf = {s.interval: s for s in slices}
    for tf in INTERVALS:
        s = by_tf.get(tf)
        if not s:
            continue
        w = 1.2 if tf == "4h" else 0.8
        if s.side == "BUY":
            score += w
            reasons.append(f"{tf.upper()} {s.source} {s.detail}")
        elif s.side == "SELL":
            score -= w
            reasons.append(f"{tf.upper()} {s.source} {s.detail}")
        else:
            reasons.append(f"{tf.upper()} {s.source} neutro ({s.detail})")

    if funding is not None:
        fp = funding * 100.0
        if fp >= 0.03:
            score -= 0.35
            reasons.append(f"funding alto ({fp:+.4f}%) — longs pagam")
        elif fp <= -0.03:
            score += 0.35
            reasons.append(f"funding negativo ({fp:+.4f}%) — shorts pagam")
        else:
            reasons.append(f"funding calmo ({fp:+.4f}%)")

    if basis is not None:
        if basis >= 0.15:
            reasons.append(f"prêmio futuros {basis:+.3f}%")
        elif basis <= -0.15:
            reasons.append(f"desconto futuros {basis:+.3f}%")

    if score >= 0.9:
        return "ALTA", reasons
    if score <= -0.9:
        return "BAIXA", reasons
    return "NEUTRO", reasons


def _slice_from_df(df: pd.DataFrame, interval: str, source: str) -> TfSlice:
    last = float(df["close"].iloc[-1])
    lookback = min(len(df) - 1, 24 if interval == "1h" else 12)
    prev = float(df["close"].iloc[-1 - lookback]) if lookback > 0 else last
    change = _pct(last, prev) or 0.0
    report = technical_report(df)
    data = enrich(df).dropna()
    rsi_v = float(data["rsi"].iloc[-1]) if len(data) and "rsi" in data.columns else None
    return TfSlice(
        interval=interval,
        source=source,
        close=last,
        change_pct=change,
        rsi=rsi_v,
        side=report.side.value,
        detail=report.summary or report.side.value,
    )


def _fetch_tf(symbol: str, interval: str) -> tuple[pd.DataFrame, str, str | None]:
    try:
        return fetch_contract_klines(symbol, interval, limit=120), "futures", None
    except Exception as exc:
        warn = f"{interval} futures falhou ({exc}); usando spot"
        logger.warning("%s %s", symbol, warn)
        df = fetch_klines(symbol, interval, limit=120)
        return df, "spot", warn


def analyze_symbol(symbol: str) -> MexcReport:
    symbol = symbol.upper()
    warnings: list[str] = []
    spot_px: float | None = None
    fut_px: float | None = None
    change_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    hold_vol: float | None = None
    funding: float | None = None
    next_settle: str | None = None

    try:
        spot_df = fetch_klines(symbol, "1h", limit=2)
        spot_px = float(spot_df["close"].iloc[-1])
    except Exception as exc:
        warnings.append(f"spot: {exc}")

    try:
        tick = fetch_contract_ticker(symbol)
        fut_px = float(tick.get("lastPrice") or tick.get("fairPrice") or 0) or None
        rf = tick.get("riseFallRate")
        if rf is not None:
            change_24h = float(rf) * 100.0
        high_24h = float(tick["high24Price"]) if tick.get("high24Price") is not None else None
        low_24h = float(tick["lower24Price"] if tick.get("lower24Price") is not None else tick.get("low24Price") or 0) or None
        if tick.get("holdVol") is not None:
            hold_vol = float(tick["holdVol"])
    except Exception as exc:
        warnings.append(f"ticker futures: {exc}")

    try:
        fund = fetch_funding_rate(symbol)
        if fund.get("fundingRate") is not None:
            funding = float(fund["fundingRate"])
        ts = fund.get("nextSettleTime")
        if ts:
            next_settle = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%H:%M UTC")
        if fut_px is None and fund.get("fairPrice") is not None:
            fut_px = float(fund["fairPrice"])
    except Exception as exc:
        warnings.append(f"funding: {exc}")

    basis = None
    if spot_px and fut_px:
        basis = _pct(fut_px, spot_px)

    slices: list[TfSlice] = []
    for interval in INTERVALS:
        try:
            df, source, warn = _fetch_tf(symbol, interval)
            if warn:
                warnings.append(warn)
            slices.append(_slice_from_df(df, interval, source))
        except Exception as exc:
            warnings.append(f"{interval}: {exc}")

    if fut_px is None and slices:
        fut_px = slices[0].close

    bias, reasons = _bias_from_slices(slices, funding, basis)
    ticker = symbol.replace("USDT", "")
    return MexcReport(
        symbol=ticker,
        spot=spot_px,
        futures=fut_px,
        basis_pct=basis,
        change_24h_pct=change_24h,
        high_24h=high_24h,
        low_24h=low_24h,
        funding_rate=funding,
        next_settle_utc=next_settle,
        hold_vol=hold_vol,
        slices=slices,
        bias=bias,
        reasons=reasons,
        warnings=warnings,
    )


def format_telegram(report: MexcReport, *, now: datetime | None = None) -> str:
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    fund_pct = report.funding_rate * 100.0 if report.funding_rate is not None else None
    lines = [
        f"📊 <b>MEXC Análise</b> · {report.symbol} · <i>{ts}</i>",
        f"Spot <b>{_fmt_px(report.spot)}</b>  Fut <b>{_fmt_px(report.futures)}</b>  "
        f"basis <b>{_fmt_pct(report.basis_pct, 3)}</b>",
        f"24h <b>{_fmt_pct(report.change_24h_pct)}</b>  "
        f"H {_fmt_px(report.high_24h)} / L {_fmt_px(report.low_24h)}",
        f"Funding <b>{_fmt_pct(fund_pct, 4)}</b>"
        + (f"  próximo {report.next_settle_utc}" if report.next_settle_utc else ""),
    ]
    for s in report.slices:
        rsi = f"RSI {s.rsi:.0f}" if s.rsi is not None else "RSI —"
        lines.append(
            f"{_side_icon(s.side)} <b>{s.interval.upper()}</b> ({s.source}) "
            f"{_fmt_px(s.close)}  Δ{_fmt_pct(s.change_pct)}  {rsi} → {s.side}"
        )
        if s.detail:
            lines.append(f"<i>{s.detail[:160]}</i>")

    bias_icon = {"ALTA": "🟢", "BAIXA": "🔴"}.get(report.bias, "⚪")
    lines.append(f"\nViés: {bias_icon} <b>{report.bias}</b>")
    for reason in report.reasons[:6]:
        lines.append(f"• {reason}")
    for warn in report.warnings[:4]:
        lines.append(f"⚠️ <i>{warn[:180]}</i>")
    lines.append("\n<i>Público MEXC (spot + USDT-M). Não é ordem automática.</i>")
    return "\n".join(lines)


def analyze_now(symbol: str | None = None) -> str:
    """Texto HTML para Telegram (/mexc) ou CLI."""
    symbols = resolve_symbols(symbol)
    parts = [format_telegram(analyze_symbol(sym)) for sym in symbols]
    return "\n\n————————\n\n".join(parts)


def reports_as_dict(report: MexcReport) -> dict[str, Any]:
    return {
        "symbol": report.symbol,
        "spot": report.spot,
        "futures": report.futures,
        "basis_pct": report.basis_pct,
        "change_24h_pct": report.change_24h_pct,
        "funding_rate": report.funding_rate,
        "bias": report.bias,
        "slices": [
            {
                "interval": s.interval,
                "source": s.source,
                "close": s.close,
                "side": s.side,
            }
            for s in report.slices
        ],
        "warnings": report.warnings,
    }
