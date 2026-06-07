FROM python:3.12-slim

# Install supercronic (lightweight cron for containers)
ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    SUPERCRONIC=/usr/local/bin/supercronic \
    SUPERCRONIC_SHA1SUM=cd48d45c4b10f3f0bfdd3a57d054cd05ac96812b

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git \
    && curl -fsSL "$SUPERCRONIC_URL" -o "$SUPERCRONIC" \
    && echo "$SUPERCRONIC_SHA1SUM  $SUPERCRONIC" | sha1sum -c - \
    && chmod +x "$SUPERCRONIC" \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kronos (mesmo container = mesmas TELEGRAM_* e TICKERS do Railway)
COPY vps/requirements-railway.txt vps/requirements-railway.txt
RUN pip install --no-cache-dir -r vps/requirements-railway.txt
RUN git clone --depth 1 https://github.com/shiyu-coder/Kronos.git /app/Kronos

COPY . .

ENV KRONOS_PATH=/app/Kronos \
    KRONOS_DEVICE=cpu \
    KRONOS_MODEL=NeoQuasar/Kronos-mini \
    KRONOS_TOKENIZER=NeoQuasar/Kronos-Tokenizer-2k \
    KRONOS_MAX_CONTEXT=2048 \
    KRONOS_TIMEFRAMES=1h,4h,1d \
    KRONOS_SAMPLE_COUNT=4 \
    KRONOS_INITIAL_CAPITAL=1000 \
    KRONOS_POSITION_USDC=100 \
    KRONOS_LEVERAGE=10 \
    KRONOS_SCORE_INTERVAL=4h \
    KRONOS_MIN_TF_AGREEMENT=3 \
    KRONOS_FEE_MAKER_PCT=0.02 \
    KRONOS_FEE_TAKER_PCT=0.05 \
    KRONOS_LIMIT_ENTRY_BARS=6 \
    KRONOS_LIMIT_ENTRY_OFFSET_PCT=0.15 \
    KRONOS_BIAS_BARS=4 \
    KRONOS_TARGET_BARS=8 \
    KRONOS_TEMPERATURE=0.65 \
    KRONOS_BIAS_THRESHOLD_PCT=0.30 \
    KRONOS_MIN_TARGET_PCT=0.5 \
    KRONOS_MIN_RR=2.0 \
    KRONOS_MAX_STOP_PCT_4H=1.8 \
    KRONOS_MAX_STOP_PCT=1.5 \
    KRONOS_CHART_DIR=/data/kronos/charts \
    HF_HOME=/data/huggingface \
    TRANSFORMERS_CACHE=/data/huggingface \
    QUANT_KRONOS_MODE=warn \
    QUANT_STATE_PATH=/data/quant_state.json \
    QUANT_IMPACT_THRESHOLD=0.65 \
    QUANT_MAX_AGE_HOURS=4 \
    QUANT_POLL_MINUTES=5 \
    QUANT_DISPLAY_TZ=Europe/Dublin

RUN mkdir -p /data /data/kronos/charts /data/huggingface \
    && chmod +x /app/vps/railway_boot.sh /app/vps/kronos_run.sh /app/vps/ensure_quant_bot.sh \
    /app/vps/quant_bot.py /app/vps/quant_watcher.py /app/vps/quant_hourly_news.py 2>/dev/null || true

# supercronic + boot Kronos (1ª execução após deploy)
CMD ["/bin/sh", "-c", "/app/vps/railway_boot.sh & exec supercronic /app/crontab"]
