"""
lib/db.py — SQLite helper.

Tabelas:
    funding_rates      — histórico de funding por ticker
    price_snapshots    — BTC/MEXC e preços Hyperliquid
    portfolio          — saldo MEXC + posições Hyperliquid
    news_articles      — artigos com scores VADER e Haiku
    orchestrator_log   — sínteses do consensus (a cada 4h)

Todos os timestamps são UTC ISO-8601.
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/crypto_monitor.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Cria tabelas se não existirem. Seguro para rodar em todo start."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS funding_rates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                funding     REAL NOT NULL,
                mark_price  REAL,
                alerted     INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                source      TEXT NOT NULL,   -- 'mexc' | 'hyperliquid'
                ticker      TEXT NOT NULL,
                price       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                source      TEXT NOT NULL,   -- 'mexc' | 'hyperliquid'
                asset       TEXT NOT NULL,
                amount      REAL NOT NULL,
                usd_value   REAL
            );

            CREATE TABLE IF NOT EXISTS news_articles (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT NOT NULL,
                source        TEXT NOT NULL,
                title         TEXT NOT NULL,
                url           TEXT UNIQUE,
                vader_score   REAL,
                haiku_score   REAL,
                haiku_summary TEXT,
                alerted       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orchestrator_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                summary   TEXT NOT NULL
            );
        """)
    logger.info("DB initialized at %s", DB_PATH)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Funding ────────────────────────────────────────────────────────────────

def insert_funding(ticker: str, funding: float, mark_price: float | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO funding_rates (ts, ticker, funding, mark_price) VALUES (?,?,?,?)",
            (now_utc(), ticker, funding, mark_price),
        )


def mark_funding_alerted(row_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE funding_rates SET alerted=1 WHERE id=?", (row_id,))


# ── Preços ─────────────────────────────────────────────────────────────────

def insert_price(source: str, ticker: str, price: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO price_snapshots (ts, source, ticker, price) VALUES (?,?,?,?)",
            (now_utc(), source, ticker, price),
        )


# ── Portfolio ──────────────────────────────────────────────────────────────

def upsert_portfolio(source: str, asset: str, amount: float, usd_value: float | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO portfolio (ts, source, asset, amount, usd_value) VALUES (?,?,?,?,?)",
            (now_utc(), source, asset, amount, usd_value),
        )


# ── Notícias ───────────────────────────────────────────────────────────────

def insert_article(
    source: str,
    title: str,
    url: str | None,
    vader_score: float,
    haiku_score: float | None = None,
    haiku_summary: str | None = None,
) -> int | None:
    """Retorna o id inserido, ou None se URL duplicada."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO news_articles
                   (ts, source, title, url, vader_score, haiku_score, haiku_summary)
                   VALUES (?,?,?,?,?,?,?)""",
                (now_utc(), source, title, url, vader_score, haiku_score, haiku_summary),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # URL duplicada — artigo já processado


def mark_article_alerted(row_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE news_articles SET alerted=1 WHERE id=?", (row_id,))


def get_recent_signals(hours: int = 4) -> dict:
    """
    Retorna dict com sinais recentes para o orchestrator.
    Janela: últimas `hours` horas.
    """
    with get_conn() as conn:
        funding = conn.execute(
            """SELECT ticker, AVG(funding) as avg_funding, MAX(funding) as max_funding
               FROM funding_rates
               WHERE ts >= datetime('now', ? || ' hours')
               GROUP BY ticker""",
            (f"-{hours}",),
        ).fetchall()

        articles = conn.execute(
            """SELECT source, title, vader_score, haiku_score, haiku_summary
               FROM news_articles
               WHERE ts >= datetime('now', ? || ' hours')
                 AND (ABS(vader_score) > 0.3 OR haiku_score IS NOT NULL)
               ORDER BY ABS(COALESCE(haiku_score, vader_score)) DESC
               LIMIT 20""",
            (f"-{hours}",),
        ).fetchall()

        prices = conn.execute(
            """SELECT source, ticker, price, ts
               FROM price_snapshots
               WHERE ts >= datetime('now', '-1 hours')
               ORDER BY ts DESC""",
        ).fetchall()

    return {
        "funding": [dict(r) for r in funding],
        "articles": [dict(r) for r in articles],
        "prices": [dict(r) for r in prices],
    }


def insert_orchestrator_log(summary: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO orchestrator_log (ts, summary) VALUES (?,?)",
            (now_utc(), summary),
        )
