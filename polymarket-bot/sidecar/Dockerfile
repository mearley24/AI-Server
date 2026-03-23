FROM node:18-slim AS node-stage

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone the BTC 15m Assistant
RUN git clone --depth 1 https://github.com/FrondEnt/PolymarketBTC15mAssistant.git assistant

WORKDIR /app/assistant
RUN npm ci --production 2>/dev/null || npm install --production

# Install Python bridge dependencies
WORKDIR /app
COPY bridge.py .
RUN python3 -m venv /app/venv \
    && /app/venv/bin/pip install --no-cache-dir redis>=5.0.0

ENV PATH="/app/venv/bin:$PATH"

# The bridge starts the Node.js assistant as a subprocess and pipes stdout
CMD ["python3", "bridge.py"]
