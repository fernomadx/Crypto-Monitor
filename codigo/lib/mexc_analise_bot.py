"""Motor do bot 📊 MEXC Análise (alerts, BTC 1h, 20x) — sem CCXT.

Regras (banner de boot):
  Modo: alerts | BTC/USDT:USDT 1h
  Entry: limit | Lev: 20x | Poll: 15s
  Cooldown pós-STOP: 12h (sem inverter)
  Long: bloqueia RSI>65 ou ADX≥40
  BE: stop na entrada após 1.5R (não em 1R)
  Stop máx: 5% (corta short atrasado)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from lib.trade_desk.indicators import enrich

SYMBOL_CCXT = "BTC/USDT:USDT"
INTERVAL = "1h"
LEVERAGE = 20
POLL_SEC = 15
COOLDOWN_HOURS = 12
RSI_LONG_MAX = 65.0
ADX_LONG_MAX = 40.0
STOP_MAX_PCT = 5.0
BE_AT_R = 1.5
RR = 2.0
LIMIT_OFFSET_PCT = 0.10  # pullback para ordem limite
ATR_STOP_MULT = 1.5


def boot_banner(*, mode: str = "alerts") -> str:
    return (
        "📊 MEXC Análise\n"
        "Bot iniciado\n"
        f"Modo: {mode} | {SYMBOL_CCXT} {INTERVAL}\n"
        f"Entry: limit | Lev: {LEVERAGE}x | Poll: {POLL_SEC}s\n"
        f"Cooldown pós-STOP: {COOLDOWN_HOURS}h (sem inverter)\n"
        f"Long: bloqueia RSI>{RSI_LONG_MAX:.0f} ou ADX≥{ADX_LONG_MAX:.0f}\n"
        "BE: stop na entrada após 1.5R (não em 1R — preserva o long de jul/26)\n"
        "Stop máx: 5% (corta short atrasado tipo 2022)"
    )


def notify_enabled(raw: str | None) -> bool:
    """Telegram 'Bot iniciado': default ON na execução direta; watchdog exporta 0."""
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def acquire_singleton_lock(lock_path: Path) -> TextIO | None:
    """Lock exclusivo do daemon. None se outra instância já segura o arquivo."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


@dataclass
class Position:
    side: str  # LONG | SHORT
    entry: float
    stop: float
    take: float
    limit: float
    filled: bool
    r: float
    opened_at: str
    be_done: bool = False
    candle: str = ""


@dataclass
class BotState:
    position: Position | None = None
    cooldown_until: str | None = None
    last_stop_side: str | None = None
    last_candle: str | None = None
    last_ok: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "cooldown_until": self.cooldown_until,
            "last_stop_side": self.last_stop_side,
            "last_candle": self.last_candle,
            "last_ok": self.last_ok,
        }
        if self.position:
            p = self.position
            d["position"] = {
                "side": p.side,
                "entry": p.entry,
                "stop": p.stop,
                "take": p.take,
                "limit": p.limit,
                "filled": p.filled,
                "r": p.r,
                "opened_at": p.opened_at,
                "be_done": p.be_done,
                "candle": p.candle,
            }
        else:
            d["position"] = None
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BotState:
        raw = raw or {}
        pos = raw.get("position")
        position = None
        if isinstance(pos, dict) and pos.get("side"):
            position = Position(
                side=str(pos["side"]),
                entry=float(pos["entry"]),
                stop=float(pos["stop"]),
                take=float(pos["take"]),
                limit=float(pos.get("limit") or pos["entry"]),
                filled=bool(pos.get("filled", True)),
                r=float(pos.get("r") or 0.0),
                opened_at=str(pos.get("opened_at") or ""),
                be_done=bool(pos.get("be_done", False)),
                candle=str(pos.get("candle") or ""),
            )
        return cls(
            position=position,
            cooldown_until=raw.get("cooldown_until"),
            last_stop_side=raw.get("last_stop_side"),
            last_candle=raw.get("last_candle"),
            last_ok=raw.get("last_ok"),
        )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


def _in_cooldown(state: BotState, now: datetime) -> bool:
    until = _parse_ts(state.cooldown_until)
    return until is not None and now < until


def _stop_take(side: str, entry: float, atr_val: float) -> tuple[float, float, float, str | None]:
    raw_stop = atr_val * ATR_STOP_MULT
    stop_pct = raw_stop / max(entry, 1e-12) * 100.0
    if side == "SHORT" and stop_pct > STOP_MAX_PCT:
        return 0.0, 0.0, 0.0, f"short bloqueado: stop {stop_pct:.2f}% > {STOP_MAX_PCT:.0f}%"
    stop_dist = min(raw_stop, entry * STOP_MAX_PCT / 100.0)
    r = stop_dist
    if side == "LONG":
        stop = entry - stop_dist
        take = entry + r * RR
    else:
        stop = entry + stop_dist
        take = entry - r * RR
    return stop, take, r, None


def evaluate_signal(df) -> dict[str, Any]:
    data = enrich(df).dropna()
    if len(data) < 30:
        return {"side": None, "rsi": None, "adx": None, "reason": "candles insuficientes"}
    row = data.iloc[-1]
    rsi_v = float(row["rsi"])
    adx_v = float(row["adx"]) if "adx" in row and row["adx"] == row["adx"] else 0.0
    ema_up = float(row["ema_fast"]) > float(row["ema_slow"])
    macd_up = float(row["hist"]) > 0
    atr_v = float(row["atr"])
    close = float(row["close"])
    blocks: list[str] = []
    side = None
    if ema_up and macd_up:
        if rsi_v > RSI_LONG_MAX:
            blocks.append(f"long bloqueado RSI {rsi_v:.0f}>{RSI_LONG_MAX:.0f}")
        elif adx_v >= ADX_LONG_MAX:
            blocks.append(f"long bloqueado ADX {adx_v:.0f}≥{ADX_LONG_MAX:.0f}")
        else:
            side = "LONG"
    elif (not ema_up) and (not macd_up):
        side = "SHORT"
        _, _, _, err = _stop_take("SHORT", close, atr_v)
        if err:
            blocks.append(err)
            side = None
    return {
        "side": side,
        "rsi": rsi_v,
        "adx": adx_v,
        "atr": atr_v,
        "close": close,
        "blocks": blocks,
        "ema_up": ema_up,
        "macd_up": macd_up,
    }


def _fmt(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    return f"{v:,.4f}"


def side_action(side: str) -> str:
    """LONG = compra, SHORT = venda."""
    key = (side or "").upper()
    if key == "LONG":
        return "COMPRA"
    if key == "SHORT":
        return "VENDA"
    return side


def format_signal_alert(
    *,
    side: str,
    limit: float,
    stop: float,
    take: float,
    rsi: float | None,
    adx: float | None,
) -> str:
    action = side_action(side)
    rsi_s = f"RSI {rsi:.0f}" if rsi is not None else ""
    adx_s = f"ADX {adx:.0f}" if adx is not None else ""
    return (
        "📊 MEXC Análise\n"
        f"SINAL {action} ({side})\n"
        "limit, sem fill ainda — não é ordem na exchange\n"
        f"{SYMBOL_CCXT} {INTERVAL}\n"
        f"Entry {_fmt(limit)} · SL {_fmt(stop)} · TP {_fmt(take)}\n"
        f"Lev {LEVERAGE}x · {rsi_s} {adx_s}".rstrip()
    )


def tick(
    *,
    state: BotState,
    df,
    last_price: float,
    now: datetime,
    high: float | None = None,
    low: float | None = None,
) -> tuple[BotState, list[str]]:
    """Um ciclo de 15s. df = klines 1h futures (último = candle em formação ou fechado)."""
    msgs: list[str] = []
    now = now.astimezone(timezone.utc)
    high = last_price if high is None else high
    low = last_price if low is None else low
    state = replace(state, last_ok=_iso(now), notes=[])

    closed = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    candle_id = str(int(closed["open_time"])) if "open_time" in closed else str(closed.get("timestamps", ""))

    pos = state.position
    if pos is not None:
        if not pos.filled:
            filled = (low <= pos.limit) if pos.side == "LONG" else (high >= pos.limit)
            if filled:
                pos = replace(pos, filled=True, entry=pos.limit)
                state = replace(state, position=pos)
                msgs.append(
                    "📊 MEXC Análise\n"
                    f"FILL {side_action(pos.side)} ({pos.side})\n"
                    f"{SYMBOL_CCXT} {INTERVAL}\n"
                    f"Entry limit {_fmt(pos.entry)} · SL {_fmt(pos.stop)} · TP {_fmt(pos.take)}\n"
                    f"Lev {LEVERAGE}x"
                )
            return state, msgs

        hit_stop = (low <= pos.stop) if pos.side == "LONG" else (high >= pos.stop)
        hit_take = (high >= pos.take) if pos.side == "LONG" else (low <= pos.take)
        move = (last_price - pos.entry) if pos.side == "LONG" else (pos.entry - last_price)
        r_mult = move / pos.r if pos.r else 0.0

        if not pos.be_done and r_mult >= BE_AT_R:
            pos = replace(pos, stop=pos.entry, be_done=True)
            state = replace(state, position=pos)
            msgs.append(
                "📊 MEXC Análise\n"
                "BE · stop na entrada após 1.5R (não em 1R)\n"
                f"{pos.side} preservado · entry {_fmt(pos.entry)}"
            )

        if hit_stop:
            cooldown_until = now + timedelta(hours=COOLDOWN_HOURS)
            state = replace(
                state,
                position=None,
                cooldown_until=_iso(cooldown_until),
                last_stop_side=pos.side,
            )
            msgs.append(
                "📊 MEXC Análise\n"
                f"STOP {side_action(pos.side)} ({pos.side})\n"
                f"Preço {_fmt(pos.stop)} · cooldown {COOLDOWN_HOURS}h (sem inverter)"
            )
            return state, msgs
        if hit_take:
            state = replace(state, position=None, cooldown_until=None)
            msgs.append(
                "📊 MEXC Análise\n"
                f"TAKE {side_action(pos.side)} ({pos.side})\n"
                f"Alvo {_fmt(pos.take)} · flat"
            )
            return state, msgs
        return state, msgs

    if _in_cooldown(state, now):
        return state, msgs
    if state.cooldown_until:
        state = replace(state, cooldown_until=None, last_stop_side=None)

    if state.last_candle == candle_id:
        return state, msgs

    sig = evaluate_signal(df.iloc[:-1] if len(df) >= 2 else df)
    state = replace(state, last_candle=candle_id)
    side = sig.get("side")
    if not side:
        return state, msgs

    entry_ref = float(sig["close"])
    if side == "LONG":
        limit = entry_ref * (1 - LIMIT_OFFSET_PCT / 100.0)
    else:
        limit = entry_ref * (1 + LIMIT_OFFSET_PCT / 100.0)
    stop, take, r, err = _stop_take(side, limit, float(sig["atr"]))
    if err or r <= 0:
        return state, msgs

    pos = Position(
        side=side,
        entry=limit,
        stop=stop,
        take=take,
        limit=limit,
        filled=False,
        r=r,
        opened_at=_iso(now),
        candle=candle_id,
    )
    state = replace(state, position=pos, last_stop_side=None)
    msgs.append(
        format_signal_alert(
            side=side,
            limit=limit,
            stop=stop,
            take=take,
            rsi=sig.get("rsi"),
            adx=sig.get("adx"),
        )
    )
    return state, msgs
