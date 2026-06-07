#!/usr/bin/env python3
"""Teste rápido QUANT — rode na VPS antes de ligar o bot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import llmquant_client, quant_state  # noqa: E402
from lib.kronos_quant import apply_to_results, conflict_note, format_kronos_footer  # noqa: E402


def main() -> int:
    ok = True
    print("=== QUANT test ===\n")

    # 1) LLMQuant API
    if llmquant_client.configured():
        try:
            hits = llmquant_client.wiki_search("bitcoin momentum", top_k=1)
            print(f"[OK] LLMQuant wiki_search: {len(hits)} hit(s)")
            if hits:
                print(f"     → {hits[0].get('title', '?')}")
        except Exception as exc:
            print(f"[FAIL] LLMQuant: {exc}")
            ok = False
    else:
        print("[SKIP] LLMQUANT_API_KEY não definida")

    # 2) Estado + hook Kronos (simulado)
    state_path = Path(os.environ.get("QUANT_STATE_PATH", "/tmp/quant_state_test.json"))
    os.environ["QUANT_STATE_PATH"] = str(state_path)
    data = quant_state.load()
    quant_state.set_ticker_impact(
        data,
        "BTC",
        bias="BEARISH",
        impact_score=0.82,
        headline="[TESTE] Evento simulado bearish BTC",
        summary="Teste de integração QUANT → Kronos",
        url=None,
    )
    quant_state.save(data)
    print(f"[OK] quant_state gravado em {state_path}")

    note = conflict_note("BTC", "BULLISH")
    print(f"[OK] conflict_note BTC BULLISH vs QUANT: {note[:80]}...")

    fake = {
        "4h": [
            {"ticker": "BTC", "bias": "BULLISH", "tradeable": True, "align_note": ""},
        ]
    }
    apply_to_results(fake)
    r = fake["4h"][0]
    mode = os.environ.get("QUANT_KRONOS_MODE", "warn")
    print(f"[OK] apply_to_results (mode={mode}): tradeable={r.get('tradeable')} note={r.get('align_note', '')[:60]}")

    print("\n--- Footer Kronos ---")
    print(format_kronos_footer().replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))

    # 3) Telegram (opcional)
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        try:
            from lib.telegram import send_quant_alert

            send_quant_alert("Teste QUANT", "Integração OK — pode usar /pesquisa e /quant no bot.")
            print("\n[OK] Telegram [QUANT] enviado")
        except Exception as exc:
            print(f"\n[WARN] Telegram: {exc}")
    else:
        print("\n[SKIP] Telegram — defina TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")

    print("\n=== Fim ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
