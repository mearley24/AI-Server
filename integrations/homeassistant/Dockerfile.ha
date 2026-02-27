# Symphony Smart Homes — HA Integration Service
# Docker image for Bob's Home Assistant bridge running on Mac Mini M4

FROM python:3.11-slim

LABEL maintainer="Symphony Smart Homes"
LABEL description="Home Assistant integration for Bob the Conductor"
LABEL version="1.0.0"

# Install system dependencies (for asyncio-mqtt and SSL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy integration modules
COPY ha_bridge.py .
COPY ha_mqtt_agent.py .
COPY ha_camera_monitor.py .
COPY ha_automations.py .
COPY ha_device_registry.py .
COPY ha_config.json .
COPY openclaw_ha_tool.json .

# Create runtime directories
RUN mkdir -p /app/logs /app/cache /data/snapshots

# Default: run the HA bridge smoke test
# Override CMD in docker-compose to run specific services
CMD ["python", "ha_bridge.py"]

# Healthcheck: verify HA connectivity
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; \
        req = urllib.request.Request(os.environ.get('HA_URL','http://localhost:8123') + '/api/', \
        headers={'Authorization': 'Bearer ' + os.environ.get('HA_TOKEN','')}); \
        urllib.request.urlopen(req, timeout=5); print('ok')" \
    || exit 1
