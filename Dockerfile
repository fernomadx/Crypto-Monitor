FROM python:3.12-slim

# crypto-monitor apenas (Kronos = Hetzner BTCCURSOR, ver Dockerfile.kronos / vps/BTCCURSOR.md)

ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    SUPERCRONIC=/usr/local/bin/supercronic \
    SUPERCRONIC_SHA1SUM=cd48d45c4b10f3f0bfdd3a57d054cd05ac96812b

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "$SUPERCRONIC_URL" -o "$SUPERCRONIC" \
    && echo "$SUPERCRONIC_SHA1SUM  $SUPERCRONIC" | sha1sum -c - \
    && chmod +x "$SUPERCRONIC" \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

CMD ["supercronic", "/app/crontab"]
