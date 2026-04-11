FROM python:3.12-slim

# Note: brctl (iCloud force-download) is a macOS-only binary and is NOT
# available in this container. Set IS_DOCKER=true in docker-compose.yml so
# the service skips brctl calls and logs a warning instead.
# iCloud and Dropbox folders are bind-mounted read-write.

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8102

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -sf http://127.0.0.1:8102/health || exit 1

CMD ["python", "main.py"]
