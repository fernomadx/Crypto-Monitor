"""
Catálogo e scorecard das previsões Kronos (SQLite /data).

Simulação padrão: capital 1000 USDC, 100 USDC por entrada (10% fixo).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import pandas as pd

from lib.db import get_conn, init_db, now_utc
from lib.mexc_klines import bars_to_timedelta, fetch_close_at

logger = logging.getLogger(__name__)

NEUTRAL_THRESHOLD_PCT = 0.15
INITIAL_CAPITAL_USDC = float(os.environ.get("KRONOS_INITIAL_CAPITAL", "1000"))
POSITION_USDC = float(os.environ.get("KRONOS_POSITION_USDC", "100"))
PNL_FLAT_THRESHOLD_USDC = 0.05


def init_kronos_tables() -> None:
    init_db()
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kronos_predictions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id              TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                ticker              TEXT NOT NULL,
                symbol              TEXT NOT NULL,
                timeframe           TEXT NOT NULL,
                interval            TEXT NOT NULL,
                candle_time         TEXT NOT NULL,
                price_base          REAL NOT NULL,
                target_short        REAL NOT NULL,
                target_long         REAL NOT NULL,
                pct_short           REAL NOT NULL,
                pct_long            REAL NOT NULL,
                bias                TEXT NOT NULL,
                short_bars          INTEGER NOT NULL,
                pred_len            INTEGER NOT NULL,
                due_short           TEXT NOT NULL,
                due_long            TEXT NOT NULL,
                position_usdc       REAL,
                actual_short        REAL,
                actual_long         REAL,
                scored_short_at     TEXT,
                scored_long_at      TEXT,
                direction_hit_short INTEGER,
                direction_hit_long  INTEGER,
                sim_return_short    REAL,
                sim_return_long     REAL,
                pnl_usdc_short      REAL,
                pnl_usdc_long       REAL,
                result_short        TEXT,
                result_long         TEXT,
                error_short_pct     REAL,
                error_long_pct      REAL
            );

            CREATE INDEX IF NOT EXISTS idx_kronos_pred_due_short
                ON kronos_predictions(due_short);
            CREATE INDEX IF NOT EXISTS idx_kronos_pred_scored
                ON kronos_predictions(scored_short_at, created_at);
        """)
        _migrate_columns(conn)


def _migrate_columns(conn) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(kronos_predictions)")}
    additions = [
        ("position_usdc", "REAL"),
        ("pnl_usdc_short", "REAL"),
        ("pnl_usdc_long", "REAL"),
        ("result_short", "TEXT"),
        ("result_long", "TEXT"),
    ]
    for name, typ in additions:
        if name not in existing:
            conn.execute(f"ALTER TABLE kronos_predictions ADD COLUMN {name} {typ}")


def _iso(ts: datetime | pd.Timestamp) -> str:
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


def _pnl_usdc(sim_return_pct: float) -> float:
    """PnL em USDC: posição fixa × retorno % da operação simulada."""
    return round(POSITION_USDC * sim_return_pct / 100.0, 2)


def _result_label(pnl_usdc: float) -> str:
    if pnl_usdc > PNL_FLAT_THRESHOLD_USDC:
        return "gain"
    if pnl_usdc < -PNL_FLAT_THRESHOLD_USDC:
        return "loss"
    return "flat"


def log_predictions(run_id: str, analysis_time: datetime, tf_label: str, interval: str,
                    short_bars: int, pred_len: int, results: list[dict]) -> int:
    init_kronos_tables()
    n = 0
    with get_conn() as conn:
        for r in results:
            candle = pd.Timestamp(r["candle_time"]).tz_convert("UTC")
            due_short = candle + bars_to_timedelta(interval, short_bars)
            due_long = candle + bars_to_timedelta(interval, pred_len)
            conn.execute(
                """INSERT INTO kronos_predictions (
                    run_id, created_at, ticker, symbol, timeframe, interval,
                    candle_time, price_base, target_short, target_long,
                    pct_short, pct_long, bias, short_bars, pred_len,
                    due_short, due_long, position_usdc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    _iso(analysis_time),
                    r["ticker"],
                    r["symbol"],
                    tf_label,
                    interval,
                    _iso(candle),
                    r["last_close"],
                    r["pred_close"],
                    r["pred_close_long"],
                    r["pct_short"],
                    r["pct_long"],
                    r["bias"],
                    short_bars,
                    pred_len,
                    _iso(due_short),
                    _iso(due_long),
                    POSITION_USDC,
                ),
            )
            n += 1
    logger.info("Kronos tracker: %d previsões salvas (run %s)", n, run_id)
    return n


def _direction_hit(bias: str, actual_pct: float) -> int | None:
    if bias == "BULLISH":
        return 1 if actual_pct > NEUTRAL_THRESHOLD_PCT else 0
    if bias == "BEARISH":
        return 1 if actual_pct < -NEUTRAL_THRESHOLD_PCT else 0
    return 1 if abs(actual_pct) <= NEUTRAL_THRESHOLD_PCT else 0


def _sim_return(bias: str, actual_pct: float) -> float:
    if bias == "BULLISH":
        return actual_pct
    if bias == "BEARISH":
        return -actual_pct
    return 0.0


def _score_row(conn, row: dict, horizon: str, now: str) -> dict | None:
    due_col = "due_short" if horizon == "short" else "due_long"
    pct_col = "pct_short" if horizon == "short" else "pct_long"
    due = pd.Timestamp(row[due_col])
    actual = fetch_close_at(row["symbol"], row["interval"], due)
    if actual is None:
        return None

    base = row["price_base"]
    actual_pct = (actual - base) / base * 100
    hit = _direction_hit(row["bias"], actual_pct)
    sim = _sim_return(row["bias"], actual_pct)
    pnl = _pnl_usdc(sim)
    result = _result_label(pnl)
    err = abs(row[pct_col] - actual_pct)

    if horizon == "short":
        conn.execute(
            """UPDATE kronos_predictions SET
                actual_short=?, scored_short_at=?, direction_hit_short=?,
                sim_return_short=?, pnl_usdc_short=?, result_short=?, error_short_pct=?
               WHERE id=?""",
            (actual, now, hit, sim, pnl, result, err, row["id"]),
        )
    else:
        conn.execute(
            """UPDATE kronos_predictions SET
                actual_long=?, scored_long_at=?, direction_hit_long=?,
                sim_return_long=?, pnl_usdc_long=?, result_long=?, error_long_pct=?
               WHERE id=?""",
            (actual, now, hit, sim, pnl, result, err, row["id"]),
        )

    return {
        **row,
        "horizon": horizon,
        "actual": actual,
        "actual_pct": actual_pct,
        "sim_return": sim,
        "pnl_usdc": pnl,
        "result": result,
        "direction_hit": hit,
    }


def score_mature_predictions() -> list[dict]:
    """Avalia previsões maduras. Retorna lista de trades fechados nesta execução."""
    init_kronos_tables()
    newly_scored: list[dict] = []
    now = now_utc()

    with get_conn() as conn:
        for horizon, col in (("short", "scored_short_at"), ("long", "scored_long_at")):
            due_col = "due_short" if horizon == "short" else "due_long"
            pending = conn.execute(
                f"""SELECT * FROM kronos_predictions
                    WHERE {col} IS NULL AND {due_col} <= ?""",
                (now,),
            ).fetchall()
            for row in pending:
                scored = _score_row(conn, dict(row), horizon, now)
                if scored:
                    newly_scored.append(scored)

    _backfill_pnl(conn=None)
    logger.info("Kronos tracker: %d horizontes avaliados", len(newly_scored))
    return newly_scored


def _backfill_pnl(conn=None) -> None:
    """Preenche PnL em linhas antigas (antes da coluna existir)."""
    with get_conn() as c:
        conn = conn or c
        conn.execute(
            """UPDATE kronos_predictions
               SET pnl_usdc_short = ROUND(? * sim_return_short / 100.0, 2),
                   result_short = CASE
                     WHEN ? * sim_return_short / 100.0 > ? THEN 'gain'
                     WHEN ? * sim_return_short / 100.0 < ? THEN 'loss'
                     ELSE 'flat' END
               WHERE scored_short_at IS NOT NULL
                 AND sim_return_short IS NOT NULL
                 AND (pnl_usdc_short IS NULL OR result_short IS NULL)""",
            (
                POSITION_USDC, POSITION_USDC, PNL_FLAT_THRESHOLD_USDC,
                POSITION_USDC, -PNL_FLAT_THRESHOLD_USDC,
            ),
        )


def _row_to_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


def _aggregate_stats(days: int | None = None, horizon: str = "short") -> dict:
    init_kronos_tables()
    _backfill_pnl()

    pnl_col = "pnl_usdc_short" if horizon == "short" else "pnl_usdc_long"
    result_col = "result_short" if horizon == "short" else "result_long"
    scored_col = "scored_short_at" if horizon == "short" else "scored_long_at"

    window = f"-{days} days" if days else None
    with get_conn() as conn:
        if window:
            rows = conn.execute(
                f"""SELECT * FROM kronos_predictions
                    WHERE {scored_col} IS NOT NULL
                      AND {pnl_col} IS NOT NULL
                      AND created_at >= datetime('now', ?)
                    ORDER BY {scored_col} ASC""",
                (window,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT * FROM kronos_predictions
                    WHERE {scored_col} IS NOT NULL AND {pnl_col} IS NOT NULL
                    ORDER BY {scored_col} ASC"""
            ).fetchall()

    rows = [_row_to_dict(r) for r in rows]
    if not rows:
        return {
            "count": 0,
            "initial_capital": INITIAL_CAPITAL_USDC,
            "position_usdc": POSITION_USDC,
            "pending_short": _count_pending("short"),
            "pending_long": _count_pending("long"),
        }

    pnls = [r[pnl_col] for r in rows]
    results = [r[result_col] for r in rows]
    hits = [r[f"direction_hit_{horizon}"] for r in rows if r.get(f"direction_hit_{horizon}") is not None]

    gains = [p for p in pnls if p > PNL_FLAT_THRESHOLD_USDC]
    losses = [p for p in pnls if p < -PNL_FLAT_THRESHOLD_USDC]
    flats = len(pnls) - len(gains) - len(losses)

    total_pnl = round(sum(pnls), 2)
    equity_end = round(INITIAL_CAPITAL_USDC + total_pnl, 2)
    return_on_capital_pct = round(total_pnl / INITIAL_CAPITAL_USDC * 100, 2)

    win_rate_pnl = round(100 * len(gains) / len(pnls), 1) if pnls else 0.0
    win_rate_dir = round(100 * sum(hits) / len(hits), 1) if hits else 0.0

    by_tf: dict[str, list[float]] = {}
    for r in rows:
        by_tf.setdefault(r["timeframe"], []).append(r[pnl_col])

    tf_pnl = {tf: round(sum(v), 2) for tf, v in by_tf.items()}
    tf_win_rate = {
        tf: round(100 * sum(1 for x in v if x > PNL_FLAT_THRESHOLD_USDC) / len(v), 1)
        for tf, v in by_tf.items()
    }

    gross_profit = sum(gains) if gains else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    return {
        "count": len(pnls),
        "initial_capital": INITIAL_CAPITAL_USDC,
        "position_usdc": POSITION_USDC,
        "equity_end": equity_end,
        "total_pnl_usdc": total_pnl,
        "return_on_capital_pct": return_on_capital_pct,
        "win_rate_pnl_pct": win_rate_pnl,
        "accuracy_pct": win_rate_dir,
        "gains": len(gains),
        "losses": len(losses),
        "flats": flats,
        "avg_gain_usdc": round(sum(gains) / len(gains), 2) if gains else 0.0,
        "avg_loss_usdc": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "avg_pnl_usdc": round(total_pnl / len(pnls), 2) if pnls else 0.0,
        "profit_factor": profit_factor,
        "by_timeframe_pnl": tf_pnl,
        "by_timeframe_win_rate": tf_win_rate,
        "pending_short": _count_pending("short"),
        "pending_long": _count_pending("long"),
    }


def _count_pending(horizon: str) -> int:
    col = "scored_short_at" if horizon == "short" else "scored_long_at"
    with get_conn() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM kronos_predictions WHERE {col} IS NULL"
        ).fetchone()[0]


def format_trade_result(r: dict) -> str:
    """Uma linha por previsão fechada."""
    icon = "✅" if r["result"] == "gain" else "❌" if r["result"] == "loss" else "➖"
    label = r["result"].upper()
    created = r.get("created_at", "")[:16].replace("T", " ")
    return (
        f"{icon} <b>{label}</b> {r['ticker']} {r['timeframe']} {r['bias']}\n"
        f"   Entrada sim: ${POSITION_USDC:.0f} @ base ${r['price_base']:,.2f}\n"
        f"   Saída real: ${r['actual']:,.2f} ({r['actual_pct']:+.2f}%)\n"
        f"   <b>PnL: ${r['pnl_usdc']:+.2f}</b> ({r['sim_return']:+.2f}% s/ posição) · {created}"
    )


def format_newly_scored_trades(trades: list[dict]) -> str:
    if not trades:
        return ""
    short_only = [t for t in trades if t.get("horizon") == "short"]
    if not short_only:
        short_only = trades
    lines = [f"<b>📋 Resultado desta rodada ({len(short_only)} fechadas)</b>"]
    for t in short_only[:12]:
        lines.append(format_trade_result(t))
    return "\n\n".join(lines)


def format_scorecard_block(label: str, s: dict) -> str:
    if s.get("count", 0) == 0:
        return f"<b>{label}</b>: ainda sem previsões fechadas"

    cap = s["initial_capital"]
    pos = s["position_usdc"]
    tf_parts = " | ".join(
        f"{k} WR {s['by_timeframe_win_rate'].get(k, 0)}% (${s['by_timeframe_pnl'].get(k, 0):+.0f})"
        for k in s.get("by_timeframe_pnl", {})
    )
    pf = s.get("profit_factor")
    pf_txt = f"{pf:.2f}" if pf is not None else "n/a"

    return "\n".join([
        f"<b>{label}</b> — {s['count']} entradas de ${pos:.0f} (capital ${cap:.0f})",
        f"  🎯 Acerto (PnL): <b>{s['win_rate_pnl_pct']}%</b> "
        f"({s['gains']} gain / {s['losses']} loss / {s['flats']} flat)",
        f"  📐 Acerto direção: {s['accuracy_pct']}%",
        f"  💰 PnL total: <b>${s['total_pnl_usdc']:+.2f}</b> "
        f"→ equity sim <b>${s['equity_end']:.2f}</b> ({s['return_on_capital_pct']:+.2f}% s/ ${cap:.0f})",
        f"  📊 Média gain: ${s['avg_gain_usdc']:+.2f} | média loss: ${s['avg_loss_usdc']:+.2f} | PF {pf_txt}",
        f"  Por TF: {tf_parts}" if tf_parts else "",
    ])


def format_scorecard_telegram(new_trades: list[dict] | None = None) -> str:
    s7 = _aggregate_stats(7)
    s30 = _aggregate_stats(30)
    lines = [
        "<b>📊 Scorecard Kronos — simulação</b>",
        f"Capital <b>${INITIAL_CAPITAL_USDC:.0f}</b> · "
        f"<b>${POSITION_USDC:.0f}</b> por entrada · horizonte curto",
        "",
    ]

    if new_trades:
        block = format_newly_scored_trades(new_trades)
        if block:
            lines.append(block)
            lines.append("")

    lines.append(format_scorecard_block("7 dias", s7))
    lines.append("")
    lines.append(format_scorecard_block("30 dias", s30))
    lines.append("")
    lines.append(
        f"<i>Pendentes: {s7.get('pending_short', 0)} curto. "
        "Cada trade = seguir viés no preço base, sair no close real do horizonte, "
        f"posição fixa ${POSITION_USDC:.0f} (sem taxas/alavancagem).</i>"
    )
    return "\n".join(lines)


def format_scorecard_brief(days: int = 7) -> str:
    s = _aggregate_stats(days)
    if s.get("count", 0) == 0:
        return (
            f"📊 <i>Scorecard {days}d: {s.get('pending_short', 0)} previsões aguardando fechar</i>"
        )
    return (
        f"📊 <b>{days}d</b> {s['count']} trades ${s['position_usdc']:.0f}: "
        f"<b>{s['win_rate_pnl_pct']}%</b> gain "
        f"({s['gains']}✅/{s['losses']}❌) · "
        f"PnL <b>${s['total_pnl_usdc']:+.2f}</b> "
        f"(${s['initial_capital']:.0f}→${s['equity_end']:.2f})"
    )


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M") + "-" + uuid.uuid4().hex[:8]
