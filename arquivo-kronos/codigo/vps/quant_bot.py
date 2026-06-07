#!/usr/bin/env python3
"""
Bot QUANT — pesquisa sob demanda no Telegram.

Comandos (só responde TELEGRAM_CHAT_ID autorizado):
  /quant, /contexto     — estado atual (notícias de impacto)
  /pesquisa <pergunta>  — consulta LLMQuant + Haiku
  /btc /eth /sol        — snapshot mercado + contexto
  /help

Rodar no Hetzner: nohup python vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
"""

from __future__ import annotations

import fcntl
import logging
import os
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import llmquant_client, quant_research, quant_state  # noqa: E402
from lib.kronos_quant import format_kronos_footer, ticker_context  # noqa: E402
from lib.telegram import send_quant_reply  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OFFSET_PATH = Path(os.environ.get("QUANT_BOT_OFFSET", "/data/quant_bot_offset.txt"))
SINGLETON_LOCK = Path(os.environ.get("QUANT_BOT_LOCK", "/data/quant_bot.lock"))
POLL_SEC = int(os.environ.get("QUANT_BOT_POLL_SEC", "2"))
_singleton_fp = None


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _allowed_chat() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _api(method: str, **kwargs) -> dict:
    token = _bot_token()
    resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=kwargs, timeout=30)
    if resp.status_code == 409:
        raise RuntimeError(
            "Telegram 409: outro processo usa getUpdates neste bot "
            "(webhook ou segunda instância). Pare duplicatas."
        )
    resp.raise_for_status()
    return resp.json()


def _acquire_singleton() -> bool:
    """Uma única instância por container (evita /ping duplicado)."""
    global _singleton_fp
    SINGLETON_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fp = open(SINGLETON_LOCK, "w")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fp.close()
        logger.warning("QUANT bot já rodando — saindo")
        return False
    fp.write(str(os.getpid()))
    fp.flush()
    _singleton_fp = fp
    return True


def _ensure_polling() -> None:
    """Remove webhook para permitir getUpdates (comum após deploy)."""
    try:
        _api("deleteWebhook", drop_pending_updates=False)
        logger.info("Telegram: webhook removido — modo polling ativo")
    except Exception as exc:
        logger.warning("deleteWebhook: %s", exc)


def _load_offset() -> int:
    if OFFSET_PATH.exists():
        try:
            return int(OFFSET_PATH.read_text().strip())
        except ValueError:
            pass
    return 0


def _save_offset(offset: int) -> None:
    OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_PATH.write_text(str(offset))


def _llmquant_status_line(*, verify: bool = False) -> str:
    if not llmquant_client.configured():
        return "⚠️ LLMQuant: configure <code>LLMQUANT_API_KEY</code> para pesquisa completa."
    if not verify:
        return "✅ LLMQuant configurado — <code>/pesquisa</code> e preços ativos."
    ok, detail = llmquant_client.health_check()
    if ok:
        return f"✅ LLMQuant — {detail}"
    return f"⚠️ LLMQuant: {detail}"


def _help_text() -> str:
    return (
        "<b>🧠 QUANT — comandos</b>\n\n"
        "/quant ou /contexto — notícias de impacto recentes\n"
        "/pesquisa &lt;pergunta&gt; — pesquisa Quant Wiki + papers\n"
        "/btc · /eth · /sol — preço + contexto\n"
        "/ping — teste de conexão (também aceita /pin)\n"
        "/help — esta ajuda\n\n"
        f"<i>Canal [QUANT] separado do [KRONOS].</i>\n"
        f"<i>{_llmquant_status_line()}</i>"
    )


def _handle_context() -> str:
    return format_kronos_footer()


def _handle_snapshot(symbol: str) -> str:
    sym = symbol.upper()
    lines = [f"<b>{sym}</b>"]
    ctx = ticker_context(sym)
    if ctx:
        lines.append(
            f"Contexto: {ctx.get('bias')} ({ctx.get('impact_score', 0):.0%}) — "
            f"{ctx.get('summary', '')}"
        )
    if llmquant_client.configured():
        try:
            snap = llmquant_client.crypto_snapshot(f"{sym}-USD")
            if snap:
                lines.append(
                    f"Preço: ${snap.get('price', 0):,.2f} "
                    f"({snap.get('dayChangePercent', 0):+.2f}% 24h)"
                )
        except Exception as exc:
            lines.append(f"<i>Snapshot: {exc}</i>")
    else:
        lines.append("<i>LLMQUANT_API_KEY não configurada.</i>")
    return "\n".join(lines)


def _dispatch(text: str) -> str:
    cmd, _, rest = text.strip().partition(" ")
    cmd = cmd.split("@")[0].lower()
    rest = rest.strip()

    if cmd in ("/start", "/help"):
        return _help_text()
    if cmd in ("/ping", "/pin"):
        from lib.quant_impact import impact_alerts_enabled

        api = _llmquant_status_line()
        thresh = os.environ.get("QUANT_IMPACT_THRESHOLD", "0.70")
        alerts = (
            f"⚡ Alertas fortes: <b>ON</b> (≥{thresh})"
            if impact_alerts_enabled()
            else "Alertas fortes: off (só digest 1H)"
        )
        return (
            f"<b>QUANT online</b>\n{api}\n{alerts}\n"
            f"Modo Kronos: <code>{os.environ.get('QUANT_KRONOS_MODE', 'warn')}</code>"
        )
    if cmd in ("/quant", "/contexto"):
        return _handle_context()
    if cmd in ("/pesquisa", "/research", "/p"):
        if not rest:
            return "Uso: <code>/pesquisa momentum em crypto</code>"
        answer = quant_research.research(rest)
        state = quant_state.load()
        quant_state.set_last_research(state, rest, answer)
        quant_state.save(state)
        return f"<b>Pesquisa:</b> {rest}\n\n{answer}"
    if cmd in ("/btc", "/eth", "/sol"):
        return _handle_snapshot(cmd[1:].upper())
    return _help_text()


def run() -> None:
    if not _bot_token() or not _allowed_chat():
        raise RuntimeError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID obrigatórios")

    if not _acquire_singleton():
        return

    logger.info("QUANT bot ativo (chat %s)", _allowed_chat())
    _ensure_polling()
    offset = _load_offset()

    while True:
        try:
            data = _api("getUpdates", offset=offset, timeout=30, allowed_updates=["message"])
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()

                if chat_id != _allowed_chat() or not text.startswith("/"):
                    continue

                logger.info("Comando: %s", text[:80])
                reply = _dispatch(text)
                send_quant_reply(chat_id, reply)

            _save_offset(offset)
        except Exception as exc:
            logger.exception("quant_bot loop: %s", exc)
            time.sleep(5)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
