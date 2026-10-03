# Kruvim API + worker image
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl tini && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade "pip>=26.2.1" && pip install -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 kruvim && mkdir -p /data && chown -R kruvim:kruvim /data /app && chmod +x docker-entrypoint.sh
USER kruvim
ENV KRUVIM_DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fsS http://localhost:8000/healthz || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "./docker-entrypoint.sh"]
CMD ["api"]
