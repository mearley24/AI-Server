# Polymarket Trading Bot

Automated trading bot for Polymarket prediction markets, integrated into the AI-Server stack.

## Observer Mode (Dry Run)

The bot defaults to **observer/dry-run mode** (`POLY_DRY_RUN=true`). In this mode it runs ALL subsystems — latency detector, market scanner, order flow analyzer, signal bus, debate engine, and all strategies — but instead of placing real orders, it logs **paper trades** to `/data/paper_trades.jsonl`.

A background scoring loop periodically checks the Gamma API for resolved markets and retroactively determines whether each paper trade would have been profitable. By the time you're ready to go live, you'll have weeks of data showing which strategies and signal combinations actually work.

### How it works

1. **All systems run normally** — signals fire, debates run, strategies decide to "trade"
2. **Orders are intercepted** — instead of hitting the Polymarket CLOB, trades are written to the paper ledger
3. **Retroactive scoring** — every hour (configurable), resolved markets are checked against paper trades
4. **P&L tracking** — `GET /paper-pnl` shows hypothetical profit/loss by strategy

### Switching to live

When your Polymarket account is funded and ready:

```bash
# Option 1: Environment variable
POLY_DRY_RUN=false

# Option 2: API endpoint (requires wallet to be configured)
curl -X POST http://localhost:8430/mode -H 'Content-Type: application/json' -d '{"mode": "live"}'
```

### API endpoints for observer mode

| Method | Path | Description |
|--------|------|-------------|
| GET | `/mode` | Current mode (`dry_run` or `live`) |
| POST | `/mode` | Switch mode (requires wallet for live) |
| GET | `/paper-trades` | Recent paper trades from ledger |
| GET | `/paper-pnl` | Hypothetical P&L from resolved markets |

## Architecture

- **FastAPI service** on port 8430
- **Polymarket CLOB API** for order placement (limit orders, FOK)
- **Gamma API** for market discovery
- **WebSocket** for real-time orderbook monitoring
- **EIP-712** order signing on Polygon
- **Signal Bus** — async pub/sub routing signals between components
- **Binance Latency Detector** — spots pricing lag between Binance BTC spot and Polymarket contracts
- **Order Flow Analyzer** — smart money signals from order book dynamics
- **Redis** — receives TA signals from the BTC 15m Assistant sidecar
- **Debate Engine** — bull/bear/judge AI validation before large trades
- **Security Sandbox** — trade limits, rate limiter, kill switch, audit trail
- **Encrypted Vault** — PBKDF2 + Fernet credential encryption at rest

## Data Flow

```
Binance WS → Latency Detector → Signal Bus → Strategies
Order Book → Order Flow Analyzer → Signal Bus → Strategies
BTC 15m Assistant → Redis → Signal Bus → Strategies
Strategy Decision → Debate Engine → Security Sandbox → Execute or Reject
```

## Strategies

### Stink Bid
Places low-ball limit buy orders on 5m/15m crypto markets (BTC, ETH, SOL). Catches flash dips on high-leverage short-term markets. Managed with configurable take-profit and stop-loss.

### Flash Crash
Monitors orderbook via WebSocket. When a token's price drops >= threshold within a short window (default: 0.30 in 10 seconds), buys the crashed side expecting mean reversion.

### Weather Trader (Enhanced)
Multi-source weather arbitrage using NOAA + AccuWeather forecasts. Enhanced 4-stage pipeline:
1. **SCAN** — Monitor 247+ active weather contracts (temperature, frost, precipitation, wind)
2. **DISCREPANCY** — Cross-reference NOAA + AccuWeather against Polymarket pricing
3. **FILTER** — Only trade when edge >= threshold, both sources agree, sufficient liquidity, and contract not expiring within 30 minutes
4. **EXECUTE** — Place order with take-profit at fair value and stop-loss at entry - 5%

Includes a **rare event scanner** targeting ultra-low-probability contracts (< 10%) where forecast data suggests higher probability — asymmetric 20x payoffs (inspired by the ColdMath wallet: $80K profit on rare weather events in Tokyo, Wellington, Ankara).

### Sports Arbitrage
Risk-free arbitrage on binary sports markets. Reverse-engineered from a wallet that made $619K in 12 months with 7,877 trades (~21/day, ~$79 avg profit/trade).

5-step loop:
1. **SCAN** — Poll Gamma API for active binary sports markets (NCAA, NBA, NFL, soccer, etc.)
2. **CHECK** — Identify arbitrage when combined YES (or NO) price < $0.98
3. **SIZE** — Compute position from available liquidity, max risk, and slippage tolerance
4. **EXECUTE** — Place simultaneous Fill-or-Kill orders on both sides
5. **SETTLE** — Collect $1/share payout on winning side, reinvest, repeat

## Components

### Order Flow Analyzer
Smart money signal detection from order book dynamics:
- **Order Book Imbalance** — bid/ask depth ratio skew detection
- **Liquidity Grab Detection** — stop hunt / wick reversal identification
- **Compression Detection** — Bollinger squeeze / ATR contraction (expansion precursor)
- **Volume Delta Tracking** — hidden accumulation/distribution via cumulative volume delta
- **Trapped Trader Detection** — failed breakout reversal signals

All signals publish to the existing Signal Bus for strategies to consume.

### Security Hardening

#### Encrypted Vault (`src/security/vault.py`)
- PBKDF2 (600,000 iterations) + Fernet (AES-128-CBC) encryption
- Encrypts all sensitive env vars at rest in `~/.polymarket-bot/vault.enc`
- File permissions locked to 0600 (owner read/write only)
- CLI: `python -m src.security.vault init` / `python -m src.security.vault rotate`
- Credentials never logged or printed in plaintext

#### Execution Sandbox (`src/security/sandbox.py`)
- **Trade limits**: Configurable max single trade, daily volume, daily loss — with hard-coded absolute ceilings ($50K/trade, $500K/day) that can't be overridden
- **Rate limiter**: Token bucket algorithm for orders/minute and API calls/minute
- **Kill switch**: Auto-triggers on daily loss breach or oversized trades; halts all strategies and cancels open orders
- **Approved endpoints whitelist**: Only Polymarket, NOAA, AccuWeather, and Binance allowed

#### Audit Trail (`src/security/audit.py`)
- Every trade decision logged with full context (strategy, market, side, size, price, debate result, signals)
- Every API call logged (endpoint, method, status code — no secrets)
- Rotating daily JSON-lines files with configurable retention (default 90 days)
- Queryable via `GET /audit?date=2026-03-23&strategy=sports_arb`

### Latency Detector
Opens a WebSocket to Binance for real-time BTC/USDT spot price. When Binance shows directional momentum but Polymarket 5m/15m contracts haven't repriced within the lag threshold, emits signals to the signal bus for strategies to act on.

### Signal Bus
Async pub/sub tying the latency detector, order flow analyzer, TA sidecar signals, and strategies together. Components publish and subscribe to typed signals without direct coupling.

### BTC 15m Assistant Sidecar
Docker container running [FrondEnt/PolymarketBTC15mAssistant](https://github.com/FrondEnt/PolymarketBTC15mAssistant) with a Python bridge that parses TA output (RSI, MACD, Heikin Ashi, VWAP, delta, prediction) and publishes structured signals to Redis for the main bot.

### Debate Engine
Before executing trades above a configurable threshold ($25 default), runs a bull/bear/judge debate using the Claude API. The bull agent argues for the trade, the bear argues against, and a judge evaluates both sides, returning a confidence score. Trades below the confidence threshold are rejected.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Bot status, wallet, active strategies |
| GET | `/mode` | Current operating mode (dry_run or live) |
| GET | `/positions` | Open positions across all strategies |
| GET | `/strategies` | Available strategies and configs |
| GET | `/pnl?keyword=bitcoin&hours=72` | Filtered P&L |
| GET | `/paper-trades` | Paper trade ledger (observer mode) |
| GET | `/paper-pnl` | Hypothetical P&L from resolved paper trades |
| GET | `/markets` | Currently scanned markets |
| GET | `/audit?date=2026-03-23&strategy=sports_arb` | Audit trail query |
| GET | `/audit/dates` | Available audit dates |
| GET | `/security/status` | Security sandbox status and kill switch |
| POST | `/start` | Start a strategy (`{"strategy": "sports_arb"}`) |
| POST | `/stop` | Stop a strategy (`{"strategy": "sports_arb"}`) |
| POST | `/mode` | Switch between dry_run and live mode |

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POLY_DRY_RUN` | No | true | Observer mode — no real orders, logs paper trades |
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
| `ACCUWEATHER_API_KEY` | No | — | AccuWeather API key (free tier: 50 calls/day) |
| `POLY_VAULT_PASSPHRASE` | No | — | Passphrase to decrypt the credential vault |

### YAML Config (optional)

Copy `config.example.yaml` to `config.yaml` for strategy-specific overrides. See the example file for all available options including weather trader, sports arb, order flow, security, latency detector, and debate engine settings.

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

# Optional: initialize the credential vault
python -m src.security.vault init

python -m src.main
```

## Safety

- Default position size: $10 USDC
- Max exposure: $100 USDC
- Hard-coded absolute ceilings: $50K/trade, $500K/day volume, $25K/day loss
- All strategies have configurable stop-losses
- Kill switch auto-triggers on loss threshold breach
- Orders are signed locally (private key never leaves the machine)
- Credentials encrypted at rest via PBKDF2 + Fernet vault
- Debate engine validates large trades ($25+) with AI bull/bear analysis
- Weather trader uses conservative $5-$10 sizing (rare events: $25 max)
- Sports arb uses Fill-or-Kill orders to prevent one-sided risk
- Rate limiter prevents order flooding (default: 10 orders/min)
- Approved API endpoint whitelist prevents arbitrary URL access
- Full audit trail with 90-day retention
