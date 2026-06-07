"""Pesquisa sob demanda — LLMQuant + Haiku (QuantMind-style context)."""

from __future__ import annotations

import logging
import os
import re

from lib import llmquant_client

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _wiki_usable(title: str, summary: str) -> bool:
    """Evita corpo wiki em idiomas não latinos — summary basta."""
    blob = f"{title} {summary}"
    if not blob.strip():
        return False
    cjk = len(_CJK_RE.findall(blob))
    return cjk < max(len(blob) * 0.25, 8)


def _haiku_synthesize(query: str, context_blocks: list[str]) -> str:
    if not ANTHROPIC_API_KEY:
        return "\n\n".join(context_blocks)[:2800]

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    ctx = "\n\n---\n\n".join(context_blocks)[:10000]
    prompt = f"""Você é analista quant crypto no Telegram. Pergunta do utilizador:
"{query}"

Use APENAS o contexto (Quant Wiki, papers, preços). Responda em português, curto para telemóvel (~900 caracteres máx.).

Formato (HTML simples — use <b> nos títulos das secções):

📊 <b>Mercado agora</b>
• BTC, ETH, SOL: preço e variação 24h (só números do contexto)

💡 <b>Leitura para trade</b>
• 2–3 bullets objetivos (momentum, risco, correlação) — linguagem de trader, não tese académica

📚 <b>Fontes</b>
• 2–4 linhas curtas: [Paper: título] ou [Wiki: título em PT se possível]

Regras:
- Não invente números
- Não faça secção longa "o que falta" — no máximo 1 frase no fim se for crítico
- Títulos de papers/wiki em inglês/chinês: cite o original, traduza brevemente entre parênteses se útil
- Isto é contexto, não ordem de trade

CONTEXTO:
{ctx}
"""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=550,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.error("Haiku research falhou: %s", exc)
        return "\n\n".join(context_blocks)[:2800]


def gather_context(query: str) -> tuple[list[str], list[str]]:
    """Retorna (blocos de texto, avisos)."""
    blocks: list[str] = []
    notes: list[str] = []

    if not llmquant_client.configured():
        notes.append("LLMQUANT_API_KEY ausente — só análise local de notícias.")
        return blocks, notes

    try:
        for hit in llmquant_client.wiki_search(query, top_k=3):
            title = hit.get("title", "Wiki")
            summary = hit.get("summary", "")
            wid = hit.get("wikiItemId")
            extra = ""
            if wid and _wiki_usable(title, summary):
                full = llmquant_client.wiki_read(wid, max_length=900)
                if full:
                    extra = (full.get("body_markdown") or "")[:900]
            blocks.append(f"[Wiki: {title}]\n{summary}\n{extra}".strip())
    except Exception as exc:
        logger.warning("wiki_search: %s", exc)
        notes.append(f"Wiki indisponível: {exc}")

    try:
        papers = llmquant_client.paper_search(query, top_k=2)
        for p in papers:
            title = p.get("title") or p.get("paperCardId", "Paper")
            card = p.get("paperCardId")
            snippet = p.get("summary") or p.get("abstract") or ""
            if card:
                body = llmquant_client.paper_read(card, sections=["introduction", "conclusion"])
                if body:
                    for sec in body.get("sections") or []:
                        snippet += "\n" + (sec.get("content") or "")[:600]
            blocks.append(f"[Paper: {title}]\n{snippet[:1500]}".strip())
    except Exception as exc:
        logger.warning("paper_search: %s", exc)
        notes.append(f"Papers indisponíveis: {exc}")

    for sym in ("BTC-USD", "ETH-USD", "SOL-USD"):
        try:
            snap = llmquant_client.crypto_snapshot(sym)
            if snap:
                blocks.append(
                    f"[Mercado {sym}] ${snap.get('price', 0):,.2f} "
                    f"({snap.get('dayChangePercent', 0):+.2f}% 24h)"
                )
        except Exception as exc:
            logger.debug("snapshot %s: %s", sym, exc)

    return blocks, notes


def research(query: str) -> str:
    query = query.strip()
    if not query:
        return "Envie uma pergunta. Ex.: <code>momentum em crypto</code>"

    blocks, notes = gather_context(query)
    if not blocks:
        return (
            "Sem contexto LLMQuant para esta consulta.\n"
            + ("\n".join(notes) if notes else "Configure LLMQUANT_API_KEY.")
        )

    answer = _haiku_synthesize(query, blocks)
    if notes:
        answer += "\n\n<i>" + " · ".join(notes) + "</i>"
    return answer[:3200]


def format_for_telegram(query: str, answer: str) -> str:
    """Cabeçalho consistente com o canal [QUANT]."""
    q = query.strip()[:120]
    body = answer.strip()
    return (
        f"🔎 <b>Pesquisa:</b> {q}\n\n"
        f"{body}\n\n"
        "<i>Contexto LLMQuant — não é ordem de trade. Cruze com [KRONOS] e funding.</i>"
    )
