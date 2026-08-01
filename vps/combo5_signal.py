#!/usr/bin/env python3
"""
vps/combo5_signal.py — Bot COMBO5 com entrada/stop/saída e avisos numerados.

Cron sugerido (a cada 5 min):
    */5 * * * * python /app/vps/combo5_signal.py >> /data/combo5.log 2>&1

Avisos Telegram:
  - ENTRADA Nº N · data/hora · stop · alvo · motivos
  - FECHAMENTO Nº N · GAIN/LOSS · explicação
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.combo5.journal import TradeJournal  # noqa: E402
from lib.combo5.signal import Combo5Signal, evaluate_combo5  # noqa: E402
from lib.mexc_klines import fetch_klines  # noqa: E402
from lib.telegram import send_combo5_alert  # noqa: E402
from lib.trade_desk.models import Side  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_env() -> None:
    for env_path in (REPO_ROOT / "vps" / ".env", REPO_ROOT / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, val = line.partition("=")
            os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def resolve_symbols() -> list[str]:
    raw = os.environ.get("COMBO5_TICKERS") or os.environ.get("KRONOS_TICKERS") or os.environ.get(
        "TICKERS", "BTC"
    )
    out: list[str] = []
    for part in raw.split(","):
        t = part.strip().upper()
        if not t:
            continue
        out.append(t if t.endswith("USDT") else f"{t}USDT")
    return out


def _hit_stop_or_take(trade, high: float, low: float, last: float) -> tuple[bool, float, str]:
    if trade.side == "LONG":
        if low <= trade.stop_loss:
            return True, float(trade.stop_loss), "stop_loss"
        if high >= trade.take_profit:
            return True, float(trade.take_profit), "take_profit"
    else:
        if high >= trade.stop_loss:
            return True, float(trade.stop_loss), "stop_loss"
        if low <= trade.take_profit:
            return True, float(trade.take_profit), "take_profit"
    return False, float(last), ""


def _signal_exit(trade, signal: Combo5Signal) -> tuple[bool, list[str]]:
    notes: list[str] = []
    exit_on_opp = os.environ.get("COMBO5_EXIT_ON_OPPOSITE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    exit_on_weak = os.environ.get("COMBO5_EXIT_ON_WEAK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if signal.ok and signal.side != Side.HOLD:
        want_long = trade.side == "LONG"
        sig_long = signal.side == Side.BUY
        if want_long != sig_long and exit_on_opp:
            notes.append(
                f"COMBO5 inverteu para {signal.side.value} "
                f"(Kronos {signal.kronos_bias}, força {signal.strength_pct:.2f}%)"
            )
            return True, notes
    if exit_on_weak:
        if not signal.ok and signal.kronos_bias == "NEUTRO":
            notes.append("Kronos 3TF perdeu alinhamento (NEUTRO)")
            return True, notes
        if signal.blocks and any("3TF desalinhado" in b for b in signal.blocks):
            notes.append("; ".join(signal.blocks[:2]))
            return True, notes
        if signal.strength_pct < 0.35 and not signal.ok:
            notes.append(f"força caiu para {signal.strength_pct:.2f}%")
            return True, notes
    return False, notes


def _emit(msg: str) -> None:
    print(msg, flush=True)
    # Telegram sem HTML pesado — texto puro
    plain = msg.replace("<", "&lt;").replace(">", "&gt;")
    send_combo5_alert("COMBO5", f"<pre>{plain}</pre>")


def _should_send_heartbeat(state_dir: Path) -> bool:
    """Manda status periódico (default 30 min) para provar que o bot está vivo."""
    every_min = int(os.environ.get("COMBO5_HEARTBEAT_MINUTES", "30"))
    if every_min <= 0:
        return False
    marker = state_dir / "last_heartbeat.txt"
    now = datetime.now(timezone.utc)
    if not marker.exists():
        return True
    try:
        last = datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() >= every_min * 60
    except Exception:
        return True


def _mark_heartbeat(state_dir: Path) -> None:
    (state_dir / "last_heartbeat.txt").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )


def _format_status(status: dict) -> str:
    sig = status.get("signal") or {}
    open_t = status.get("open")
    blocks = sig.get("blocks") or []
    lines = [
        f"⏱ Status COMBO5 — {status.get('updated_at')}",
        f"Par: {status.get('symbol')} @ {status.get('price')}",
        f"Sinal: {sig.get('side')} | ok={sig.get('ok')} | Kronos {sig.get('kronos_bias')} "
        f"| força {float(sig.get('strength_pct') or 0):.2f}%",
        f"Ações: {status.get('actions') or ['hold']}",
    ]
    if open_t:
        lines.append(
            f"Aberto: Nº {open_t.get('number')} {open_t.get('side')} "
            f"entrada {open_t.get('entry_price')} SL {open_t.get('stop_loss')} TP {open_t.get('take_profit')}"
        )
    else:
        lines.append("Sem trade aberto.")
    if blocks:
        lines.append("Bloqueios: " + "; ".join(str(b) for b in blocks[:3]))
    lines.append("Entrada/saída só avisam quando houver trade (GAIN/LOSS).")
    return "\n".join(lines)


def process_symbol(symbol: str, journal: TradeJournal, state_dir: Path) -> dict:
    df_1h = fetch_klines(symbol, "1h", limit=120)
    df_4h = fetch_klines(symbol, "4h", limit=120)
    df_1d = fetch_klines(symbol, "1d", limit=90)
    signal = evaluate_combo5(symbol=symbol, df_1h=df_1h, df_4h=df_4h, df_1d=df_1d)

    last = float(df_1h["close"].iloc[-1])
    high = float(df_1h["high"].iloc[-1])
    low = float(df_1h["low"].iloc[-1])
    actions: list[str] = []

    open_t = journal.get_open(symbol)
    if open_t is not None:
        should, exit_px, reason = _hit_stop_or_take(open_t, high, low, last)
        notes: list[str] = []
        if not should:
            do_exit, notes = _signal_exit(open_t, signal)
            if do_exit:
                should, exit_px, reason = True, last, "signal_exit"
        if should:
            closed, alert = journal.close_trade(
                symbol=symbol, exit_price=exit_px, exit_reason=reason, market_notes=notes
            )
            _emit(alert)
            actions.append(f"closed #{closed.number} {closed.result}")
            open_t = None

    if open_t is None and signal.ok and signal.side in {Side.BUY, Side.SELL}:
        notional = float(os.environ.get("COMBO5_NOTIONAL_USDT", "1000"))
        qty = notional / max(signal.price, 1e-12)
        side = "LONG" if signal.side == Side.BUY else "SHORT"
        reasons = list(signal.reasons) + [
            f"Stop {signal.stop_price:.4f} | Alvo {signal.take_profit_price:.4f}",
            f"RR 1:{os.environ.get('COMBO5_RR', '2.0')}",
        ]
        opened, alert = journal.open_trade(
            symbol=symbol,
            side=side,
            price=float(signal.price),
            stop=float(signal.stop_price),
            take_profit=float(signal.take_profit_price),
            qty=float(qty),
            entry_reasons=reasons,
            kronos_bias=signal.kronos_bias,
            strength_pct=float(signal.strength_pct),
            confidence=float(signal.confidence),
        )
        _emit(alert)
        actions.append(f"opened #{opened.number} {opened.side}")

    status = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": symbol,
        "price": last,
        "signal": signal.to_dict(),
        "actions": actions,
        "open": journal.get_open(symbol).to_dict() if journal.get_open(symbol) else None,
        "next_entry_number": journal.state.next_number,
    }
    (state_dir / f"status_{symbol}.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return status


def main() -> None:
    _load_env()
    if os.environ.get("COMBO5_ENABLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("COMBO5_ENABLED=0 — saindo")
        return

    state_dir = Path(os.environ.get("COMBO5_STATE_DIR", "/data/combo5"))
    if not state_dir.exists():
        # fallback local / sem volume Railway
        state_dir = REPO_ROOT / "vps" / "combo5_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    journal = TradeJournal(state_dir / "journal.json")

    symbols = resolve_symbols()
    # 1 trade aberto por vez no journal global — processa o primeiro símbolo configurado
    # (ou todos se COMBO5_MULTI=1)
    multi = os.environ.get("COMBO5_MULTI", "0").strip().lower() in {"1", "true", "yes", "on"}
    targets = symbols if multi else symbols[:1]

    force_status = os.environ.get("COMBO5_FORCE_STATUS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    send_hb = force_status or _should_send_heartbeat(state_dir)

    for symbol in targets:
        try:
            status = process_symbol(symbol, journal, state_dir)
            logger.info(
                "%s price=%.2f signal=%s ok=%s actions=%s",
                symbol,
                status["price"],
                status["signal"]["side"],
                status["signal"]["ok"],
                status["actions"] or ["hold"],
            )
            if status["signal"]["blocks"]:
                logger.info("blocks: %s", status["signal"]["blocks"][:3])
            # Sempre avisa em trade; se não houve ação, manda heartbeat periódico
            if send_hb and not status["actions"]:
                _emit(_format_status(status))
                _mark_heartbeat(state_dir)
                send_hb = False
            elif status["actions"]:
                _mark_heartbeat(state_dir)
        except Exception as exc:
            logger.exception("COMBO5 falhou em %s: %s", symbol, exc)
            try:
                send_combo5_alert(f"erro {symbol}", str(exc)[:400])
            except Exception:
                pass
            raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
