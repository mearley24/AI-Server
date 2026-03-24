# CLAUDE.md — AI-First Development Guide

> This file is the source of truth for any AI agent (Claude Code, Cursor, Perplexity, Codex) working in this repo. Read it first. Follow it always.

---

## Project Identity

**Repo:** `mearley24/AI-Server`
**Owner:** Symphony Smart Homes — custom AV/home automation, Denver CO
**Primary Node:** Bob (Mac Mini M4, Docker, always-on 24/7)
**Telegram:** @ConductorBob_bot

---

## Architecture Overview

```
AI-Server/
├── polymarket-bot/          # Multi-platform trading bot (Kalshi, crypto, Polymarket)
│   ├── src/
│   │   ├── platforms/       # Platform abstraction layer
│   │   │   ├── base.py      # PlatformClient ABC — ALL platforms implement this
│   │   │   ├── kalshi_client.py    # Kalshi (RSA-PSS auth, prediction markets)
│   │   │   ├── crypto_client.py    # CCXT (Kraken/Coinbase — XRP, HBAR, XCN, PI)
│   │   │   └── polymarket_client.py # Polymarket (EIP-712/CLOB)
│   │   ├── security/        # vault.py, sandbox.py, audit.py
│   │   ├── main.py          # FastAPI on port 8430
│   │   ├── signal_bus.py    # Cross-platform signal routing
│   │   ├── debate_engine.py # Claude bull/bear AI trade evaluation
│   │   └── paper_ledger.py  # Dry-run trade simulation
│   ├── strategies/
│   │   ├── kalshi/          # kalshi_scanner, kalshi_weather, kalshi_fed
│   │   ├── crypto/          # btc_correlation, mean_reversion, momentum
│   │   ├── stink_bid.py     # Polymarket strategies
│   │   ├── flash_crash.py
│   │   ├── weather_trader.py
│   │   ├── sports_arb.py
│   │   └── base.py          # Abstract strategy interface
│   ├── sidecar/             # btc-15m-assistant (Node.js BTC TA → Redis)
│   └── tests/               # 68+ tests covering all platforms
├── orchestrator/            # Bob's brain — task scheduling, orchestration
├── integrations/            # D-Tools, Home Assistant, Telegram
├── client_ai/               # Symphony Concierge (client-facing AI)
├── clawwork/                # Revenue-generating AI tasks
├── voice_receptionist/      # Bob the Conductor (Twilio voice)
├── dashboard/               # Mission Control UI
├── ios-app/                 # SymphonyOps mobile app
└── docker-compose.yml       # All services
```

---

## Core Patterns — Follow These

### 1. Platform Abstraction (Trading)

Every trading platform implements `PlatformClient` from `polymarket-bot/src/platforms/base.py`:

```python
class PlatformClient(ABC):
    async def connect() -> bool
    async def get_markets(**filters) -> list[dict]
    async def get_orderbook(market_id) -> dict
    async def place_order(order: Order) -> dict
    async def cancel_order(order_id) -> bool
    async def get_positions() -> list[Position]
    async def get_balance() -> dict
    async def subscribe_realtime(market_ids, callback) -> None
    platform_name: str  # property
    is_dry_run: bool    # property
```

**Adding a new platform?** Create `src/platforms/new_client.py`, implement `PlatformClient`, add to config.

### 2. Strategy Interface

All strategies extend `strategies/base.py`. Each strategy:
- Receives signals via `signal_bus`
- Evaluates using platform-specific data
- Optionally runs through `debate_engine` (Claude bull/bear)
- Executes via the appropriate `PlatformClient`
- Logs all decisions to `security/audit.py`

### 3. Signal Bus

`signal_bus.py` routes signals across platforms:
- A weather forecast signal can trigger both `kalshi_weather` and `weather_trader` simultaneously
- BTC momentum from the sidecar can feed both `latency_detector` (Polymarket) and `btc_correlation` (crypto)
- Signals specify `platform: str` — "kalshi", "crypto", "polymarket", or "all"

### 4. Security Stack

- **vault.py** — PBKDF2+Fernet encryption for API keys at rest
- **sandbox.py** — Kill switch, rate limits, exposure caps
- **audit.py** — JSONL append-only log of every trade decision
- **Never** hardcode keys. Always use `.env` + vault encryption.

### 5. Dry-Run by Default

**Every platform defaults to `dry_run=true`.** Paper trading uses `paper_ledger.py` to simulate orders without touching real APIs. Set `*_DRY_RUN=false` in `.env` only when ready to go live.

---

## Development Workflow (AI-First)

### Chain of Thought — How We Build Features

Follow this pipeline for any new feature or upgrade:

```
Research → Spec → Build → Test → PR → Merge → Deploy
   ↑                                              |
   └──────── Verification Loop ←───────────────────┘
```

1. **Research**: Gather data (API docs, X posts, market patterns, tutorials). Save findings to workspace files.
2. **Spec**: Write a structured spec (markdown) with:
   - Context (what exists)
   - Architecture (how it fits)
   - Implementation details (code patterns, endpoints, models)
   - Priority order
3. **Build**: Code against the spec. Follow patterns in this file.
4. **Test**: Run `pytest polymarket-bot/tests/` — all tests must pass.
5. **PR**: Create a feature branch, open PR with clear description.
6. **Merge**: Squash merge to main.
7. **Deploy**: Bob pulls, `docker compose up -d`.

### Prompt Chaining Patterns

Use these sequential chains for different task types:

| Task | Chain |
|------|-------|
| New strategy | Research market pattern → Spec with edge analysis → Implement strategy class → Backtest with paper_ledger → Review P&L → Push |
| New platform | Read API docs → Auth implementation → Core endpoints → WebSocket → Strategy adapters → Integration tests → Push |
| Bug fix | Reproduce → Root cause → Fix → Test → Push |
| Content/research | Gather info → List options → Analyze each → Recommend |

### Verification Loops

After any significant change:
- Run tests: `cd polymarket-bot && python -m pytest tests/ -v`
- Check types: all public functions have type hints
- Check security: no secrets in code, vault.py for key storage
- Check dry-run: new platforms must default to `dry_run=true`

---

## Coding Standards

| Language | Style |
|----------|-------|
| Python | PEP 8, type hints, docstrings on public functions, async/await for I/O |
| JavaScript | `'use strict'`, CommonJS, 2-space indent, single quotes |
| Shell | `#!/usr/bin/env bash`, `set -euo pipefail`, comment non-obvious steps |
| Config | YAML for structured config, `.env` for secrets |
| Commits | Imperative mood, ≤72 chars subject (`feat:`, `fix:`, `refactor:`, `docs:`) |

**No TypeScript. No npm frameworks (React/Vue). Vanilla JS for frontends.**

---

## Key Environment Variables

```bash
# Trading Platforms
PLATFORMS_ENABLED=kalshi,crypto       # Comma-separated: kalshi, crypto, polymarket
KALSHI_API_KEY_ID=                    # UUID from Kalshi dashboard
KALSHI_PRIVATE_KEY_PATH=/app/secrets/kalshi.key
KALSHI_ENVIRONMENT=demo               # "demo" or "production"
KALSHI_DRY_RUN=true
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
KRAKEN_DRY_RUN=true
POLY_PRIVATE_KEY=                     # Polymarket wallet key (in vault)
POLY_DRY_RUN=true

# AI
ANTHROPIC_API_KEY=                    # Claude for debate engine
OPENAI_API_KEY=                       # Backup LLM

# Infrastructure
REDIS_URL=redis://redis:6379
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

---

## Docker Services

```bash
docker compose up -d                  # Start all services
docker compose logs -f polymarket-bot # Watch trading bot logs
docker compose restart polymarket-bot # Restart after config change
```

| Service | Port | Description |
|---------|------|-------------|
| polymarket-bot | 8430 | Multi-platform trading bot (FastAPI) |
| redis | 6379 | Signal bus + BTC sidecar bridge |
| btc-15m-assistant | — | BTC technical analysis sidecar |
| uptime-kuma | 3001 | Service monitoring |
| openwebui | 8080 | Local LLM interface |

---

## API Quick Reference

```bash
curl localhost:8430/health            # Health check
curl localhost:8430/status            # All platforms + strategies status
curl localhost:8430/positions         # Open positions (all platforms)
curl localhost:8430/positions?platform=kalshi  # Filter by platform
curl localhost:8430/pnl               # Aggregated P&L
curl localhost:8430/strategies        # Available strategies + configs
```

---

## Trading Strategy Inventory

### Prediction Markets (Kalshi + Polymarket)
| Strategy | Platform | Pattern |
|----------|----------|---------|
| `stink_bid` | Polymarket | Low-ball limit orders on high-leverage markets |
| `flash_crash` | Polymarket | Orderbook drop ≥0.30 in 10s → buy |
| `weather_trader` | Polymarket | NOAA/AccuWeather divergence from market pricing |
| `sports_arb` | Polymarket | YES+YES < $0.98 on binary sports markets |
| `latency_detector` | Polymarket | 9-16s window after BTC >0.11% move on Binance |
| `order_flow_analyzer` | Polymarket | Large wallet pattern detection |
| `kalshi_scanner` | Kalshi | Market discovery + opportunity scoring |
| `kalshi_weather` | Kalshi | Weather contracts via NOAA data |
| `kalshi_fed` | Kalshi | Fed rate / CPI / GDP economic indicators |

### Crypto Spot (Kraken/Coinbase via CCXT)
| Strategy | Tokens | Pattern |
|----------|--------|---------|
| `btc_correlation` | XRP, HBAR, XCN, PI | BTC momentum → altcoin delay (9-16s window) |
| `mean_reversion` | XRP, HBAR, XCN | Bollinger Bands + RSI oversold/overbought |
| `momentum` | All | MACD + EMA crossover trend following |

---

## When You're Lost

1. Read this file.
2. Read `AGENTS.md` for Bob's operational context.
3. Read `.cursor/rules/project.mdc` for coding standards.
4. Check `polymarket-bot/README.md` for bot-specific docs.
5. Check `polymarket-bot/config.example.yaml` for all configuration options.
6. Run `pytest polymarket-bot/tests/ -v` to verify nothing is broken.

---

## Known Issues & Fixes (Never Repeat These)

Every bug we encounter gets documented here so no AI agent makes the same mistake twice.

### eth_account API Rename
- **Problem**: `from eth_account.messages import encode_structured_data` fails on newer eth_account versions
- **Fix**: Use try/except fallback: `except ImportError: from eth_account.messages import encode_typed_data as encode_structured_data`
- **File**: `src/signer.py`

### Binance WebSocket Geoblocked in US
- **Problem**: Binance returns HTTP 451 "Unavailable for Legal Reasons" from US IPs
- **Fix**: Use Kraken WebSocket (`wss://ws.kraken.com/v2`) as default BTC feed. Set `BTC_FEED_SOURCE=kraken` in .env
- **File**: `src/latency_detector.py`

### Polymarket WebSocket When Not Enabled
- **Problem**: Bot tries to connect to Polymarket CLOB WebSocket even when Polymarket is not in PLATFORMS_ENABLED, causing 404 spam
- **Fix**: Check PLATFORMS_ENABLED before starting WebSocket. Skip if "polymarket" not listed.
- **File**: `src/main.py`

### CCXT Balance Dict Formatting
- **Problem**: CCXT `fetch_balance()` returns nested dicts. Formatting with `:.2f` on a dict throws "unsupported format string"
- **Fix**: Extract numeric value from `balance.get('USD', {}).get('total', 0)` or sum non-zero values
- **File**: `heartbeat/health_check.py`

### Docker .env Not Reloading on Restart
- **Problem**: `docker compose restart` does NOT reload .env changes
- **Fix**: Must use `docker compose down <service> && docker compose up -d <service>` to pick up .env changes

### Platform Import Crashes
- **Problem**: Missing platform SDK dependency crashes entire bot on startup
- **Fix**: All platform imports in main.py use try/except ImportError. Health checker reports "dependency_missing" instead of crashing.
- **File**: `src/main.py`, `heartbeat/health_check.py`

---

## Principles

- **Dry-run first.** Always. No exceptions.
- **Vault your secrets.** Never `.env` alone — use `vault.py` encryption.
- **Log everything.** `audit.py` JSONL for trades, structured logging for operations.
- **Platform-agnostic strategies.** Use the abstraction layer. Don't hardcode platform-specific logic in strategy classes.
- **AI decides, human approves.** Debate engine evaluates, sandbox enforces limits, human flips `DRY_RUN=false`.
- **Ship fast, iterate faster.** Spec → Build → Test → Push. Verification loops catch issues. Don't over-plan.
