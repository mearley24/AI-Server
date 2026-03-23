# Polymarket Trading Bot

Automated trading bot for Polymarket prediction markets, integrated into the AI-Server stack.

## Architecture

- **FastAPI service** on port 8430
- **Polymarket CLOB API** for order placement (limit orders, FOK)
- **Gamma API** for market discovery
- **WebSocket** for real-time orderbook monitoring
- **EIP-712** order signing on Polygon

## Strategies

### Stink Bid
Places low-ball limit buy orders on 5m/15m crypto markets (BTC, ETH, SOL). Catches flash dips on high-leverage short-term markets. Managed with configurable take-profit and stop-loss.

### Flash Crash
Monitors orderbook via WebSocket. When a token's price drops >= threshold within a short window (default: 0.30 in 10 seconds), buys the crashed side expecting mean reversion.

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

### YAML Config (optional)

Copy `config.example.yaml` to `config.yaml` for strategy-specific overrides.

## Running

### Docker (recommended)

```bash
docker compose up polymarket-bot
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
