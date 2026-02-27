# =============================================================================
# OpenClaw Dockerfile
# Service: Multi-agent orchestration (Bob's brain)
# Target:  Mac Mini M4 — linux/arm64
# =============================================================================

FROM python:3.12-slim AS base

# Labels
LABEL org.opencontainers.image.title="OpenClaw"
LABEL org.opencontainers.image.description="Multi-agent orchestration — OpenAI-compatible API"
LABEL com.symphony.role="orchestrator"

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create data directories
RUN mkdir -p /app/data/conversations /app/data/logs /app/agents

# Default port
ENV PORT=3000
ENV LOG_LEVEL=info
ENV AGENTS_DIR=/app/agents
ENV DATA_DIR=/app/data

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:3000/health || exit 1

CMD ["python", "main.py"]
