"""
Catálogo e scorecard das previsões Kronos (SQLite /data).

Simulação: capital 1000 USDC, margem 100 USDC × alavancagem (padrão 20x),
ordens LIMITE na MEXC com taxas sobre nocional (maker/taker).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import pandas as pd

from lib.db import get_conn, init_db, now_utc
from lib.mexc_klines import bars_to_timedelta, fetch_bars_list, fetch_close_at

logger = logging.getLogger(__name__)

NEUTRAL_THRESHOLD_PCT = 0.15
INITIAL_CAPITAL_USDC = float(os.environ.get("KRONOS_INITIAL_CAPITAL", "1000"))
MARGIN_USDC = float(os.environ.get("KRONOS_POSITION_USDC", "100"))
LEVERAGE = max(1.0, float(os.environ.get("KRONOS_LEVERAGE", "20")))
POSITION_USDC = MARGIN_USDC  # alias: margem por entrada
PNL_FLAT_THRESHOLD_USDC = float(os.environ.get("KRONOS_FLAT_THRESHOLD_USDC", "0.05"))


def notional_usdc() -> float:
    """Exposição nocional = margem × alavancagem."""
    return MARGIN_USDC * LEVERAGE

FEE_MAKER_PCT = float(os.environ.get("KRONOS_FEE_MAKER_PCT", "0.02"))
FEE_TAKER_PCT = float(os.environ.get("KRONOS_FEE_TAKER_PCT", "0.05"))
LIMIT_ENTRY_BARS = int(os.environ.get("KRONOS_LIMIT_ENTRY_BARS", "4"))
LIMIT_EXIT_BARS = int(os.environ.get("KRONOS_LIMIT_EXIT_BARS", "0"))


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
                error_long_pct      REAL,
                order_type          TEXT DEFAULT 'limit',
                entry_filled_short  INTEGER,
                entry_fill_price_short REAL,
                exit_fill_price_short  REAL,
                fee_usdc_short      REAL,
                exit_type_short     TEXT,
                stop_price_short    REAL
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
        ("order_type", "TEXT DEFAULT 'limit'"),
        ("entry_filled_short", "INTEGER"),
        ("entry_fill_price_short", "REAL"),
        ("exit_fill_price_short", "REAL"),
        ("fee_usdc_short", "REAL"),
        ("exit_type_short", "TEXT"),
        ("stop_price_short", "REAL"),
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


def _fee_usdc(notional: float, fee_pct: float) -> float:
    return notional * (fee_pct / 100.0)


def _limit_entry_fill(
    bars: list[dict],
    limit_price: float,
    side: str,
    max_bars: int,
) -> tuple[bool, float | None, int]:
    for i, b in enumerate(bars[:max_bars]):
        if side == "long":
            if b["low"] <= limit_price:
                return True, limit_price, i
        else:
            if b["high"] >= limit_price:
                return True, limit_price, i
    return False, None, -1


def _limit_exit_fill(bars: list[dict], limit_price: float, side: str) -> tuple[bool, float | None]:
    for b in bars:
        if side == "long":
            if b["high"] >= limit_price:
                return True, limit_price
        else:
            if b["low"] <= limit_price:
                return True, limit_price
    return False, None


def _stop_hit(bar: dict, stop: float, side: str) -> bool:
    if side == "long":
        return float(bar["low"]) <= stop
    return float(bar["high"]) >= stop


def simulate_limit_trade(
    *,
    bias: str,
    price_base: float,
    target: float,
    stop: float | None,
    bars_after_signal: list[dict],
    due_close: float,
) -> dict:
    """Entrada limite no base; saída no alvo limite, stop limite, ou taker no vencimento."""
    if bias == "NEUTRO" or not bars_after_signal:
        return {
            "entry_filled": False,
            "entry_fill_price": None,
            "exit_fill_price": due_close,
            "sim_return_pct": 0.0,
            "pnl_usdc": 0.0,
            "fee_usdc": 0.0,
            "result": "skip",
            "exit_type": "none",
        }

    side = "long" if bias == "BULLISH" else "short"
    entry_ok, entry_px, entry_idx = _limit_entry_fill(
        bars_after_signal, price_base, side, LIMIT_ENTRY_BARS
    )
    if not entry_ok or entry_px is None:
        return {
            "entry_filled": False,
            "entry_fill_price": None,
            "exit_fill_price": None,
            "sim_return_pct": 0.0,
            "pnl_usdc": 0.0,
            "fee_usdc": 0.0,
            "result": "no_fill",
            "exit_type": "entry_timeout",
        }

    notional = notional_usdc()
    fee_entry = _fee_usdc(notional, FEE_MAKER_PCT)
    exit_bars = bars_after_signal[entry_idx + 1 :]
    if LIMIT_EXIT_BARS > 0:
        exit_bars = exit_bars[:LIMIT_EXIT_BARS]

    exit_px = None
    exit_type = "market_due"
    for bar in exit_bars:
        if stop is not None and _stop_hit(bar, stop, side):
            exit_px = stop
            exit_type = "stop_loss"
            break
        if side == "long" and float(bar["high"]) >= target:
            exit_px = target
            exit_type = "limit_target"
            break
        if side == "short" and float(bar["low"]) <= target:
            exit_px = target
            exit_type = "limit_target"
            break

    if exit_px is None:
        exit_px = due_close
        exit_type = "market_due"

    fee_exit = _fee_usdc(
        notional,
        FEE_MAKER_PCT if exit_type == "limit_target" else FEE_TAKER_PCT,
    )

    if side == "long":
        gross_pct = (exit_px - entry_px) / entry_px * 100.0
    else:
        gross_pct = (entry_px - exit_px) / entry_px * 100.0

    total_fee = fee_entry + fee_exit
    gross_pnl = notional * (gross_pct / 100.0)
    net_pnl = gross_pnl - total_fee
    # Liquidação: perda máxima = margem (100% da margem)
    if net_pnl < -MARGIN_USDC:
        net_pnl = -MARGIN_USDC
    net_pct = (net_pnl / MARGIN_USDC) * 100.0

    if net_pnl > PNL_FLAT_THRESHOLD_USDC:
        result = "gain"
    elif net_pnl < -PNL_FLAT_THRESHOLD_USDC:
        result = "loss"
    else:
        result = "flat"

    return {
        "entry_filled": True,
        "entry_fill_price": entry_px,
        "exit_fill_price": exit_px,
        "sim_return_pct": round(net_pct, 4),
        "pnl_usdc": round(net_pnl, 2),
        "fee_usdc": round(total_fee, 4),
        "result": result,
        "exit_type": exit_type,
    }


def log_predictions(
    run_id: str,
    analysis_time: datetime,
    tf_label: str,
    interval: str,
    short_bars: int,
    pred_len: int,
    results: list[dict],
) -> int:
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
                    due_short, due_long, position_usdc, order_type, stop_price_short
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    MARGIN_USDC,
                    "limit",
                    r.get("stop_price"),
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


def _sim_return_market(bias: str, actual_pct: float) -> float:
    if bias == "BULLISH":
        return actual_pct
    if bias == "BEARISH":
        return -actual_pct
    return 0.0


def _result_label(pnl_usdc: float) -> str:
    if pnl_usdc > PNL_FLAT_THRESHOLD_USDC:
        return "gain"
    if pnl_usdc < -PNL_FLAT_THRESHOLD_USDC:
        return "loss"
    return "flat"


def _score_row_short_limit(conn, row: dict, now: str) -> dict | None:
    """Scorecard curto: ordens limite + taxas MEXC."""
    candle = pd.Timestamp(row["candle_time"]).tz_convert("UTC")
    due = pd.Timestamp(row["due_short"]).tz_convert("UTC")
    delta = bars_to_timedelta(row["interval"], 1)
    end = due + delta * 2

    actual = fetch_close_at(row["symbol"], row["interval"], due)
    bars = fetch_bars_list(row["symbol"], row["interval"], candle, end)
    if actual is None and bars:
        actual = bars[-1]["close"]
    if actual is None:
        return None

    base = row["price_base"]
    actual_pct = (actual - base) / base * 100
    hit = _direction_hit(row["bias"], actual_pct)
    err = abs(row["pct_short"] - actual_pct)

    candle_ms = int(candle.timestamp() * 1000)
    bars_after = [b for b in bars if b["ts"] > candle_ms]

    stop = row.get("stop_price_short")
    if stop is None:
        from lib.kronos_levels import compute_stop_from_target

        stop = compute_stop_from_target(base, float(row["target_short"]), row["bias"])

    sim = simulate_limit_trade(
        bias=row["bias"],
        price_base=base,
        target=float(row["target_short"] or base),
        stop=float(stop) if stop else None,
        bars_after_signal=bars_after,
        due_close=float(actual),
    )

    sim_return = sim["sim_return_pct"]
    pnl = sim["pnl_usdc"]
    result = sim["result"]

    conn.execute(
        """UPDATE kronos_predictions SET
            actual_short=?, scored_short_at=?, direction_hit_short=?,
            sim_return_short=?, pnl_usdc_short=?, result_short=?, error_short_pct=?,
            entry_filled_short=?, entry_fill_price_short=?, exit_fill_price_short=?,
            fee_usdc_short=?, exit_type_short=?
           WHERE id=?""",
        (
            actual,
            now,
            hit,
            sim_return,
            pnl,
            result,
            err,
            1 if sim.get("entry_filled") else 0,
            sim.get("entry_fill_price"),
            sim.get("exit_fill_price"),
            sim.get("fee_usdc", 0),
            sim.get("exit_type"),
            row["id"],
        ),
    )

    return {
        **row,
        "horizon": "short",
        "actual": actual,
        "actual_pct": actual_pct,
        "sim_return": sim_return,
        "pnl_usdc": pnl,
        "result": result,
        "direction_hit": hit,
        "entry_filled": sim.get("entry_filled"),
        "entry_fill_price": sim.get("entry_fill_price"),
        "exit_fill_price": sim.get("exit_fill_price"),
        "fee_usdc": sim.get("fee_usdc", 0),
        "exit_type": sim.get("exit_type"),
    }


def _score_row_long_market(conn, row: dict, now: str) -> dict | None:
    """Horizonte longo: close real no vencimento (sem limite, para referência)."""
    due = pd.Timestamp(row["due_long"])
    actual = fetch_close_at(row["symbol"], row["interval"], due)
    if actual is None:
        return None

    base = row["price_base"]
    actual_pct = (actual - base) / base * 100
    hit = _direction_hit(row["bias"], actual_pct)
    sim = _sim_return_market(row["bias"], actual_pct)
    raw_pnl = notional_usdc() * sim / 100.0
    pnl = round(max(-MARGIN_USDC, raw_pnl), 2)
    result = _result_label(pnl)
    err = abs(row["pct_long"] - actual_pct)

    conn.execute(
        """UPDATE kronos_predictions SET
            actual_long=?, scored_long_at=?, direction_hit_long=?,
            sim_return_long=?, pnl_usdc_long=?, result_long=?, error_long_pct=?
           WHERE id=?""",
        (actual, now, hit, sim, pnl, result, err, row["id"]),
    )

    return {
        **row,
        "horizon": "long",
        "actual": actual,
        "actual_pct": actual_pct,
        "sim_return": sim,
        "pnl_usdc": pnl,
        "result": result,
        "direction_hit": hit,
    }


def _score_row(conn, row: dict, horizon: str, now: str) -> dict | None:
    if horizon == "short":
        return _score_row_short_limit(conn, row, now)
    return _score_row_long_market(conn, row, now)


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

    _backfill_pnl()
    logger.info("Kronos tracker: %d horizontes avaliados", len(newly_scored))
    return newly_scored


def _backfill_pnl() -> None:
    """Preenche PnL em linhas antigas (antes da coluna existir)."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE kronos_predictions
               SET pnl_usdc_short = ROUND(? * sim_return_short / 100.0, 2),
                   result_short = CASE
                     WHEN ? * sim_return_short / 100.0 > ? THEN 'gain'
                     WHEN ? * sim_return_short / 100.0 < ? THEN 'loss'
                     ELSE 'flat' END
               WHERE scored_short_at IS NOT NULL
                 AND sim_return_short IS NOT NULL
                 AND (pnl_usdc_short IS NULL OR result_short IS NULL)
                 AND result_short NOT IN ('no_fill', 'skip')""",
            (
                POSITION_USDC, POSITION_USDC, PNL_FLAT_THRESHOLD_USDC,
                POSITION_USDC, -PNL_FLAT_THRESHOLD_USDC,
            ),
        )


def _row_to_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row


def _is_counted_trade(result: str | None) -> bool:
    return result in ("gain", "loss", "flat")


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
                      AND {result_col} IS NOT NULL
                      AND created_at >= datetime('now', ?)
                    ORDER BY {scored_col} ASC""",
                (window,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT * FROM kronos_predictions
                    WHERE {scored_col} IS NOT NULL AND {result_col} IS NOT NULL
                    ORDER BY {scored_col} ASC"""
            ).fetchall()

    rows = [_row_to_dict(r) for r in rows]
    traded = [r for r in rows if _is_counted_trade(r.get(result_col))]
    no_fill = sum(1 for r in rows if r.get(result_col) == "no_fill")

    if not traded:
        return {
            "count": 0,
            "no_fill": no_fill,
            "initial_capital": INITIAL_CAPITAL_USDC,
            "position_usdc": MARGIN_USDC,
            "leverage": LEVERAGE,
            "notional_usdc": notional_usdc(),
            "pending_short": _count_pending("short"),
            "pending_long": _count_pending("long"),
        }

    pnls = [r[pnl_col] for r in traded]
    hits = [r[f"direction_hit_{horizon}"] for r in traded if r.get(f"direction_hit_{horizon}") is not None]
    fees = sum(float(r.get("fee_usdc_short") or 0) for r in traded) if horizon == "short" else 0.0

    gains = [p for p in pnls if p > PNL_FLAT_THRESHOLD_USDC]
    losses = [p for p in pnls if p < -PNL_FLAT_THRESHOLD_USDC]
    flats = len(pnls) - len(gains) - len(losses)

    total_pnl = round(sum(pnls), 2)
    equity_end = round(INITIAL_CAPITAL_USDC + total_pnl, 2)
    return_on_capital_pct = round(total_pnl / INITIAL_CAPITAL_USDC * 100, 2)

    win_rate_pnl = round(100 * len(gains) / len(pnls), 1) if pnls else 0.0
    win_rate_dir = round(100 * sum(hits) / len(hits), 1) if hits else 0.0

    by_tf: dict[str, list[float]] = {}
    for r in traded:
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
        "no_fill": no_fill,
        "total_fees_usdc": round(fees, 2),
        "initial_capital": INITIAL_CAPITAL_USDC,
        "position_usdc": MARGIN_USDC,
        "leverage": LEVERAGE,
        "notional_usdc": notional_usdc(),
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


def get_timeframe_ranking(days: int | None = 30) -> list[dict]:
    """Ranking de acerto/PnL por timeframe (1H, 4H, Diário)."""
    init_kronos_tables()
    window = f"-{days} days" if days else None
    with get_conn() as conn:
        if window:
            rows = conn.execute(
                """SELECT timeframe, result_short, pnl_usdc_short, direction_hit_short
                   FROM kronos_predictions
                   WHERE scored_short_at IS NOT NULL AND result_short IN ('gain','loss','flat')
                     AND created_at >= datetime('now', ?)
                   ORDER BY timeframe""",
                (window,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT timeframe, result_short, pnl_usdc_short, direction_hit_short
                   FROM kronos_predictions
                   WHERE scored_short_at IS NOT NULL AND result_short IN ('gain','loss','flat')
                   ORDER BY timeframe"""
            ).fetchall()

    by_tf: dict[str, dict] = {}
    for tf, res, pnl, hit in rows:
        st = by_tf.setdefault(
            tf,
            {"timeframe": tf, "n": 0, "gains": 0, "pnl": 0.0, "dir_hits": 0, "dir_n": 0},
        )
        st["n"] += 1
        if res == "gain":
            st["gains"] += 1
        if pnl is not None:
            st["pnl"] += float(pnl)
        if hit is not None:
            st["dir_n"] += 1
            st["dir_hits"] += int(hit)

    ranked = []
    for st in by_tf.values():
        n = st["n"]
        st["win_rate_pnl_pct"] = round(100 * st["gains"] / n, 1) if n else 0.0
        st["accuracy_pct"] = round(100 * st["dir_hits"] / st["dir_n"], 1) if st["dir_n"] else 0.0
        st["pnl"] = round(st["pnl"], 2)
        ranked.append(st)

    ranked.sort(key=lambda x: (-x["win_rate_pnl_pct"], -x["pnl"]))
    return ranked


def format_daily_report_telegram() -> str:
    """Relatório diário: resumo 7d/30d + ranking por timeframe."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    s7 = _aggregate_stats(7)
    s30 = _aggregate_stats(30)
    rank30 = get_timeframe_ranking(30)
    rank7 = get_timeframe_ranking(7)
    pending = _count_pending("short")

    lines = [
        f"<b>📊 Relatório diário Kronos</b>",
        f"🕐 {now}",
        f"Pendentes aguardando vencimento: <b>{pending}</b>",
        "",
        format_scorecard_block("Últimos 7 dias", s7),
        "",
        format_scorecard_block("Últimos 30 dias", s30),
        "",
        "<b>🏆 Ranking por timeframe (7 dias)</b>",
    ]

    if rank7:
        for i, st in enumerate(rank7, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
            lines.append(
                f"{medal} <b>{st['timeframe']}</b>: {st['win_rate_pnl_pct']}% acerto PnL "
                f"({st['gains']}/{st['n']}) · dir. {st['accuracy_pct']}% · "
                f"PnL <b>${st['pnl']:+.2f}</b>"
            )
        lines.append(f"\n<i>Melhor TF (7d): <b>{rank7[0]['timeframe']}</b></i>")
    else:
        lines.append("<i>Sem trades fechados nos últimos 7 dias.</i>")

    lines.append("\n<b>🏆 Ranking por timeframe (30 dias)</b>")
    if rank30:
        for i, st in enumerate(rank30, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
            lines.append(
                f"{medal} <b>{st['timeframe']}</b>: {st['win_rate_pnl_pct']}% acerto PnL "
                f"({st['gains']}/{st['n']}) · dir. {st['accuracy_pct']}% · "
                f"PnL <b>${st['pnl']:+.2f}</b>"
            )
        lines.append(f"\n<i>Melhor TF (30d): <b>{rank30[0]['timeframe']}</b></i>")
    else:
        lines.append("<i>Sem trades fechados nos últimos 30 dias.</i>")

    return "\n".join(lines)


def _count_pending(horizon: str) -> int:
    col = "scored_short_at" if horizon == "short" else "scored_long_at"
    with get_conn() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM kronos_predictions WHERE {col} IS NULL"
        ).fetchone()[0]


def format_trade_result(r: dict) -> str:
    """Uma linha por previsão fechada (limite + taxas no horizonte curto)."""
    res = r.get("result", "")
    if res == "skip":
        return (
            f"➖ <b>NEUTRO</b> {r['ticker']} {r['timeframe']} — sem simulação\n"
            f"   Close vencimento: ${r['actual']:,.2f} ({r['actual_pct']:+.2f}%)"
        )
    if res == "no_fill":
        return (
            f"⏳ <b>SEM FILL</b> {r['ticker']} {r['timeframe']} {r['bias']}\n"
            f"   Entrada limite @ ${r['price_base']:,.2f} não preenchida em {LIMIT_ENTRY_BARS} barras"
        )

    icon = "✅" if res == "gain" else "❌" if res == "loss" else "➖"
    label = res.upper()
    created = r.get("created_at", "")[:16].replace("T", " ")
    fee = float(r.get("fee_usdc") or 0)
    exit_type = r.get("exit_type")
    if exit_type == "limit_target":
        exit_lbl = "limite no alvo"
    elif exit_type == "stop_loss":
        exit_lbl = "stop"
    else:
        exit_lbl = "fech. vencimento (taker)"
    entry_px = r.get("entry_fill_price") or r["price_base"]
    exit_px = r.get("exit_fill_price") or r["actual"]

    return (
        f"{icon} <b>{label}</b> {r['ticker']} {r['timeframe']} {r['bias']} · ordem limite\n"
        f"   Margem ${MARGIN_USDC:.0f} × {LEVERAGE:.0f}x (${notional_usdc():.0f} nocional)\n"
        f"   ${entry_px:,.2f} → ${exit_px:,.2f} ({exit_lbl}) · venc. ${r['actual']:,.2f}\n"
        f"   <b>PnL líq.: ${r['pnl_usdc']:+.2f}</b> ({r['sim_return']:+.2f}% s/ margem) · taxas ${fee:.2f} · {created}"
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
        pending = s.get("pending_short", 0)
        nf = s.get("no_fill", 0)
        extra = f" · {nf} sem fill" if nf else ""
        return f"<b>{label}</b>: ainda sem trades fechados ({pending} pendentes{extra})"

    cap = s["initial_capital"]
    pos = s["position_usdc"]
    tf_parts = " | ".join(
        f"{k} WR {s['by_timeframe_win_rate'].get(k, 0)}% (${s['by_timeframe_pnl'].get(k, 0):+.0f})"
        for k in s.get("by_timeframe_pnl", {})
    )
    pf = s.get("profit_factor")
    pf_txt = f"{pf:.2f}" if pf is not None else "n/a"
    nf = s.get("no_fill", 0)
    fees = s.get("total_fees_usdc", 0)

    return "\n".join([
        f"<b>{label}</b> — {s['count']} trades · margem ${pos:.0f} × {s.get('leverage', LEVERAGE):.0f}x "
        f"(nocional ${s.get('notional_usdc', notional_usdc()):.0f}) · capital ${cap:.0f}",
        f"  🎯 Acerto (PnL líq.): <b>{s['win_rate_pnl_pct']}%</b> "
        f"({s['gains']} gain / {s['losses']} loss / {s['flats']} flat)",
        f"  ⏳ Sem fill entrada: {nf} · taxas totais: ${fees:.2f}",
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
        f"margem <b>${MARGIN_USDC:.0f}</b> · <b>{LEVERAGE:.0f}x</b> "
        f"(nocional ${notional_usdc():.0f}/trade) · limite",
        f"Taxas MEXC sobre nocional: maker {FEE_MAKER_PCT}% · taker {FEE_TAKER_PCT}%",
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
        "Entrada limite no preço base (até "
        f"{LIMIT_ENTRY_BARS} barras); saída limite no alvo curto ou taker no vencimento. "
        f"Margem ${MARGIN_USDC:.0f} com {LEVERAGE:.0f}x; perda máx. sim. = margem (liquidação).</i>"
    )
    return "\n".join(lines)


def format_scorecard_brief(days: int = 7) -> str:
    s = _aggregate_stats(days)
    if s.get("count", 0) == 0:
        return (
            f"📊 <i>Scorecard {days}d: {s.get('pending_short', 0)} previsões aguardando fechar</i>"
        )
    nf = s.get("no_fill", 0)
    nf_txt = f" · {nf} sem fill" if nf else ""
    return (
        f"📊 <b>{days}d</b> {s['count']} trades ${s['position_usdc']:.0f}×{s.get('leverage', LEVERAGE):.0f}x{nf_txt}: "
        f"<b>{s['win_rate_pnl_pct']}%</b> gain "
        f"({s['gains']}✅/{s['losses']}❌) · "
        f"PnL <b>${s['total_pnl_usdc']:+.2f}</b> "
        f"(${s['initial_capital']:.0f}→${s['equity_end']:.2f})"
    )


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M") + "-" + uuid.uuid4().hex[:8]
