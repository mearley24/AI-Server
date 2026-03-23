# Polymarket Trading Bot

Automated trading bot for Polymarket prediction markets, integrated into the AI-Server stack.

## Architecture

- **FastAPI service** on port 8430
- **Polymarket CLOB API** for order placement (limit orders, FOK)
- **Gamma API** for market discovery
- **WebSocket** for real-time orderbook monitoring
- **EIP-712** order signing on Polygon
- **Signal Bus** — async pub/sub routing signals between components
- **Binance Latency Detector** — spots pricing lag between Binance BTC spot and Polymarket contracts
- **Redis** — receives TA signals from the BTC 15m Assistant sidecar
- **Debate Engine** — bull/bear/judge AI validation before large trades

## Data Flow

```
Binance WS → Latency Detector → Signal Bus → Strategies
BTC 15m Assistant → Redis → Signal Bus → Strategies
Strategy Decision → Debate Engine → Execute or Reject
```

## Strategies

### Stink Bid
Places low-ball limit buy orders on 5m/15m crypto markets (BTC, ETH, SOL). Catches flash dips on high-leverage short-term markets. Managed with configurable take-profit and stop-loss.

### Flash Crash
Monitors orderbook via WebSocket. When a token's price drops >= threshold within a short window (default: 0.30 in 10 seconds), buys the crashed side expecting mean reversion.

### Weather Trader
Uses NOAA National Weather Service forecasts to trade temperature bracket markets on Polymarket. Compares forecast probability distributions against bracket pricing, buying when Polymarket significantly underprices a bracket (default: 10% edge). Conservative sizing ($5-$10), slower-moving markets — beginner-friendly.

## Components

### Latency Detector
Opens a WebSocket to Binance for real-time BTC/USDT spot price. When Binance shows directional momentum but Polymarket 5m/15m contracts haven't repriced within the lag threshold, emits signals to the signal bus for strategies to act on.

### Signal Bus
Async pub/sub tying the latency detector, TA sidecar signals, and strategies together. Components publish and subscribe to typed signals without direct coupling.

### BTC 15m Assistant Sidecar
Docker container running [FrondEnt/PolymarketBTC15mAssistant](https://github.com/FrondEnt/PolymarketBTC15mAssistant) with a Python bridge that parses TA output (RSI, MACD, Heikin Ashi, VWAP, delta, prediction) and publishes structured signals to Redis for the main bot.

### Debate Engine
Before executing trades above a configurable threshold ($25 default), runs a bull/bear/judge debate using the Claude API. The bull agent argues for the trade, the bear argues against, and a judge evaluates both sides, returning a confidence score. Trades below the confidence threshold are rejected.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Bot status, wallet, active strategies |
| GET | `/positions` | Open positions across all strategies |
| GET | `/strategies` | Available strategies and configs |
| GET | `/pnl?keyword=bitcoin&hours=72` | Filtered P&L |
| GET | `/markets` | Currently scanned markets |
| POST | `/start` | Start a strategy (`{"strategy": "stink_bid"}`) |
| POST | `/stop` | Stop a strategy (`{"strategy": "stink_bid"}`) |

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POLY_PRIVATE_KEY` | Yes | — | Wallet private key (64 hex chars, no 0x) |
| `POLY_SAFE_ADDRESS` | Yes | — | Polymarket Safe address |
| `POLY_BUILDER_API_KEY` | No | — | Builder Program API key (gasless) |
| `POLY_BUILDER_API_SECRET` | No | — | Builder Program API secret |
| `POLY_BUILDER_API_PASSPHRASE` | No | — | Builder Program passphrase |
| `POLY_DEFAULT_SIZE` | No | 10.0 | Default position size (USDC) |
| `POLY_MAX_EXPOSURE` | No | 100.0 | Max portfolio exposure (USDC) |
| `POLY_LOG_LEVEL` | No | info | Log level |
| `ANTHROPIC_API_KEY` | No | — | Required for debate engine |
| `REDIS_URL` | No | redis://redis:6379 | Redis URL for TA sidecar signals |

### YAML Config (optional)

Copy `config.example.yaml` to `config.yaml` for strategy-specific overrides. See the example file for all available options including weather trader, latency detector, and debate engine settings.

## Running

### Docker (recommended)

```bash
# Start all services (bot + Redis + BTC 15m Assistant sidecar)
docker compose up polymarket-bot btc-15m-assistant redis
```

### Local

```bash
cd polymarket-bot
pip install -r requirements.txt
python -m src.main
```

## Safety

- Default position size: $10 USDC
- Max exposure: $100 USDC
- All strategies have configurable stop-losses
- Orders are signed locally (private key never leaves the machine)
- Debate engine validates large trades ($25+) with AI bull/bear analysis
- Weather trader uses conservative $5-$10 sizing
