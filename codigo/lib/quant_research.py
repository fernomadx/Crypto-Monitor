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


def _sanitize_answer(text: str) -> str:
    """Remove secções académicas que o modelo insiste em gerar."""
    lines: list[str] = []
    skip = False
    for line in text.splitlines():
        low = line.lower().strip()
        if any(
            k in low
            for k in (
                "falta no contexto",
                "o que falta",
                "falta:",
                "missing context",
                "dados em falta",
            )
        ):
            skip = True
            continue
        if skip and (line.startswith("•") or line.startswith("-") or not line.strip()):
            if not line.strip():
                skip = False
            continue
        skip = False
        lines.append(line)
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def _haiku_synthesize(query: str, context_blocks: list[str]) -> str:
    if not ANTHROPIC_API_KEY:
        return "\n\n".join(context_blocks)[:2800]

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    ctx = "\n\n---\n\n".join(context_blocks)[:10000]
    prompt = f"""Analista crypto no Telegram. Pergunta: "{query}"

CONTEXTO (use só isto):
{ctx}

Responda em português. MÁXIMO 700 caracteres no total. Sem parágrafos longos.

Copie EXATAMENTE esta estrutura (3 secções, nada mais):

📊 <b>Mercado</b>
BTC $X (+Y% 24h) · ETH $X (+Y%) · SOL $X (+Y%)

💡 <b>Leitura</b>
• (1 frase: momentum / rotação altcoins)
• (1 frase: risco — stop/disciplina)

📚 <b>Fontes</b>
• [Paper: nome curto] · [Wiki: nome curto]

PROIBIDO: listar dados em falta, volume, IV, correlação histórica, janelas 20d/60d, secção "falta no contexto", mais de 2 bullets em Leitura, citar ML/Random Forest salvo se for 1 linha na Leitura.
"""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=380,
            messages=[{"role": "user", "content": prompt}],
        )
        return _sanitize_answer(msg.content[0].text.strip())[:1100]
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
        for hit in llmquant_client.wiki_search(query, top_k=2):
            title = hit.get("title", "Wiki")
            summary = (hit.get("summary") or "")[:400]
            if _wiki_usable(title, summary):
                blocks.append(f"[Wiki: {title}] {summary}".strip())
    except Exception as exc:
        logger.warning("wiki_search: %s", exc)
        notes.append(f"Wiki indisponível: {exc}")

    try:
        papers = llmquant_client.paper_search(query, top_k=1)
        for p in papers:
            title = p.get("title") or p.get("paperCardId", "Paper")
            snippet = (p.get("summary") or p.get("abstract") or "")[:350]
            blocks.append(f"[Paper: {title}] {snippet}".strip())
    except Exception as exc:
        logger.warning("paper_search: %s", exc)
        notes.append(f"Papers indisponíveis: {exc}")

    market: list[str] = []
    for sym in ("BTC-USD", "ETH-USD", "SOL-USD"):
        try:
            snap = llmquant_client.crypto_snapshot(sym)
            if snap:
                market.append(
                    f"{sym} ${snap.get('price', 0):,.2f} "
                    f"({snap.get('dayChangePercent', 0):+.2f}% 24h)"
                )
        except Exception as exc:
            logger.debug("snapshot %s: %s", sym, exc)

    # Preços primeiro — o modelo prioriza mercado sobre papers
    if market:
        blocks[:0] = ["[Preços ao vivo] " + " · ".join(market)]

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
    return answer[:1400]


def format_for_telegram(query: str, answer: str) -> str:
    """Cabeçalho consistente com o canal [QUANT]."""
    q = query.strip()[:120]
    body = answer.strip()
    return (
        f"🔎 <b>Pesquisa:</b> {q}\n\n"
        f"{body}\n\n"
        "<i>Contexto LLMQuant — não é ordem de trade. Cruze com [KRONOS] e funding.</i>"
    )
