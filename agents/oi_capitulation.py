"""
agents/oi_capitulation.py — Scanner de capitulação OI (day trade) — 47 perps Binance.

Cadência: a cada 5 min (via supercronic), ~2 min após o fechamento do candle.

Estratégia validada em 2 anos de dados (2024-11 → 2026-11, 47 moedas):
LONG no fechamento do candle de 5m quando:
  1. retorno_1h <= -2%          (queda forte)
  2. queda_OI_1h <= -2%         (flush de liquidações forçadas)
  3. long_short_ratio < quantil 25% dos últimos 7 dias  (varejo vendido)
Convicção ALTA quando o mercado (média do universo) cai >= 1% na 1h.

Backtest (líquido de 11 bps taker): +69,7 bps/op, PF 1,71, ~3 ops/dia,
70% dos dias com operação. Saída oficial: +2h. Alvo/stop = referência de risco.

Cache de barras em /data/oi_cache/ (JSON por moeda). Sinais em oi_signals (SQLite)
e /data/oi_signals.jsonl. Alerta via Telegram com entrada, alvo e stop.
"""

import os
import sys
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# Garante que lib/ seja importável (Railway: /app; local: raiz do repo)
sys.path.insert(0, "/app")
if not os.path.isdir("/app/lib"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import requests

from lib import db, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE = "https://fapi.binance.com"
CACHE_DIR = os.environ.get("OI_CACHE_DIR", "/data/oi_cache")
LOG_FILE = os.environ.get("OI_SIGNALS_LOG", "/data/oi_signals.jsonl")
Q25_WIN = 2016          # 7 dias de barras de 5 min
KEEP = Q25_WIN + 40

COINS = ["AAVEUSDT","ADAUSDT","ARBUSDT","AVAXUSDT","BCHUSDT","DOGEUSDT","DOTUSDT",
         "ENAUSDT","ETHUSDT","ETHFIUSDT","ETCUSDT","FETUSDT","FILUSDT","HBARUSDT",
         "ICPUSDT","INJUSDT","JUPUSDT","LINKUSDT","LTCUSDT","NEARUSDT","ONDOUSDT",
         "ONEUSDT","OPUSDT","QNTUSDT","SEIUSDT","SOLUSDT","STRKUSDT","SUIUSDT",
         "TIAUSDT","TRXUSDT","UNIUSDT","WLDUSDT","XLMUSDT","XMRUSDT","XRPUSDT",
         "ZECUSDT","ZROUSDT","BTCUSDT","BNBUSDT","1000PEPEUSDT","1000SHIBUSDT",
         "1000BONKUSDT","APTUSDT","CRVUSDT","DASHUSDT","LITUSDT"]


def _get(path, params):
    r = requests.get(f"{BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _paged(endpoint, params, limit_total, map_row):
    """Pagina para trás (endTime) até juntar limit_total linhas."""
    rows, end = [], None
    remaining = limit_total
    while remaining > 0:
        p = dict(params, limit=min(500, remaining))
        if end:
            p["endTime"] = end - 1
        try:
            data = _get(endpoint, p)
        except Exception:
            break
        if not data:
            break
        rows = [map_row(d) for d in data] + rows
        end = rows[0][0]
        remaining -= len(data)
        if len(data) < 2:
            break
    return rows


def fetch_coin(sym):
    """Cache incremental de ts/close/oi/ls por moeda."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    fpath = os.path.join(CACHE_DIR, f"{sym}.json")
    cache = {"ts": [], "close": [], "oi": [], "ls": []}
    if os.path.exists(fpath):
        try:
            with open(fpath) as fh:
                cache = json.load(fh)
        except Exception:
            pass

    if len(cache["ts"]) < Q25_WIN:
        kl = _paged("/fapi/v1/klines",
                    {"symbol": sym, "interval": "5m"}, KEEP,
                    lambda k: [int(k[0]), float(k[4])])
        oi = _paged("/futures/data/openInterestHist",
                    {"symbol": sym, "period": "5m"}, KEEP,
                    lambda d: [int(float(d["timestamp"])), float(d["sumOpenInterest"])])
        ls = _paged("/futures/data/globalLongShortAccountRatio",
                    {"symbol": sym, "period": "5m"}, KEEP,
                    lambda d: [int(float(d["timestamp"])), float(d["longShortRatio"])])
        oi_m = {r[0]: r[1] for r in oi}
        ls_m = {r[0]: r[1] for r in ls}
        ts = [r[0] for r in kl]
        cache = {"ts": ts,
                 "close": [r[1] for r in kl],
                 "oi": [oi_m.get(t) for t in ts],
                 "ls": [ls_m.get(t) for t in ts]}
    else:
        try:
            kl = _get("/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 3})
            oi = _get("/futures/data/openInterestHist", {"symbol": sym, "period": "5m", "limit": 3})
            ls = _get("/futures/data/globalLongShortAccountRatio", {"symbol": sym, "period": "5m", "limit": 3})
        except Exception:
            return None
        oi_m = {int(float(d["timestamp"])): float(d["sumOpenInterest"]) for d in oi}
        ls_m = {int(float(d["timestamp"])): float(d["longShortRatio"]) for d in ls}
        seen = set(cache["ts"])
        for k in kl:
            t = int(k[0])
            if t in seen:
                continue
            cache["ts"].append(t)
            cache["close"].append(float(k[4]))
            cache["oi"].append(oi_m.get(t))
            cache["ls"].append(ls_m.get(t))
        for key in ("ts", "close", "oi", "ls"):
            cache[key] = cache[key][-KEEP:]

    with open(fpath, "w") as fh:
        json.dump(cache, fh)
    return cache


def ensure_table():
    with db.get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS oi_signals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT NOT NULL,
            coin       TEXT NOT NULL,
            side       TEXT NOT NULL,
            entry      REAL NOT NULL,
            alvo       REAL,
            stop       REAL,
            ret_1h_pct REAL,
            oi_1h_pct  REAL,
            conviccao  TEXT,
            mkt_1h_pct REAL,
            exit_2h    REAL,
            pnl_bps    REAL,
            avaliado_em TEXT
        );
        """)


def already_sent(conn, coin, candle_ts):
    return conn.execute(
        "SELECT 1 FROM oi_signals WHERE coin=? AND ts=? LIMIT 1",
        (coin, candle_ts)).fetchone() is not None


def main():
    t0 = time.time()
    ensure_table()

    snaps = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for sym, cache in zip(COINS, ex.map(fetch_coin, COINS)):
            if cache and len(cache["ts"]) >= Q25_WIN:
                snaps[sym] = cache

    if len(snaps) < 30:
        logger.warning("apenas %d moedas com dados — rodada abortada", len(snaps))
        return

    rets = [c["close"][-2] / c["close"][-14] - 1 for c in snaps.values() if len(c["close"]) > 14]
    mkt = float(np.mean(rets)) if rets else 0.0

    sinais = []
    with db.get_conn() as conn:
        for sym, c in snaps.items():
            close, oi, ls = c["close"], c["oi"], c["ls"]
            if oi[-2] is None or oi[-14] is None or ls[-2] is None:
                continue
            ret1h = close[-2] / close[-14] - 1
            oi1h = oi[-2] / oi[-14] - 1
            ls_hist = [x for x in ls[-(Q25_WIN + 1):-1] if x is not None]
            if len(ls_hist) < Q25_WIN * 0.9:
                continue
            ls_q25 = float(np.percentile(ls_hist, 25))
            if ret1h <= -0.02 and oi1h <= -0.02 and ls[-2] < ls_q25:
                candle_utc = datetime.fromtimestamp(c["ts"][-2] / 1000, tz=timezone.utc)
                ts_str = candle_utc.strftime("%Y-%m-%d %H:%M")
                if already_sent(conn, sym, ts_str):
                    continue
                entry = close[-2]
                conv = "ALTA" if mkt <= -0.01 else "padrao"
                conn.execute(
                    "INSERT INTO oi_signals (ts, coin, side, entry, alvo, stop, "
                    "ret_1h_pct, oi_1h_pct, conviccao, mkt_1h_pct) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts_str, sym, "LONG", entry, entry * 1.02, entry * 0.975,
                     round(ret1h * 100, 2), round(oi1h * 100, 2), conv, round(mkt * 100, 2)))
                sinais.append({"moeda": sym, "ts": ts_str, "entrada": entry,
                               "ret": ret1h * 100, "oi": oi1h * 100, "conv": conv})

    for s in sinais:
        rec = {"ts": s["ts"], "coin": s["moeda"], "side": "LONG", "entry": s["entrada"],
               "alvo": round(s["entrada"] * 1.02, 8), "stop": round(s["entrada"] * 0.975, 8),
               "ret_1h_pct": round(s["ret"], 2), "oi_1h_pct": round(s["oi"], 2),
               "conviccao": s["conv"], "mkt_1h_pct": round(mkt * 100, 2)}
        with open(LOG_FILE, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    if sinais:
        linhas = []
        for s in sinais:
            estrela = "\U0001F525 " if s["conv"] == "ALTA" else ""
            linhas.append(
                f"{estrela}<b>{s['moeda']}</b> LONG\n"
                f"├ Entrada: <code>{s['entrada']:.8g}</code>\n"
                f"├ Alvo ref (+2%): <code>{s['entrada']*1.02:.8g}</code>\n"
                f"├ Stop prot (-2.5%): <code>{s['entrada']*0.975:.8g}</code>\n"
                f"├ Queda 1h: {s['ret']:.2f}% | OI 1h: {s['oi']:.2f}%\n"
                f"└ Saída oficial: +2h (sinal {s['ts']} UTC)")
        msg = ("⚡️ <b>SINAL DE CAPITULAÇÃO OI</b> — %d moeda(s)\n"
               "Mercado 1h: %+.2f%%\n\n" % (len(sinais), mkt * 100)) + "\n\n".join(linhas)
        telegram.send(msg)
        logger.info("%d sinal(is) enviados ao Telegram", len(sinais))

    logger.info("%d moedas | mkt_1h %+.2f%% | %d sinal(is) | %.1fs",
                len(snaps), mkt * 100, len(sinais), time.time() - t0)


if __name__ == "__main__":
    main()
