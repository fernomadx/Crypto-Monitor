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

    Com 3 timeframes: exige os 3 no mesmo viés (sem NEUTRO, sem split).
    """
    if not biases:
        return "neutral", "sem dados"

    n = len(biases)
    values = list(biases.values())
    neutrals = sum(1 for v in values if v == "NEUTRO")
    bulls = sum(1 for v in values if v == "BULLISH")
    bears = sum(1 for v in values if v == "BEARISH")

    if n >= 3:
        if neutrals > 0:
            return "neutral", "TF sem viés direcional"
        if bulls == n:
            return "aligned", f"alinhado alta ({n} TFs)"
        if bears == n:
            return "aligned", f"alinhado baixa ({n} TFs)"
        return "conflict", "conflito entre timeframes"

    sides = [_side(b) for b in values if _side(b) != 0]
    if len(sides) < MIN_TF_AGREEMENT:
        return "neutral", "poucos TFs com viés claro"
    if bulls >= MIN_TF_AGREEMENT and bears == 0:
        return "aligned", f"alinhado alta ({bulls}/{n} TFs)"
    if bears >= MIN_TF_AGREEMENT and bulls == 0:
        return "aligned", f"alinhado baixa ({bears}/{n} TFs)"
    return "conflict", "conflito entre timeframes"


def _dominant_bias(biases: dict[str, str]) -> str | None:
    """Viés majoritário entre TFs direcionais (BULLISH ou BEARISH)."""
    bulls = sum(1 for b in biases.values() if b == "BULLISH")
    bears = sum(1 for b in biases.values() if b == "BEARISH")
    if bulls > bears and bulls >= MIN_TF_AGREEMENT:
        return "BULLISH"
    if bears > bulls and bears >= MIN_TF_AGREEMENT:
        return "BEARISH"
    return None


def tradeable_for_interval(ticker: str, interval: str, biases: dict[str, str]) -> tuple[bool, str]:
    """
    Pode entrar no catálogo/scorecard neste TF?
    - Scorecard (4H): exige viés direcional no 4H, alinhado ao consenso.
    - 1h: não se divergir de 4h e 4h = 1d (mesmo viés).
    """
    iv = interval.lower()
    status, note = alignment_summary(biases)
    b1 = biases.get("1h", "NEUTRO")
    b4 = biases.get("4h", "NEUTRO")
    bd = biases.get("1d", "NEUTRO")
    iv_bias = biases.get(iv, "NEUTRO")

    if iv == SCORE_INTERVAL and _side(iv_bias) == 0:
        return False, f"{iv.upper()} sem viés direcional — não entra no scorecard"

    dominant = _dominant_bias(biases)

    # Scorecard: exige consenso total — sem fallback 4H+D com 1H oposto
    if iv == SCORE_INTERVAL:
        if status == "conflict":
            return False, "conflito multi-TF — não entra no scorecard"
        if status != "aligned":
            return False, note
        if dominant and iv_bias != dominant:
            return False, f"4H ({iv_bias}) não confirma consenso {dominant}"
        return True, note

    if status == "aligned":
        return True, note

    # 4h + diário concordam → informativo em 1d; 1h divergente ignorado
    if b4 != "NEUTRO" and b4 == bd and _side(b4) != 0:
        if iv == "1h" and b1 != b4:
            return False, "1H diverge de 4H/D — ignorado"
        if iv == "1d":
            return True, "4H e Diário alinhados"
        return False, note

    return False, note


def should_log_to_scorecard(interval: str, tradeable: bool, result: dict | None = None) -> bool:
    if interval.lower() != SCORE_INTERVAL or not tradeable:
        return False
    if result is None:
        return True
    if result.get("bias") not in ("BULLISH", "BEARISH"):
        return False
    if not result.get("has_levels", True):
        return False
    from lib.kronos_config import ticker_in_scorecard

    if not ticker_in_scorecard(result.get("ticker", "")):
        return False
    return True


def format_alignment_report(biases_by_ticker: dict[str, dict[str, str]]) -> str:
    lines = [
        "<b>📐 Consenso multi-timeframe</b>",
        f"<i>Scorecard: só <b>{SCORE_INTERVAL.upper()}</b> com <b>3 TFs no mesmo viés</b> "
        f"(conflito = não entra, mesmo se 4H=D).</i>",
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
