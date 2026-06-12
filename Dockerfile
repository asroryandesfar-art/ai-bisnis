# BotNesia + Intelligence Platform — image produksi
# Dipakai untuk service: agent_api, celery-worker, celery-beat (lihat docker-compose.yml)

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependensi sistem minimal untuk asyncpg/numpy/cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8001

# Default: jalankan agent_api. docker-compose meng-override `command`
# untuk service celery-worker & celery-beat.
CMD ["uvicorn", "agent_api:app", "--host", "0.0.0.0", "--port", "8001"]
