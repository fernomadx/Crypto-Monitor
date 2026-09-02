#!/usr/bin/env python3
"""
Bot QUANT — pesquisa sob demanda no Telegram.

Comandos (só responde TELEGRAM_CHAT_ID autorizado):
  /quant, /contexto     — estado atual (notícias de impacto)
  /pesquisa <pergunta>  — consulta LLMQuant + Haiku
  /combo5, /analise     — análise COMBO5 ao vivo (fora do cron)
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
# Telegram segura getUpdates até `timeout` segundos; o HTTP precisa ser maior, senão
# o requests estoura ReadTimeout no mesmo instante e o log explode (centenas de MB).
GET_UPDATES_LONG_POLL_SEC = int(os.environ.get("QUANT_BOT_LONG_POLL_SEC", "25"))
_singleton_fp = None
