"""
Alinhamento multi-timeframe — evita catalogar/scorear sinais conflitantes.

Regras:
  - Operável: ≥2 TFs com o mesmo viés (BULLISH/BEARISH).
  - 1H ignorado no catálogo se divergir de 4H e 4H = Diário.
  - Scorecard: só intervalo primário (padrão 4h) e símbolos operáveis.
"""

from __future__ import annotations

import os

MIN_TF_AGREEMENT = int(os.environ.get("KRONOS_MIN_TF_AGREEMENT", "2"))
SCORE_INTERVAL = os.environ.get("KRONOS_SCORE_INTERVAL", "4h").strip().lower()


def _side(bias: str) -> int:
    if bias == "BULLISH":
        return 1
    if bias == "BEARISH":
        return -1
    return 0


def collect_biases_by_ticker(results_by_interval: dict[str, list[dict]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for interval, results in results_by_interval.items():
        key = interval.lower()
        for r in results:
            out.setdefault(r["ticker"], {})[key] = r.get("bias", "NEUTRO")
    return out


def alignment_summary(biases: dict[str, str]) -> tuple[str, str]:
    """
    Retorna (status, nota).
    status: aligned | conflict | neutral
    """
    sides = [_side(b) for b in biases.values() if _side(b) != 0]
    if len(sides) < MIN_TF_AGREEMENT:
        return "neutral", "poucos TFs com viés claro"

    bulls = sum(1 for s in sides if s > 0)
    bears = sum(1 for s in sides if s < 0)
    if bulls >= MIN_TF_AGREEMENT and bears == 0:
        return "aligned", f"alinhado alta ({bulls}/{len(biases)} TFs)"
    if bears >= MIN_TF_AGREEMENT and bulls == 0:
        return "aligned", f"alinhado baixa ({bears}/{len(biases)} TFs)"
    return "conflict", "conflito entre timeframes"


def tradeable_for_interval(ticker: str, interval: str, biases: dict[str, str]) -> tuple[bool, str]:
    """
    Pode entrar no catálogo/scorecard neste TF?
    - 1h: não se divergir de 4h e 4h = 1d (mesmo viés).
    - Geral: precisa de alinhamento global OU 4h+1d alinhados (intervalo primário).
    """
    iv = interval.lower()
    status, note = alignment_summary(biases)
    b1 = biases.get("1h", "NEUTRO")
    b4 = biases.get("4h", "NEUTRO")
    bd = biases.get("1d", "NEUTRO")

    if status == "aligned":
        return True, note

    # 4h + diário concordam → operável em 4h e 1d, não em 1h divergente
    if b4 != "NEUTRO" and b4 == bd and _side(b4) != 0:
        if iv == "1h" and b1 != b4:
            return False, "1H diverge de 4H/D — ignorado"
        if iv in ("4h", "1d"):
            return True, "4H e Diário alinhados"
        return False, note

    return False, note


def should_log_to_scorecard(interval: str, tradeable: bool) -> bool:
    return interval.lower() == SCORE_INTERVAL and tradeable


def format_alignment_report(biases_by_ticker: dict[str, dict[str, str]]) -> str:
    lines = [
        "<b>📐 Consenso multi-timeframe</b>",
        f"<i>Scorecard: só <b>{SCORE_INTERVAL.upper()}</b> com ≥{MIN_TF_AGREEMENT} TFs alinhados "
        f"(1H omitido se divergir de 4H=D).</i>",
        "",
    ]
    for ticker in sorted(biases_by_ticker):
        biases = biases_by_ticker[ticker]
        status, note = alignment_summary(biases)
        tf_txt = " · ".join(f"{k.upper()} {v}" for k, v in sorted(biases.items()))
        icon = "✅" if status == "aligned" else "⚠️" if status == "conflict" else "➖"
        op4, _ = tradeable_for_interval(ticker, "4h", biases)
        score = "entra no scorecard" if op4 and SCORE_INTERVAL == "4h" else "só informativo"
        lines.append(f"{icon} <b>{ticker}</b>: {note} — {tf_txt} ({score})")
    return "\n".join(lines)
