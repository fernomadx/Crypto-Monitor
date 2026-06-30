"""Configuração Kronos — versão, defaults v4.0 e bootstrap (sobrescreve vars antigas Railway)."""

from __future__ import annotations

import os

RULES_VERSION = "4.0"

# v4.0 — capital preservation: 3x, alvos ≥1%, stop 4H apertado, só BTC no scorecard
V40_DEFAULTS: dict[str, str] = {
    "KRONOS_TEMPERATURE": "0.65",
    "KRONOS_BIAS_THRESHOLD_PCT": "0.40",
    "KRONOS_MIN_TARGET_PCT": "1.0",
    "KRONOS_MIN_RR": "3.0",
    "KRONOS_MAX_STOP_PCT_4H": "0.8",
    "KRONOS_MAX_STOP_PCT": "1.0",
    "KRONOS_LIMIT_ENTRY_OFFSET_PCT": "0.10",
    "KRONOS_LIMIT_ENTRY_BARS": "4",
    "KRONOS_MIN_TF_AGREEMENT": "3",
    "KRONOS_SAMPLE_COUNT": "4",
    "KRONOS_LEVERAGE": "3",
    "KRONOS_SCORE_INTERVAL": "4h",
    "KRONOS_MIN_EDGE_PCT": "0.15",
    "KRONOS_SCORE_TICKERS": "BTC",
    "QUANT_KRONOS_MODE": "veto",
}

# Alias legado (v3.x usava estes nomes internamente)
V31_DEFAULTS = V40_DEFAULTS


def apply_kronos_defaults(force: bool = True) -> None:
    """
    Garante parâmetros v4.0 no boot.
    force=True: sobrescreve vars antigas do Railway (10x, MIN_RR=1.5, etc.).
    """
    for key, val in V40_DEFAULTS.items():
        if force or not os.environ.get(key):
            os.environ[key] = val


def apply_v31_defaults(force: bool = True) -> None:
    """Alias retrocompatível — chama apply_kronos_defaults."""
    apply_kronos_defaults(force=force)


def score_tickers() -> frozenset[str]:
    """Tickers permitidos no scorecard (ex.: BTC → só Bitcoin)."""
    raw = os.environ.get("KRONOS_SCORE_TICKERS", "BTC").strip()
    if not raw or raw.lower() in ("*", "all"):
        return frozenset()
    return frozenset(t.strip().upper().replace("USDT", "") for t in raw.split(",") if t.strip())


def ticker_in_scorecard(ticker: str) -> bool:
    allow = score_tickers()
    if not allow:
        return True
    return ticker.upper().replace("USDT", "") in allow


def active_config() -> dict[str, str]:
    return {
        "rules": RULES_VERSION,
        "model": os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-mini"),
        "temperature": os.environ.get("KRONOS_TEMPERATURE", "0.65"),
        "bias_threshold": os.environ.get("KRONOS_BIAS_THRESHOLD_PCT", "0.40"),
        "min_target": os.environ.get("KRONOS_MIN_TARGET_PCT", "1.0"),
        "min_rr": os.environ.get("KRONOS_MIN_RR", "3.0"),
        "stop_4h": os.environ.get("KRONOS_MAX_STOP_PCT_4H", "0.8"),
        "entry_offset": os.environ.get("KRONOS_LIMIT_ENTRY_OFFSET_PCT", "0.10"),
        "entry_bars": os.environ.get("KRONOS_LIMIT_ENTRY_BARS", "4"),
        "leverage": os.environ.get("KRONOS_LEVERAGE", "3"),
        "score_tf": os.environ.get("KRONOS_SCORE_INTERVAL", "4h"),
        "score_tickers": os.environ.get("KRONOS_SCORE_TICKERS", "BTC"),
        "align": "3TFs-iguais",
    }


def format_config_footer() -> str:
    c = active_config()
    tickers = c["score_tickers"]
    return (
        f"<i>Kronos rules v{c['rules']} · R:R {c['min_rr']} · stop4H {c['stop_4h']}% · "
        f"alvo≥{c['min_target']}% · 3TFs · sim {c['leverage']}x · scorecard {tickers}</i>"
    )


def format_boot_message() -> str:
    c = active_config()
    tickers = os.environ.get("TICKERS", "BTC,ETH,SOL")
    score = c["score_tickers"]
    lines = [
        f"<b>Kronos v{c['rules']} ativo</b> (preservação de capital)",
        f"Moedas analisadas: <code>{tickers}</code>",
        f"Scorecard: só <b>{score}</b> · {c['score_tf'].upper()} · 3 TFs alinhados",
        f"Temp {c['temperature']} · viés ±{c['bias_threshold']}% · alvo mín {c['min_target']}%",
        f"R:R {c['min_rr']} · stop 4H {c['stop_4h']}% · entrada pullback {c['entry_offset']}%",
        f"Simulação: <b>{c['leverage']}x</b> (margem $100 · nocional ${float(c['leverage']) * 100:.0f})",
        "QUANT modo <b>veto</b> — bloqueia 4H se notícia contradiz.",
        "Daemon: alerta ~1–3 min após fechar candle (1H · 4H · Diário UTC).",
        "<b>⚠️ Scorecard antigo (v3.x 10x)?</b> Rode reset para recomeçar limpo:",
        "<code>python3 vps/kronos_reset_catalog.py --confirm</code>",
    ]
    return "\n".join(lines)
