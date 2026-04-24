FROM python:3.11-slim
WORKDIR /app

# Install dependencies first (better layer caching)
COPY cortex/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy cortex package (engine, memory, goals, dashboard, static UI, ...)
COPY cortex/ /app/cortex/
COPY scripts/ /app/scripts/

# Copy source files for migration (mounted read-only at runtime, but baked in as fallback)
COPY AGENT_LEARNINGS.md /app/AGENT_LEARNINGS.md
COPY polymarket-bot/ideas.txt /app/ideas.txt

# Knowledge dir is mounted at runtime via volume — skip baking in
# (see docker-compose.yml: ./polymarket-bot/knowledge:/app/knowledge:ro)

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "cortex.engine"]
