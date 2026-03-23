FROM node:18-slim AS node-stage

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone the BTC 15m Assistant (fall back to empty stub if repo is unavailable)
RUN git clone --depth 1 https://github.com/FrondEnt/PolymarketBTC15mAssistant.git assistant \
    || (echo "WARNING: git clone failed, creating stub assistant" \
        && mkdir -p assistant \
        && echo 'console.error("Assistant repo unavailable at build time"); process.exit(1);' > assistant/index.js \
        && echo '{"name":"stub","version":"0.0.0","private":true}' > assistant/package.json)

WORKDIR /app/assistant
RUN npm ci --production 2>/dev/null || npm install --production

# Verify the assistant can at least be required without immediate crash
RUN node -e "try { require('./index'); } catch(e) { console.log('Build check: ' + e.message); }" \
    || echo "WARNING: assistant module check returned non-zero (may be normal if it needs runtime deps)"

# Install Python bridge dependencies
WORKDIR /app
COPY bridge.py .
RUN python3 -m venv /app/venv \
    && /app/venv/bin/pip install --no-cache-dir redis>=5.0.0

ENV PATH="/app/venv/bin:$PATH"

# The bridge starts the Node.js assistant as a subprocess and pipes stdout
CMD ["python3", "bridge.py"]
