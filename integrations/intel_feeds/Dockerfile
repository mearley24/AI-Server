# Intel Feeds — Trading Intelligence Gathering Layer
# Python 3.12-slim base for minimal footprint
# ------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="intel_feeds" \
      org.opencontainers.image.description="Trading intelligence gathering layer for Polymarket bot" \
      org.opencontainers.image.version="1.0.0"

# ---- System dependencies -------------------------------------------------
# curl for healthcheck, ca-certificates for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Python dependencies --------------------------------------------------
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- Application code ------------------------------------------------------
# Copy the entire integrations package
COPY . ./integrations/intel_feeds/

# Ensure the data directory exists (SQLite DB lives here)
# In production this should be a mounted volume: -v /host/data:/data
RUN mkdir -p /data/intel_feeds

# ---- Runtime configuration -----------------------------------------------
# All values can be overridden via -e flags or docker-compose environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REDIS_URL="redis://172.18.0.100:6379" \
    INTEL_HEALTH_PORT=8765 \
    REDDIT_POLL_SEC=900 \
    NEWS_POLL_SEC=600 \
    POLYMARKET_POLL_SEC=300 \
    LOG_LEVEL=INFO

# ---- Healthcheck -----------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:${INTEL_HEALTH_PORT}/health | grep -q '"status": "ok"' || exit 1

# ---- Ports -----------------------------------------------------------------
# Health check / query API
EXPOSE ${INTEL_HEALTH_PORT}

# ---- Entrypoint ------------------------------------------------------------
CMD ["python", "-m", "integrations.intel_feeds.runner"]
