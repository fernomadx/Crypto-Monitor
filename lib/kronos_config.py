"""Configuração Kronos — versão e parâmetros ativos (boot + rodapé Telegram)."""

from __future__ import annotations

import os

RULES_VERSION = "3.1"


def active_config() -> dict[str, str]:
    return {
        "rules": RULES_VERSION,
        "model": os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-mini"),
        "temperature": os.environ.get("KRONOS_TEMPERATURE", "0.65"),
        "bias_threshold": os.environ.get("KRONOS_BIAS_THRESHOLD_PCT", "0.30"),
        "min_target": os.environ.get("KRONOS_MIN_TARGET_PCT", "0.5"),
        "min_rr": os.environ.get("KRONOS_MIN_RR", "2.0"),
        "stop_4h": os.environ.get("KRONOS_MAX_STOP_PCT_4H", "1.8"),
        "entry_offset": os.environ.get("KRONOS_LIMIT_ENTRY_OFFSET_PCT", "0.15"),
        "entry_bars": os.environ.get("KRONOS_LIMIT_ENTRY_BARS", "6"),
        "leverage": os.environ.get("KRONOS_LEVERAGE", "10"),
        "score_tf": os.environ.get("KRONOS_SCORE_INTERVAL", "4h"),
        "align": "3TFs-iguais",
    }


def format_config_footer() -> str:
    c = active_config()
    return (
        f"<i>Kronos rules v{c['rules']} · R:R {c['min_rr']} · stop4H {c['stop_4h']}% · "
        f"alvo=ML · 3TFs · sim {c['leverage']}x</i>"
    )


def format_boot_message() -> str:
    c = active_config()
    tickers = os.environ.get("TICKERS", "BTC,ETH,SOL")
    lines = [
        f"<b>Kronos v{c['rules']} ativo</b> (regras anti-loss)",
        f"Moedas: <code>{tickers}</code>",
        f"Temp {c['temperature']} · viés ±{c['bias_threshold']}% · alvo mín {c['min_target']}%",
        f"R:R {c['min_rr']} · stop 4H {c['stop_4h']}% · entrada pullback {c['entry_offset']}%",
        f"Scorecard: <b>{c['score_tf'].upper()}</b> só com <b>3 TFs iguais</b> (sem conflito)",
        "Gerando 1ª previsão (CPU: 15–40 min)...",
    ]
    return "\n".join(lines)
