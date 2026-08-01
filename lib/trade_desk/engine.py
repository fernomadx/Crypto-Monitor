from __future__ import annotations

import os
from typing import Any

import pandas as pd

from lib.trade_desk.analysts import (
    kronos_as_report,
    momentum_report,
    structure_report,
    technical_report,
)
from lib.trade_desk.models import AnalystReport, DeskVerdict, Side


def _ohlcv_from_kronos_result(r: dict[str, Any]) -> pd.DataFrame | None:
    hist = r.get("chart_hist")
    if hist is None or getattr(hist, "empty", True):
        return None
    df = hist.copy()
    # Kronos chart_hist may lack volume — synthesize neutral volume for indicators
    if "volume" not in df.columns:
        df["volume"] = 1.0
    # Prefer richer frame if pred attached history elsewhere
    return df


def _ohlcv_from_mexc(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame | None:
    try:
        from lib.mexc_klines import fetch_klines

        raw = fetch_klines(symbol, interval, limit=limit)
        cols = ["open", "high", "low", "close", "volume"]
        return raw[cols].copy()
    except Exception:
        return None


def consensus(reports: list[AnalystReport], max_size_pct: float) -> tuple[Side, float, float, str]:
    weights = {
        "kronos": 0.4,
        "technical": 0.3,
        "sentiment": 0.15,
        "structure": 0.15,
    }
    buy = sell = 0.0
    for r in reports:
        w = weights.get(r.name, 0.2) * r.confidence
        if r.side == Side.BUY:
            buy += w
        elif r.side == Side.SELL:
            sell += w
    total = buy + sell
    if total < 1e-9:
        return Side.HOLD, 0.0, 0.0, "Sem consenso"
    if buy >= sell:
        side, conf, margin = Side.BUY, buy / total, buy - sell
    else:
        side, conf, margin = Side.SELL, sell / total, sell - buy
    if conf < 0.5:
        return Side.HOLD, conf, 0.0, f"Consenso fraco ({side.value}@{conf:.2f})"
    size = min(max_size_pct, max_size_pct * (0.4 + 0.6 * conf) * min(1.0, margin * 2))
    detail = " | ".join(f"{r.name}:{r.side.value}@{r.confidence:.2f}" for r in reports)
    return side, round(conf, 3), round(size, 4), detail


def evaluate_symbol(
    *,
    symbol: str,
    interval: str,
    kronos_result: dict[str, Any] | None = None,
    df: pd.DataFrame | None = None,
) -> DeskVerdict:
    """Roda mesa multi-agente e cruza com viés Kronos (se houver)."""
    max_size = float(os.environ.get("TRADE_DESK_MAX_POSITION_PCT", "0.25"))
    min_conf = float(os.environ.get("TRADE_DESK_MIN_CONFIDENCE", "0.55"))

    frame = df
    if frame is None and kronos_result is not None:
        frame = _ohlcv_from_kronos_result(kronos_result)
    if frame is None or len(frame) < 40:
        mexc_df = _ohlcv_from_mexc(symbol, interval)
        if mexc_df is not None and len(mexc_df) >= 30:
            frame = mexc_df
    if frame is None or len(frame) < 30:
        return DeskVerdict(
            Side.HOLD,
            0.0,
            0.0,
            None,
            kronos_result.get("bias") if kronos_result else None,
            "Sem OHLCV para desk",
            [],
            ticker=(kronos_result or {}).get("ticker") or symbol.replace("USDT", ""),
        )

    reports = [
        technical_report(frame),
        momentum_report(frame),
        structure_report(frame),
    ]
    k_bias = kronos_result.get("bias") if kronos_result else None
    k_rep = kronos_as_report(
        k_bias,
        kronos_result.get("pct_short") if kronos_result else None,
        kronos_result.get("tradeable") if kronos_result else None,
    )
    if k_rep:
        reports.append(k_rep)

    side, conf, size, detail = consensus(reports, max_size)
    if conf < min_conf:
        side, size = Side.HOLD, 0.0

    agrees: bool | None = None
    if k_bias:
        kb = k_bias.upper()
        if side == Side.BUY:
            agrees = kb.startswith("BULL")
        elif side == Side.SELL:
            agrees = kb.startswith("BEAR")
        else:
            agrees = kb.startswith("NEUT")

    summary = detail
    if k_bias is not None and agrees is not None:
        summary = ("✅ alinha Kronos" if agrees else "⚠️ diverge Kronos") + f" ({k_bias}) · " + detail

    return DeskVerdict(
        side,
        conf,
        size,
        agrees,
        k_bias,
        summary,
        reports,
        ticker=(kronos_result or {}).get("ticker") or symbol.replace("USDT", ""),
    )


def apply_desk_to_results(results_by_interval: dict[str, list[dict]]) -> list[DeskVerdict]:
    """Anexa desk_* nos results Kronos e pode vetar tradeable se TRADE_DESK_VETO=1."""
    veto = os.environ.get("TRADE_DESK_VETO", "1").strip().lower() in {"1", "true", "yes", "on"}
    require_agree = os.environ.get("TRADE_DESK_REQUIRE_AGREE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    verdicts: list[DeskVerdict] = []
    for interval, results in results_by_interval.items():
        for r in results:
            symbol = r.get("symbol") or f"{r.get('ticker', 'BTC')}USDT"
            v = evaluate_symbol(symbol=symbol, interval=interval, kronos_result=r)
            verdicts.append(v)
            r["desk_side"] = v.side.value
            r["desk_confidence"] = v.confidence
            r["desk_size_pct"] = v.size_pct
            r["desk_agrees"] = v.agrees_with_kronos
            r["desk_summary"] = v.summary
            if veto and r.get("tradeable"):
                if v.side == Side.HOLD or v.confidence < float(
                    os.environ.get("TRADE_DESK_MIN_CONFIDENCE", "0.55")
                ):
                    r["tradeable"] = False
                    r["align_note"] = (r.get("align_note") or "") + " | desk HOLD/low conf"
                elif require_agree and v.agrees_with_kronos is False:
                    r["tradeable"] = False
                    r["align_note"] = (r.get("align_note") or "") + " | desk diverge Kronos"
    return verdicts


def format_desk_section(verdicts: list[DeskVerdict]) -> str:
    if not verdicts:
        return ""
    lines = ["🧠 <b>Trade Desk</b> (técnico+momentum+estrutura+Kronos)"]
    for v in verdicts:
        icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(v.side.value, "⚪")
        agree = ""
        if v.agrees_with_kronos is True:
            agree = " · alinhado"
        elif v.agrees_with_kronos is False:
            agree = " · DIVERGE"
        label = v.ticker or "?"
        lines.append(
            f"{icon} <b>{label}</b> {v.side.value} conf={v.confidence:.2f} "
            f"size={v.size_pct:.0%}{agree}"
            + (f" · Kronos {v.kronos_bias}" if v.kronos_bias else "")
        )
        lines.append(f"<i>{v.summary[:180]}</i>")
    return "\n".join(lines)