"""Diário de trades numerados — entrada/saída com explicação gain/loss."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class NumberedTrade:
    number: int
    symbol: str
    side: str  # LONG / SHORT
    status: str  # OPEN / CLOSED
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float
    opened_at: str
    opened_at_local_note: str
    entry_reasons: list[str] = field(default_factory=list)
    kronos_bias: str = ""
    strength_pct: float = 0.0
    confidence: float = 0.0
    exit_price: float | None = None
    closed_at: str | None = None
    result: str | None = None  # GAIN / LOSS / BREAKEVEN
    exit_reason: str | None = None
    pnl_pct: float | None = None
    pnl_abs: float | None = None
    outcome_explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JournalState:
    next_number: int = 1
    open_trades: dict[str, NumberedTrade] = field(default_factory=dict)
    closed_trades: list[NumberedTrade] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_number": self.next_number,
            "open_trades": {k: v.to_dict() for k, v in self.open_trades.items()},
            "closed_trades": [t.to_dict() for t in self.closed_trades],
            "alerts": self.alerts[-200:],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalState:
        open_trades = {k: NumberedTrade(**v) for k, v in (data.get("open_trades") or {}).items()}
        closed = [NumberedTrade(**t) for t in (data.get("closed_trades") or [])]
        return cls(
            next_number=int(data.get("next_number", 1)),
            open_trades=open_trades,
            closed_trades=closed,
            alerts=list(data.get("alerts") or []),
        )


class TradeJournal:
    def __init__(self, path: str | Path = ".combo5_journal.json"):
        self.path = Path(path)
        if self.path.exists():
            self.state = JournalState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            self.state = JournalState()
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _alert(self, msg: str) -> str:
        self.state.alerts.append(msg)
        self._save()
        return msg

    def get_open(self, symbol: str) -> NumberedTrade | None:
        return self.state.open_trades.get(symbol)

    def open_trade(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        stop: float,
        take_profit: float,
        qty: float,
        entry_reasons: list[str],
        kronos_bias: str,
        strength_pct: float,
        confidence: float,
    ) -> tuple[NumberedTrade, str]:
        if symbol in self.state.open_trades:
            raise RuntimeError(f"Já existe trade aberto em {symbol}")
        n = self.state.next_number
        self.state.next_number += 1
        now = datetime.now(timezone.utc)
        trade = NumberedTrade(
            number=n,
            symbol=symbol,
            side=side,
            status="OPEN",
            entry_price=price,
            stop_loss=stop,
            take_profit=take_profit,
            qty=qty,
            opened_at=now.isoformat(),
            opened_at_local_note=now.strftime("%d/%m/%Y %H:%M UTC"),
            entry_reasons=entry_reasons,
            kronos_bias=kronos_bias,
            strength_pct=strength_pct,
            confidence=confidence,
        )
        self.state.open_trades[symbol] = trade
        msg = format_entry_alert(trade)
        self._alert(msg)
        return trade, msg

    def close_trade(
        self,
        *,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        market_notes: list[str] | None = None,
    ) -> tuple[NumberedTrade, str]:
        trade = self.state.open_trades.get(symbol)
        if not trade:
            raise RuntimeError(f"Sem trade aberto em {symbol}")
        now = datetime.now(timezone.utc)
        if trade.side == "LONG":
            pnl_pct = (exit_price / trade.entry_price - 1) * 100
        else:
            pnl_pct = (trade.entry_price / exit_price - 1) * 100
        pnl_abs = trade.qty * trade.entry_price * (pnl_pct / 100.0)
        if pnl_pct > 0.05:
            result = "GAIN"
        elif pnl_pct < -0.05:
            result = "LOSS"
        else:
            result = "BREAKEVEN"

        trade.status = "CLOSED"
        trade.exit_price = exit_price
        trade.closed_at = now.isoformat()
        trade.result = result
        trade.exit_reason = exit_reason
        trade.pnl_pct = round(pnl_pct, 3)
        trade.pnl_abs = round(pnl_abs, 2)
        trade.outcome_explanation = explain_outcome(
            trade, exit_price, exit_reason, result, market_notes or []
        )

        del self.state.open_trades[symbol]
        self.state.closed_trades.append(trade)
        msg = format_exit_alert(trade, now.strftime("%d/%m/%Y %H:%M UTC"))
        self._alert(msg)
        return trade, msg


def format_entry_alert(t: NumberedTrade) -> str:
    side_pt = "COMPRA (LONG)" if t.side == "LONG" else "VENDA (SHORT)"
    reasons = "\n".join(f"  • {r}" for r in t.entry_reasons) or "  • —"
    return (
        f"📥 ENTRADA Nº {t.number}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Par: {t.symbol}\n"
        f"Lado: {side_pt}\n"
        f"Data/hora: {t.opened_at_local_note}\n"
        f"Preço entrada: {t.entry_price:.4f}\n"
        f"Stop: {t.stop_loss:.4f}\n"
        f"Alvo (TP): {t.take_profit:.4f}\n"
        f"Kronos: {t.kronos_bias} | força {t.strength_pct:.2f}% | conf desk {t.confidence:.2f}\n"
        f"Motivos da entrada:\n{reasons}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def format_exit_alert(t: NumberedTrade, closed_note: str) -> str:
    emoji = "✅" if t.result == "GAIN" else ("❌" if t.result == "LOSS" else "➖")
    return (
        f"{emoji} FECHAMENTO — ENTRADA Nº {t.number}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Par: {t.symbol} | {t.side}\n"
        f"Aberta em: {t.opened_at_local_note}\n"
        f"Fechada em: {closed_note}\n"
        f"Entrada: {t.entry_price:.4f} → Saída: {t.exit_price:.4f}\n"
        f"Resultado: {t.result} ({t.pnl_pct:+.2f}% | {t.pnl_abs:+.2f} USDT)\n"
        f"Tipo de saída: {t.exit_reason}\n"
        f"Explicação:\n{t.outcome_explanation}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def explain_outcome(
    trade: NumberedTrade,
    exit_price: float,
    exit_reason: str,
    result: str,
    market_notes: list[str],
) -> str:
    move = abs((exit_price / trade.entry_price - 1) * 100)
    direction = "a favor" if result == "GAIN" else ("contra" if result == "LOSS" else "lateral")
    parts: list[str] = []

    if exit_reason == "take_profit":
        parts.append(
            f"O preço atingiu o alvo ({trade.take_profit:.4f}). "
            f"O movimento {direction} foi de ~{move:.2f}% e validou o setup "
            f"Kronos {trade.kronos_bias} (força {trade.strength_pct:.2f}%)."
        )
        if result == "GAIN":
            parts.append(
                "Deu certo porque o alinhamento 3TF se sustentou até o TP — "
                "tendência e desk apontavam a mesma direção."
            )
    elif exit_reason == "stop_loss":
        parts.append(
            f"O preço atingiu o stop ({trade.stop_loss:.4f}). "
            f"Movimento {direction} de ~{move:.2f}% invalidou a tese da entrada Nº {trade.number}."
        )
        parts.append(
            "Deu errado porque o mercado andou contra o viés Kronos antes de atingir o alvo — "
            "possível fakeout, notícia/volatilidade ou perda do alinhamento de tendência."
        )
    elif exit_reason == "signal_exit":
        pnl_txt = f"{trade.pnl_pct:+.2f}%" if trade.pnl_pct is not None else f"~{move:.2f}%"
        parts.append(
            f"Saída por sinal contrário/revogação do setup COMBO5 (não foi SL nem TP). "
            f"PnL no fechamento: {pnl_txt} (movimento {direction})."
        )
        if result == "GAIN":
            parts.append(
                "Deu certo parcialmente: a tese ainda gerava lucro quando o alinhamento "
                "Kronos/desk enfraqueceu ou inverteu — lucro realizado antes de virar loss."
            )
        elif result == "LOSS":
            parts.append(
                "Não deu certo: o setup perdeu força ou inverteu com a posição já negativa — "
                "corte defensivo para não esperar o stop cheio."
            )
        else:
            parts.append("Saída perto do zero: mercado lateralizou e o sinal deixou de ser válido.")
    else:
        parts.append(f"Saída ({exit_reason}) com movimento {direction} de ~{move:.2f}%.")
        if result == "GAIN":
            parts.append("Deu certo porque o preço andou a favor da entrada antes do fechamento.")
        elif result == "LOSS":
            parts.append("Não deu certo porque o preço andou contra a tese da entrada.")

    if market_notes:
        parts.append("Contexto na saída: " + "; ".join(market_notes))
    parts.append("Lembrete do setup de entrada: " + ("; ".join(trade.entry_reasons[:3]) or "COMBO5"))
    return " ".join(parts)
