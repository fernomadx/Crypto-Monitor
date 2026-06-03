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
    KRONOS_CHART_DIR=/data/kronos/charts \
    HF_HOME=/data/huggingface \
    TRANSFORMERS_CACHE=/data/huggingface

RUN mkdir -p /data /data/kronos/charts /data/huggingface \
    && chmod +x /app/vps/railway_boot.sh 2>/dev/null || true

# supercronic + boot Kronos (1ª execução após deploy)
CMD ["/bin/sh", "-c", "/app/vps/railway_boot.sh & exec supercronic /app/crontab"]
