# ─── Build stage ─────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Native build deps for better-sqlite3
RUN apk add --no-cache python3 make g++

# Install dependencies first (cache-friendly layer)
COPY package.json package-lock.json* ./
RUN npm install --omit=dev

# Copy source
COPY . .

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM node:20-alpine

WORKDIR /app

# better-sqlite3 native addon needs libstdc++ at runtime;
# su-exec for dropping privileges in the entrypoint
RUN apk add --no-cache libstdc++ su-exec

# Non-root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy built artifacts
COPY --from=builder /app /app

# Ensure data directory exists and app tree is owned by appuser
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

# Entrypoint fixes bind-mount permissions then drops to appuser
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node", "server.js"]
