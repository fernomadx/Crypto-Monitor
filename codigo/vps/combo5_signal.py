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
    """Análise periódica (default 60 min). 0 = só via COMBO5_FORCE_STATUS (cron horário)."""
    every_min = int(os.environ.get("COMBO5_HEARTBEAT_MINUTES", "60"))
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


def _format_status(
    status: dict,
    *,
    title: str | None = None,
    footer: str | None = None,
) -> str:
    sig = status.get("signal") or {}
    open_t = status.get("open")
    blocks = sig.get("blocks") or []
    reasons = sig.get("reasons") or []
    thr = float(sig.get("threshold_pct") or 0.35)
    strength = float(sig.get("strength_pct") or 0)
    signed = float(sig.get("strength_signed_pct") or 0)
    atr = float(sig.get("atr_pct") or 0)
    ema = sig.get("ema_4h_aligned")
    ema_txt = "sim" if ema is True else ("não" if ema is False else "n/d (4h neutro)")

    icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(str(sig.get("side")), "⚪")
    head = title or f"📊 Análise horária COMBO5 — {status.get('updated_at')}"
    lines = [
        head,
        f"{icon} {status.get('symbol')} @ {float(status.get('price') or 0):.2f}",
        "",
        "Kronos 3TF (proxy momentum):",
        f"  1h={sig.get('bias_1h')} | 4h={sig.get('bias_4h')} | 1d={sig.get('bias_1d')}",
        f"  Força 4h: {signed:+.2f}% (|{strength:.2f}%|) | thr ±{thr}%",
        f"  EMA 4h alinhada: {ema_txt}",
        "",
        "Desk (técnico+momentum+estrutura):",
        f"  Lado {sig.get('desk_side')} | conf {float(sig.get('confidence') or 0):.2f}",
        f"  {sig.get('desk_detail') or '—'}",
        "",
        f"Volatilidade ATR%: {atr:.2f} (janela ok 0.5–1.1)",
        f"Decisão: {sig.get('side')} | setup_ok={sig.get('ok')}",
    ]
    if reasons:
        lines.append("Pontos a favor: " + "; ".join(str(r) for r in reasons[:4]))
    if blocks:
        lines.append("Bloqueios (por isso não entrou): " + "; ".join(str(b) for b in blocks[:4]))
    else:
        lines.append("Sem bloqueios — setup válido para entrada.")

    actions = status.get("actions") or []
    if actions:
        lines.extend(["", "Ações neste ciclo: " + ", ".join(str(a) for a in actions)])

    if open_t:
        lines.extend(
            [
                "",
                f"Trade aberto Nº {open_t.get('number')} {open_t.get('side')}",
                f"  Entrada {open_t.get('entry_price')} | SL {open_t.get('stop_loss')} | TP {open_t.get('take_profit')}",
            ]
        )
    else:
        lines.extend(["", "Sem trade aberto agora.", f"Próxima entrada seria Nº {status.get('next_entry_number')}"])

    if sig.get("ok") and sig.get("side") in {"BUY", "SELL"}:
        lines.append(
            f"Níveis se entrar: SL {float(sig.get('stop_price') or 0):.2f} | "
            f"TP {float(sig.get('take_profit_price') or 0):.2f}"
        )

    lines.append("")
    lines.append(
        footer
        or "Gestão SL/TP roda a cada 5 min; análise automática 1x/hora (ou /combo5 sob demanda)."
    )
    return "\n".join(lines)


def _runtime() -> tuple[Path, TradeJournal, list[str]]:
    """State dir + journal + tickers configurados.

    Sempre prefere COMBO5_STATE_DIR (/data/combo5 no Railway). Nunca cair
    silenciosamente em path efêmero do container — isso fazia o bot 'sumir'
    após redeploy (heartbeat/journal perdidos).
    """
    _load_env()
    preferred = Path(os.environ.get("COMBO5_STATE_DIR", "/data/combo5"))
    fallback = REPO_ROOT / "vps" / "combo5_state"
    state_dir = preferred
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        # migra estado antigo se ficou no path efêmero
        if preferred.resolve() != fallback.resolve() and fallback.exists():
            for name in ("journal.json", "last_heartbeat.txt", "last_ok.txt"):
                src, dst = fallback / name, preferred / name
                if src.is_file() and not dst.exists():
                    try:
                        dst.write_bytes(src.read_bytes())
                    except OSError:
                        pass
            for stale in fallback.glob("status_*.json"):
                dst = preferred / stale.name
                if not dst.exists():
                    try:
                        dst.write_bytes(stale.read_bytes())
                    except OSError:
                        pass
    except OSError:
        logger.warning("COMBO5: não escreveu em %s — usando %s", preferred, fallback)
        state_dir = fallback
        state_dir.mkdir(parents=True, exist_ok=True)
    journal = TradeJournal(state_dir / "journal.json")
    return state_dir, journal, resolve_symbols()


def _normalize_symbol(raw: str) -> str:
    t = raw.strip().upper()
    if not t:
        raise ValueError("símbolo vazio")
    return t if t.endswith("USDT") else f"{t}USDT"


def analyze_now(symbol: str | None = None) -> str:
    """
    Análise COMBO5 em tempo real (comando Telegram /combo5 · /analise).

    Roda o mesmo ciclo do cron (SL/TP/entrada se setup ok) e devolve o texto
    da análise — independente do horário programado.
    """
    if os.environ.get("COMBO5_ENABLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return "COMBO5 desligado (COMBO5_ENABLED=0)."

    state_dir, journal, symbols = _runtime()
    if symbol:
        targets = [_normalize_symbol(symbol)]
    else:
        multi = os.environ.get("COMBO5_MULTI", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        targets = symbols if multi else symbols[:1]
        if not targets:
            return "Nenhum ticker em COMBO5_TICKERS / KRONOS_TICKERS."

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts: list[str] = []
    for sym in targets:
        status = process_symbol(sym, journal, state_dir)
        parts.append(
            _format_status(
                status,
                title=f"📊 Análise sob demanda COMBO5 — {now}",
                footer=(
                    "Pedido via /combo5 ou /analise · "
                    "gestão automática continua a cada 5 min."
                ),
            )
        )
    _mark_heartbeat(state_dir)
    _mark_ok(state_dir)
    return "\n\n————————\n\n".join(parts)


def _mark_ok(state_dir: Path) -> None:
    (state_dir / "last_ok.txt").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )


def _error_rate_limited(state_dir: Path, key: str, *, cooldown_sec: int = 1800) -> bool:
    """True se devemos SUPRIMIR o alerta (já avisamos há pouco)."""
    marker = state_dir / "last_error_alert.txt"
    now = datetime.now(timezone.utc)
    payload = f"{now.isoformat()}|{key}"
    if marker.exists():
        try:
            raw = marker.read_text(encoding="utf-8").strip()
            ts_s, _, prev_key = raw.partition("|")
            last = datetime.fromisoformat(ts_s)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if prev_key == key and (now - last).total_seconds() < cooldown_sec:
                return True
        except Exception:
            pass
    try:
        marker.write_text(payload, encoding="utf-8")
    except OSError:
        pass
    return False


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

    state_dir, journal, symbols = _runtime()

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
            _mark_ok(state_dir)
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
            key = f"{symbol}:{type(exc).__name__}:{str(exc)[:80]}"
            if not _error_rate_limited(state_dir, key):
                try:
                    send_combo5_alert(f"erro {symbol}", str(exc)[:400])
                except Exception:
                    pass
            # Não derruba o cron inteiro com traceback infinito — próximo ciclo tenta de novo
            continue


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
