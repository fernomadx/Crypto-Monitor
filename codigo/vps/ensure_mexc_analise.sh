#!/bin/sh
# Watchdog do daemon 📊 MEXC Análise (poll 15s).
# Detecta via /proc (python:slim não tem pgrep; ps também pode faltar).
# Restart do cron é silencioso — "Bot iniciado" só no boot (MEXC_ANALISE_NOTIFY=1).
set -eu

if [ "${MEXC_ANALISE_BOT:-1}" = "0" ] || [ "${MEXC_ANALISE_BOT:-1}" = "false" ]; then
  exit 0
fi

BOT="${BOT:-/app/vps/mexc_analise_bot.py}"
if [ ! -f "$BOT" ]; then
  BOT="$(cd "$(dirname "$0")/.." && pwd)/vps/mexc_analise_bot.py"
fi

STATE_DIR="${MEXC_ANALISE_STATE:-/data/mexc_analise}"
LOG="${MEXC_ANALISE_LOG:-/data/mexc_analise.log}"
PIDFILE="${MEXC_ANALISE_PIDFILE:-$STATE_DIR/bot.pid}"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"

list_pids() {
  for dir in /proc/[0-9]*; do
    [ -r "$dir/cmdline" ] || continue
    cmd=$(tr '\0' ' ' < "$dir/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *mexc_analise_bot.py*) echo "${dir#/proc/}" ;;
    esac
  done
}

pids=$(list_pids | tr '\n' ' ')
n=0
for _ in $pids; do n=$((n + 1)); done

if [ "$n" -gt 1 ]; then
  echo "ensure_mexc_analise: $n instâncias — reiniciando uma só"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  sleep 2
  n=0
elif [ "$n" -eq 1 ]; then
  echo "$pids" > "$PIDFILE"
  echo "ensure_mexc_analise: já rodando pid $pids"
  exit 0
fi

# Cron/watchdog default silencioso; container_start exporta NOTIFY=1 uma vez.
export MEXC_ANALISE_NOTIFY="${MEXC_ANALISE_NOTIFY:-0}"
PYTHON="${PYTHON:-python}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python3
fi
nohup "$PYTHON" "$BOT" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "ensure_mexc_analise: iniciado pid $! notify=$MEXC_ANALISE_NOTIFY"
