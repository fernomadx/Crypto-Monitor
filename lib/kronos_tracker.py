"""
Catálogo e scorecard das previsões Kronos (SQLite /data).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pandas as pd

from lib.db import get_conn, init_db, now_utc
from lib.mexc_klines import bars_to_timedelta, fetch_close_at

logger = logging.getLogger(__name__)

NEUTRAL_THRESHOLD_PCT = 0.15


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
                actual_short        REAL,
                actual_long         REAL,
                scored_short_at     TEXT,
                scored_long_at      TEXT,
                direction_hit_short INTEGER,
                direction_hit_long  INTEGER,
                sim_return_short    REAL,
                sim_return_long     REAL,
                error_short_pct     REAL,
                error_long_pct      REAL
            );

            CREATE INDEX IF NOT EXISTS idx_kronos_pred_due_short
                ON kronos_predictions(due_short);
            CREATE INDEX IF NOT EXISTS idx_kronos_pred_scored
                ON kronos_predictions(scored_short_at, created_at);
        """)


def _iso(ts: datetime | pd.Timestamp) -> str:
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


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
                    due_short, due_long
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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


def score_mature_predictions() -> int:
    """Preenche actual_* para previsões cujo horizonte já passou."""
    init_kronos_tables()
    scored = 0
    now = now_utc()

    with get_conn() as conn:
        pending_short = conn.execute(
            """SELECT * FROM kronos_predictions
               WHERE scored_short_at IS NULL AND due_short <= ?""",
            (now,),
        ).fetchall()

        for row in pending_short:
            r = dict(row)
            due = pd.Timestamp(r["due_short"])
            actual = fetch_close_at(r["symbol"], r["interval"], due)
            if actual is None:
                continue
            base = r["price_base"]
            actual_pct = (actual - base) / base * 100
            hit = _direction_hit(r["bias"], actual_pct)
            sim = _sim_return(r["bias"], actual_pct)
            err = abs(r["pct_short"] - actual_pct)
            conn.execute(
                """UPDATE kronos_predictions SET
                    actual_short=?, scored_short_at=?, direction_hit_short=?,
                    sim_return_short=?, error_short_pct=?
                   WHERE id=?""",
                (actual, now, hit, sim, err, r["id"]),
            )
            scored += 1

        pending_long = conn.execute(
            """SELECT * FROM kronos_predictions
               WHERE scored_long_at IS NULL AND due_long <= ?""",
            (now,),
        ).fetchall()

        for row in pending_long:
            r = dict(row)
            due = pd.Timestamp(r["due_long"])
            actual = fetch_close_at(r["symbol"], r["interval"], due)
            if actual is None:
                continue
            base = r["price_base"]
            actual_pct = (actual - base) / base * 100
            hit = _direction_hit(r["bias"], actual_pct)
            sim = _sim_return(r["bias"], actual_pct)
            err = abs(r["pct_long"] - actual_pct)
            conn.execute(
                """UPDATE kronos_predictions SET
                    actual_long=?, scored_long_at=?, direction_hit_long=?,
                    sim_return_long=?, error_long_pct=?
                   WHERE id=?""",
                (actual, now, hit, sim, err, r["id"]),
            )
            scored += 1

    logger.info("Kronos tracker: %d horizontes avaliados", scored)
    return scored


def _aggregate_stats(days: int | None = None) -> dict:
    init_kronos_tables()
    window = f"-{days} days" if days else None
    with get_conn() as conn:
        if window:
            rows = conn.execute(
                """SELECT * FROM kronos_predictions
                   WHERE scored_short_at IS NOT NULL
                     AND created_at >= datetime('now', ?)""",
                (window,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM kronos_predictions WHERE scored_short_at IS NOT NULL"
            ).fetchall()

    if not rows:
        return {"count": 0}

    hits = [r["direction_hit_short"] for r in rows if r["direction_hit_short"] is not None]
    sims = [r["sim_return_short"] for r in rows if r["sim_return_short"] is not None]
    errors = [r["error_short_pct"] for r in rows if r["error_short_pct"] is not None]

    wins = [s for s in sims if s > 0]
    losses = [s for s in sims if s < 0]

    by_tf: dict[str, list[int]] = {}
    for r in rows:
        if r["direction_hit_short"] is None:
            continue
        by_tf.setdefault(r["timeframe"], []).append(r["direction_hit_short"])

    tf_accuracy = {
        tf: round(100 * sum(v) / len(v), 1) if v else 0.0
        for tf, v in by_tf.items()
    }

    total_sim = sum(sims) if sims else 0.0
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    return {
        "count": len(hits),
        "accuracy_pct": round(100 * sum(hits) / len(hits), 1) if hits else 0.0,
        "total_sim_return_pct": round(total_sim, 2),
        "avg_sim_return_pct": round(total_sim / len(sims), 3) if sims else 0.0,
        "avg_error_pct": round(sum(errors) / len(errors), 2) if errors else 0.0,
        "profit_factor": profit_factor,
        "wins": len(wins),
        "losses": len(losses),
        "by_timeframe": tf_accuracy,
        "pending_short": _count_pending("short"),
        "pending_long": _count_pending("long"),
    }


def _count_pending(horizon: str) -> int:
    col = "scored_short_at" if horizon == "short" else "scored_long_at"
    with get_conn() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM kronos_predictions WHERE {col} IS NULL"
        ).fetchone()[0]


def format_scorecard_telegram() -> str:
    s7 = _aggregate_stats(7)
    s30 = _aggregate_stats(30)
    lines = ["<b>📊 Scorecard Kronos</b>", ""]

    def block(label: str, s: dict) -> None:
        if s.get("count", 0) == 0:
            lines.append(f"<b>{label}</b>: ainda sem amostras fechadas")
            return
        pf = s["profit_factor"]
        pf_txt = f"{pf:.2f}" if pf is not None else "n/a"
        tf_parts = " | ".join(f"{k} {v}%" for k, v in s.get("by_timeframe", {}).items())
        lines.append(f"<b>{label}</b> ({s['count']} trades simulados, horizonte curto)")
        lines.append(f"  Acerto direção: <b>{s['accuracy_pct']}%</b>")
        lines.append(
            f"  Retorno simulado (seguir viés): <b>{s['total_sim_return_pct']:+.2f}%</b> "
            f"(média {s['avg_sim_return_pct']:+.3f}%/previsão)"
        )
        lines.append(f"  Erro médio vs real: {s['avg_error_pct']:.2f}% | PF: {pf_txt}")
        lines.append(f"  W/L: {s['wins']}/{s['losses']}")
        if tf_parts:
            lines.append(f"  Por TF: {tf_parts}")

    block("7 dias", s7)
    lines.append("")
    block("30 dias", s30)
    lines.append("")
    lines.append(
        f"<i>Pendentes de fechar: {s7.get('pending_short', 0)} curto / "
        f"{s7.get('pending_long', 0)} longo. "
        "Retorno simulado = entrar no viés no preço base e sair no close real do horizonte.</i>"
    )
    return "\n".join(lines)


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M") + "-" + uuid.uuid4().hex[:8]


def format_scorecard_brief(days: int = 7) -> str:
    s = _aggregate_stats(days)
    if s.get("count", 0) == 0:
        return (
            f"📊 <i>Scorecard {days}d: aguardando horizontes fecharem "
            f"({s.get('pending_short', 0)} pendentes)</i>"
        )
    return (
        f"📊 <b>Scorecard {days}d</b> ({s['count']} fechadas): "
        f"acerto <b>{s['accuracy_pct']}%</b> | "
        f"retorno sim. <b>{s['total_sim_return_pct']:+.2f}%</b> | "
        f"erro méd. {s['avg_error_pct']:.2f}%"
    )
