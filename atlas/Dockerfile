FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY migrations/alembic.ini ./alembic.ini

RUN pip install --upgrade pip && pip install -e ".[dev]"

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["bash", "-c", "alembic -c alembic.ini upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
