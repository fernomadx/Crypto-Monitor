#!/usr/bin/env python3
"""
Bot QUANT — pesquisa sob demanda no Telegram.

Comandos (só responde TELEGRAM_CHAT_ID autorizado):
  /quant, /contexto     — estado atual (notícias de impacto)
  /pesquisa <pergunta>  — consulta LLMQuant + Haiku
  /combo5, /analise     — análise COMBO5 ao vivo (fora do cron)
  /combo5 ranking       — ranking paper COMBO5 (7d/30d)
  /c5score              — atalho do ranking COMBO5
  /mexc                 — 📊 MEXC Análise (spot + futuros, sem CCXT)
  /btc /eth /sol        — snapshot mercado + contexto
  /scorecard            — acerto Kronos (simulação 4H)
  /vps [IP|test]        — configura/testa Hetzner BTCCURSOR
  /help

Rodar no Hetzner: nohup python vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
COMBO5_RANKING_SUBCOMMANDS = frozenset(
    {
        "ranking",
        "rank",
        "score",
        "scorecard",
        "performance",
        "perf",
        "desempenho",
    }
)


def _enabled() -> bool:
    return os.environ.get("QUANT_BOT_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _allowed_chat() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


class TelegramConflict(RuntimeError):
    """Telegram 409 — outro getUpdates (Railway vs Hetzner) no mesmo token."""


def _api(method: str, **kwargs) -> dict:
    token = _bot_token()
    resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=kwargs, timeout=30)
    if resp.status_code == 409:
        raise TelegramConflict(
            "Telegram 409: outro processo usa getUpdates neste bot "
            "(webhook ou segunda instância Hetzner/Railway). "
            "Na VPS: QUANT_BOT_ENABLED=0 e mate quant_bot.py."
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


def _bot_mode() -> str:
    raw = os.environ.get("QUANT_BOT_MODE", "auto").strip().lower()
    if raw in {"webhook", "poll", "polling"}:
        return "poll" if raw == "polling" else raw
    return "auto"


def _webhook_secret() -> str:
    explicit = os.environ.get("QUANT_WEBHOOK_SECRET", "").strip()
    if explicit:
        return explicit[:256]
    token = _bot_token()
    return hashlib.sha256(f"quant-webhook:{token}".encode("utf-8")).hexdigest()


def webhook_public_url() -> str:
    """URL HTTPS que o Telegram chama. Vazio = usar polling."""
    explicit = os.environ.get("QUANT_WEBHOOK_URL", "").strip()
    if explicit:
        url = explicit.rstrip("/")
        if not url.endswith("/telegram"):
            url = f"{url}/telegram"
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        return url
    domain = (
        os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or os.environ.get("RAILWAY_STATIC_URL")
        or ""
    ).strip()
    if not domain:
        return ""
    if domain.startswith("http://"):
        domain = "https://" + domain[len("http://") :]
    elif not domain.startswith("https://"):
        domain = f"https://{domain}"
    return domain.rstrip("/") + "/telegram"


def _listen_port() -> int:
    raw = os.environ.get("PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    if os.environ.get("RAILWAY_ENVIRONMENT") or webhook_public_url():
        return 8080
    return 0


def _ensure_polling() -> None:
    """Remove webhook para permitir getUpdates (comum após deploy)."""
    try:
        _api("deleteWebhook", drop_pending_updates=False)
        logger.info("Telegram: webhook removido — modo polling ativo")
    except Exception as exc:
        logger.warning("deleteWebhook: %s", exc)


def _ensure_webhook(url: str) -> None:
    secret = _webhook_secret()
    last_err = "sem tentativa"
    for attempt in range(1, 9):
        try:
            data = _api(
                "setWebhook",
                url=url,
                secret_token=secret,
                allowed_updates=["message"],
                drop_pending_updates=False,
            )
            if data.get("ok"):
                logger.info("Telegram webhook ativo: %s", url)
                return
            last_err = str(data)
        except Exception as exc:
            last_err = str(exc)
        logger.warning("setWebhook tentativa %s/8: %s", attempt, last_err)
        time.sleep(min(5 * attempt, 20))
    raise RuntimeError(f"setWebhook falhou: {last_err}")


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
        "/combo5 ou /analise — análise COMBO5 <b>agora</b> (fora do cron)\n"
        "/combo5 BTC — mesmo, forçando o par\n"
        "/combo5 ranking ou /c5score — ranking paper (entrada/saída 7d/30d)\n"
        "/mexc — 📊 MEXC Análise (spot + futuros + funding)\n"
        "/mexc BTC — mesmo, forçando o par\n"
        "/btc · /eth · /sol — preço + contexto\n"
        "/ping — teste de conexão (também aceita /pin)\n"
        "/scorecard — acerto das entradas Kronos (7d/30d, simulação 4H)\n"
        "/scorecard diario — ranking por timeframe + resumo\n"
        "/resetscorecard — apaga catálogo e recomeça scorecard v5 limpo\n"
        "/vps — status Hetzner · <code>/vps test</code> desliga Kronos duplicado · <code>/vps IP</code>\n"
        "/help — esta ajuda\n\n"
        f"<i>Canal [QUANT] separado do [KRONOS]/[COMBO5].</i>\n"
        f"<i>{_llmquant_status_line()}</i>"
    )


def _handle_context() -> str:
    return format_kronos_footer()


def _handle_mexc(args: str) -> str:
    """📊 MEXC Análise — spot + futuros (substitui CCXT / RequestTimeout)."""
    from lib.mexc_analise import analyze_now

    try:
        return analyze_now(args.strip() or None)
    except Exception as exc:
        logger.exception("mexc análise: %s", exc)
        return f"⚠️ Falha na MEXC Análise: {exc}"


def _combo5_ranking_request(args: str) -> bool:
    first = args.strip().split()[0].lower() if args.strip() else ""
    return first in COMBO5_RANKING_SUBCOMMANDS


def _combo5_pre(heading: str, body: str) -> str:
    plain = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"🎯 <b>[COMBO5]</b> {heading}\n\n<pre>{plain}</pre>"


def _handle_combo5_ranking() -> str:
    from vps.combo5_signal import ranking_now

    try:
        body = ranking_now()
    except Exception as exc:
        logger.exception("combo5 ranking: %s", exc)
        return f"⚠️ Falha no ranking COMBO5: {exc}"
    return _combo5_pre("ranking", body)


def _handle_combo5(args: str) -> str:
    """Análise COMBO5 sob demanda — mesmo motor do cron 5 min / horário."""
    if _combo5_ranking_request(args):
        return _handle_combo5_ranking()

    from vps.combo5_signal import analyze_now

    try:
        body = analyze_now(args.strip() or None)
    except Exception as exc:
        logger.exception("combo5 on-demand: %s", exc)
        return f"⚠️ Falha na análise COMBO5: {exc}"
    return _combo5_pre("sob demanda", body)


def _handle_scorecard(args: str) -> str:
    from lib.kronos_config import apply_v31_defaults
    from lib.kronos_tracker import (
        format_daily_report_telegram,
        format_scorecard_telegram,
        init_kronos_tables,
        score_mature_predictions,
    )

    apply_v31_defaults()
    init_kronos_tables()

    warn = ""
    new_trades: list = []
    try:
        new_trades = score_mature_predictions()
    except Exception as exc:
        logger.exception("scorecard: %s", exc)
        warn = f"\n\n⚠️ Não foi possível fechar trades pendentes agora: {exc}\n<i>Mostrando catálogo já gravado.</i>"

    sub = args.strip().lower()
    try:
        if sub in ("diario", "daily", "ranking", "relatorio", "relatório"):
            body = format_daily_report_telegram()
        else:
            short_closed = [t for t in new_trades if t.get("horizon") == "short"]
            body = format_scorecard_telegram(new_trades=short_closed if short_closed else None)
        return body + warn
    except Exception as exc:
        logger.exception("scorecard format: %s", exc)
        return f"⚠️ Erro ao montar scorecard: {exc}{warn}"


def _handle_reset_scorecard() -> str:
    from lib.kronos_config import apply_kronos_defaults, active_config, RULES_VERSION
    from lib.kronos_rules_stamp import ensure_catalog_for_current_rules

    apply_kronos_defaults()
    os.environ["KRONOS_FORCE_CATALOG_RESET"] = "1"
    did, deleted = ensure_catalog_for_current_rules(notify=False)
    c = active_config()
    if did:
        return (
            f"✅ <b>Scorecard resetado</b> — {deleted} registros apagados.\n"
            f"Regras <b>v{RULES_VERSION}</b> · {c['leverage']}x · alvo≥{c['min_target']}% · "
            f"stop {c['stop_4h']}% · só {c['score_tickers']}.\n"
            f"<i>Próximas entradas 4H alinhadas entram no catálogo limpo.</i>"
        )
    return f"✅ Catálogo já estava limpo para v{RULES_VERSION}."


def _handle_vps(args: str) -> str:
    from lib import vps_config
    from vps.hetzner_remote import sync_and_test

    sub = args.strip().lower()
    if sub in ("", "status", "info"):
        return vps_config.status_text()
    if sub in ("test", "sync", "check"):
        return sync_and_test()
    ip = args.strip().split()[0]
    try:
        vps_config.set_host(ip)
    except ValueError as exc:
        return f"⚠️ {exc}\nUso: <code>/vps 95.xxx.xxx.xxx</code> ou <code>/vps test</code>"
    return sync_and_test(ip)


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

        api = _llmquant_status_line(verify=True)
        thresh = os.environ.get("QUANT_IMPACT_THRESHOLD", "0.70")
        alerts = (
            f"⚡ Alertas fortes: <b>ON</b> (≥{thresh})"
            if impact_alerts_enabled()
            else "Alertas fortes: off (só digest 1H)"
        )
        return (
            f"<b>QUANT online</b>\n{api}\n{alerts}\n"
            f"Modo Kronos: <code>{os.environ.get('QUANT_KRONOS_MODE', 'warn')}</code>\n"
            f"COMBO5: <code>/combo5</code> · <code>/combo5 ranking</code> · <code>/c5score</code>\n"
            f"MEXC: <code>/mexc</code>"
        )
    if cmd in ("/quant", "/contexto"):
        return _handle_context()
    if cmd in ("/combo5", "/analise", "/análise", "/c5"):
        return _handle_combo5(rest)
    if cmd in ("/c5score", "/combo5ranking", "/c5ranking"):
        return _handle_combo5_ranking()
    if cmd in ("/mexc", "/mexcanálise", "/mexc_analise"):
        return _handle_mexc(rest)
    if cmd in ("/pesquisa", "/research", "/p"):
        if not rest:
            return "Uso: <code>/pesquisa momentum em crypto</code>"
        answer = quant_research.research(rest)
        state = quant_state.load()
        quant_state.set_last_research(state, rest, answer)
        quant_state.save(state)
        return quant_research.format_for_telegram(rest, answer)
    if cmd in ("/btc", "/eth", "/sol"):
        return _handle_snapshot(cmd[1:].upper())
    if cmd in ("/scorecard", "/score", "/acerto"):
        return _handle_scorecard(rest)
    if cmd in ("/resetscorecard", "/resetcatalogo", "/reset"):
        return _handle_reset_scorecard()
    if cmd in ("/vps", "/hetzner", "/btccursor"):
        return _handle_vps(rest)
    return _help_text()


def _process_update(upd: dict) -> None:
    msg = upd.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    if chat_id != _allowed_chat() or not text.startswith("/"):
        return

    logger.info("Comando: %s", text[:80])
    cmd, _, rest = text.strip().partition(" ")
    cmd = cmd.split("@")[0].lower()
    rest = rest.strip()
    if cmd in ("/scorecard", "/score", "/acerto"):
        send_quant_reply(
            chat_id,
            "⏳ Calculando scorecard Kronos (consulta MEXC + catálogo)…",
        )
    elif cmd in ("/combo5", "/analise", "/análise", "/c5"):
        if _combo5_ranking_request(rest):
            send_quant_reply(chat_id, "⏳ Montando ranking COMBO5…")
        else:
            send_quant_reply(
                chat_id,
                "⏳ Analisando COMBO5 ao vivo (candles MEXC + Kronos 3TF)…",
            )
    elif cmd in ("/c5score", "/combo5ranking", "/c5ranking"):
        send_quant_reply(chat_id, "⏳ Montando ranking COMBO5…")
    elif cmd in ("/mexc", "/mexcanálise", "/mexc_analise"):
        send_quant_reply(
            chat_id,
            "⏳ Consultando MEXC spot + futuros (retry se a API atrasar)…",
        )
    elif cmd in ("/vps", "/hetzner", "/btccursor"):
        if rest.lower() in ("test", "sync", "check") or (
            rest and rest.split()[0][0].isdigit()
        ):
            send_quant_reply(chat_id, "⏳ Hetzner: desligando Kronos duplicado e verificando…")
    reply = _dispatch(text)
    if not send_quant_reply(chat_id, reply):
        send_quant_reply(
            chat_id,
            "⚠️ Falha ao enviar resposta. Tente de novo em alguns segundos.",
            parse_mode=None,
        )


class _WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        logger.info("webhook " + fmt, *args)

    def _send(self, code: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in {"/", "/health", "/healthz"}:
            self._send(200, b"quant-bot ok\n")
            return
        self._send(404, b"not found\n")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/telegram":
            self._send(404, b"not found\n")
            return
        got = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != _webhook_secret():
            logger.warning("webhook: secret_token inválido")
            self._send(403, b"forbidden\n")
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, b"bad json\n")
            return
        threading.Thread(target=_process_update, args=(payload,), daemon=True).start()
        self._send(200, b"ok")


def _start_http(port: int) -> ThreadingHTTPServer | None:
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _WebhookHandler)
    except OSError as exc:
        logger.warning("HTTP porta %s ocupada: %s", port, exc)
        return None
    thread = threading.Thread(target=server.serve_forever, name="quant-http", daemon=True)
    thread.start()
    logger.info("HTTP quant_bot em 0.0.0.0:%s (/health, /telegram)", port)
    return server


def _resolve_webhook_url() -> str:
    mode = _bot_mode()
    if mode == "poll":
        return ""
    url = webhook_public_url()
    if url:
        return url
    if mode != "webhook" and not os.environ.get("RAILWAY_ENVIRONMENT"):
        return ""
    for i in range(3):
        url = webhook_public_url()
        if url:
            return url
        logger.info("Aguardando RAILWAY_PUBLIC_DOMAIN (%s/3)…", i + 1)
        time.sleep(5)
    return webhook_public_url()


def run() -> None:
    port = _listen_port()

    if not _enabled():
        logger.info("QUANT_BOT_ENABLED=0 — Telegram off; /health se PORT")
        if port:
            _start_http(port)
            while True:
                time.sleep(3600)
        return

    if not _bot_token() or not _allowed_chat():
        logger.error("TELEGRAM_BOT_TOKEN/CHAT_ID ausentes")
        if port:
            _start_http(port)
            while True:
                time.sleep(3600)
        raise RuntimeError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID obrigatórios")

    if not _acquire_singleton():
        return

    logger.info("QUANT bot ativo (chat %s)", _allowed_chat())
    http = _start_http(port) if port else None
    webhook_url = _resolve_webhook_url()

    if webhook_url:
        try:
            _ensure_webhook(webhook_url)
            logger.info("Modo webhook — Hetzner getUpdates recebe 409 (esperado)")
            if http is None:
                raise RuntimeError("webhook exige HTTP (defina PORT)")
            while True:
                time.sleep(3600)
        except Exception as exc:
            logger.exception("webhook falhou (%s) — caindo para polling", exc)
            if http is None and port:
                http = _start_http(port)

    _ensure_polling()
    offset = _load_offset()

    while True:
        try:
            data = _api("getUpdates", offset=offset, timeout=30, allowed_updates=["message"])
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                _process_update(upd)
            _save_offset(offset)
        except TelegramConflict as exc:
            logger.warning("%s — tenta webhook, senão retry 20s", exc)
            url = webhook_public_url()
            if url:
                try:
                    if http is None and port:
                        http = _start_http(port)
                    _ensure_webhook(url)
                    logger.info("Passou a webhook após 409: %s", url)
                    while True:
                        time.sleep(3600)
                except Exception as hook_exc:
                    logger.warning("webhook após 409 falhou: %s", hook_exc)
            time.sleep(20)
            continue
        except Exception as exc:
            logger.exception("quant_bot loop: %s", exc)
            time.sleep(5)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
