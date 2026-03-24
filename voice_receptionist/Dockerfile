FROM node:20-alpine

WORKDIR /app

# Native build deps for better-sqlite3
RUN apk add --no-cache python3 make g++

# Install dependencies
COPY package.json ./
RUN npm install --omit=dev

# Copy source
COPY . .

# Create data directory
RUN mkdir -p /app/data

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1

CMD ["node", "--unhandled-rejections=throw", "server.js"]
