# BTC 15m Assistant Sidecar

Docker sidecar that runs [FrondEnt/PolymarketBTC15mAssistant](https://github.com/FrondEnt/PolymarketBTC15mAssistant) and bridges its TA signal output to Redis for consumption by the main Polymarket trading bot.

## Architecture

```
┌─────────────────────────┐     ┌─────────┐     ┌──────────────────┐
│ BTC 15m Assistant (Node) │────▶│ bridge.py│────▶│ Redis pub/sub    │
│ RSI, MACD, VWAP, HA,    │     │ (Python) │     │ polymarket:ta_   │
│ delta, prediction        │     └─────────┘     │ signals channel  │
└─────────────────────────┘                      └────────┬─────────┘
                                                          │
                                                 ┌────────▼─────────┐
                                                 │ Polymarket Bot   │
                                                 │ Signal Bus       │
                                                 └──────────────────┘
```

## How It Works

1. The Dockerfile clones the BTC 15m Assistant repo and installs its Node.js dependencies.
2. `bridge.py` starts the assistant as a subprocess.
3. The assistant outputs TA data as JSON lines to stdout.
4. The bridge parses each line and publishes structured signals to the `polymarket:ta_signals` Redis channel.
5. The main bot's signal bus subscribes to this Redis channel and routes TA signals to strategies.

## Signal Format

```json
{
  "source": "btc_15m_assistant",
  "timestamp": 1711234567.89,
  "rsi": 45.2,
  "macd": 0.003,
  "heikin_ashi": "bullish",
  "vwap": 63210.5,
  "delta": 120.3,
  "prediction": "up",
  "confidence": 0.72
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `POLYMARKET_AUTO_SELECT_LATEST` | `true` | Auto-select the latest BTC market |

## Running Standalone

```bash
docker build -t btc-15m-assistant .
docker run --rm -e REDIS_URL=redis://host.docker.internal:6379 btc-15m-assistant
```

## Running with Docker Compose

The sidecar is included in the project's `docker-compose.yml` and starts automatically alongside the main bot and Redis.
