#!/usr/bin/env python3
"""
Daemon Kronos — modelo ML sempre em memória, dispara no fechamento do candle.

Evita recarregar o modelo a cada hora (15–40 min de atraso). Com o daemon,
o texto da previsão sai ~1–3 min após o candle fechar; o gráfico vem em seguida.
"""

from __future__ import annotations

import fcntl
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.kronos_config import RULES_VERSION, apply_v31_defaults, format_config_footer  # noqa: E402
from lib.kronos_schedule import CANDLE_DELAY_SEC, format_next_candle_line, next_wake_time  # noqa: E402

apply_v31_defaults()

from lib.telegram import send_kronos_alert  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "vps"))
from kronos_signal import CandleNotReadyError, execute_run, load_predictor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [daemon] %(message)s",
)
logger = logging.getLogger(__name__)

MAX_RETRIES = int(os.environ.get("KRONOS_CANDLE_MAX_RETRIES", "12"))
RETRY_SLEEP_SEC = int(os.environ.get("KRONOS_CANDLE_RETRY_SEC", "5"))
DAEMON_LOCK = Path(os.environ.get("KRONOS_DAEMON_LOCK", "/data/kronos_daemon.lock"))
_singleton_fp = None


def _acquire_singleton() -> bool:
    """Uma instância do daemon por container."""
    global _singleton_fp
    DAEMON_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fp = open(DAEMON_LOCK, "w")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fp.close()
        logger.warning("outro kronos_daemon já ativo — saindo")
        return False
    fp.write(str(os.getpid()))
    fp.flush()
    _singleton_fp = fp
    return True


def _should_notify_boot() -> bool:
    """Telegram só no boot do container, não em restart do watchdog."""
    return os.environ.get("KRONOS_DAEMON_NOTIFY", "0").lower() in ("1", "true", "yes", "on")


def sleep_until(target: datetime) -> None:
    while True:
        now = datetime.now(timezone.utc)
        sec = (target - now).total_seconds()
        if sec <= 0:
            return
        time.sleep(min(sec, 30))


def close_hour_for_wake(wake_at: datetime) -> int:
    return wake_at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).hour


def run_tf(predictor, tf: str, wake_at: datetime) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            execute_run(
                predictor,
                tf,
                candle_wake_at=wake_at,
                text_before_chart=True,
            )
            return
        except CandleNotReadyError as exc:
            logger.warning("%s tentativa %d/%d: %s", tf.upper(), attempt, MAX_RETRIES, exc)
            if attempt >= MAX_RETRIES:
                send_kronos_alert(
                    f"Candle {tf.upper()} atrasado",
                    f"MEXC não publicou o candle fechado após {MAX_RETRIES} tentativas.\n"
                    f"<i>{exc}</i>",
                )
                raise
            time.sleep(RETRY_SLEEP_SEC)


def on_candle_close(predictor, wake_at: datetime) -> None:
    hour = close_hour_for_wake(wake_at)
    logger.info("Fechamento candle %02d:00 UTC — disparando 1H", hour)
    run_tf(predictor, "1h", wake_at)

    if hour % 4 == 0:
        logger.info("Fechamento candle 4H — disparando 4H")
        run_tf(predictor, "4h", wake_at)

    if hour == 0:
        logger.info("Fechamento candle Diário — disparando 1D")
        run_tf(predictor, "1d", wake_at)


def main() -> None:
    if not _acquire_singleton():
        return

    logger.info("Daemon Kronos v%s iniciando", RULES_VERSION)
    predictor = load_predictor()
    now_utc = datetime.now(timezone.utc)
    if _should_notify_boot():
        send_kronos_alert(
            "Modelo pronto",
            f"<b>Daemon ativo</b> — alertas no fechamento do candle.\n"
            f"{format_next_candle_line(now_utc)}\n"
            f"1H horário · 4H em 0/4/8/12/16/20 · Diário à meia-noite\n"
            f"<i>Texto da previsão antes do gráfico (~1–3 min após fechar).</i>\n"
            f"{format_config_footer()}",
        )
    else:
        logger.info("Daemon reiniciado (sem Telegram — KRONOS_DAEMON_NOTIFY=0)")

    while True:
        wake_at = next_wake_time(datetime.now(timezone.utc))
        close_at = wake_at - timedelta(seconds=CANDLE_DELAY_SEC)
        logger.info(
            "Aguardando fechamento candle %s UTC → wake %s",
            close_at.strftime("%Y-%m-%d %H:%M"),
            wake_at.strftime("%H:%M:%S"),
        )
        sleep_until(wake_at)
        try:
            on_candle_close(predictor, wake_at)
            err_stamp = Path(os.environ.get("KRONOS_LAST_ERROR_STAMP", "/data/kronos_last_error.txt"))
            if err_stamp.exists():
                err_stamp.unlink(missing_ok=True)
        except Exception as exc:
            logger.exception("Erro no ciclo %s: %s", wake_at, exc)
            err_stamp = Path(os.environ.get("KRONOS_LAST_ERROR_STAMP", "/data/kronos_last_error.txt"))
            err_msg = str(exc)[:500]
            last_msg = err_stamp.read_text().strip() if err_stamp.exists() else ""
            # Evita spam do mesmo erro a cada hora
            if err_msg != last_msg:
                try:
                    send_kronos_alert("Erro daemon", err_msg)
                    err_stamp.parent.mkdir(parents=True, exist_ok=True)
                    err_stamp.write_text(err_msg)
                except Exception:
                    pass
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("daemon abortado: %s", exc)
        try:
            send_kronos_alert("Daemon parou", str(exc)[:500])
        except Exception:
            pass
        sys.exit(1)
