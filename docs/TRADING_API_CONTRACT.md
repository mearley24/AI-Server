# Trading API Contract

This document freezes the trading endpoint contract moved out of `api/mobile_api.py` into `api/trading_api.py`.

## Base URL

- Local default: `http://localhost:8421`
- Env override: `TRADING_API_PORT`

## Endpoints

### Portfolio

- `GET /portfolio`
  - Reads `knowledge/portfolio.json`
  - Returns JSON portfolio payload or `{ "error": "No portfolio found" }`

- `GET /portfolio/goal`
  - Reads `knowledge/goals/beatrice_upgrade.json`
  - Returns normalized keys:
    - `target_amount`
    - `current_amount`
  - Legacy `target/current` keys are normalized server-side if present.

### Investing

- `GET /invest/scan`
  - Executes: `python3 tools/market_intel.py --polymarket`
  - Returns command result envelope:
    - `success` (bool)
    - `output` (str)
    - `error` (str)

- `POST /invest/research`
  - Body: `{ "query": "<text>" }`
  - Executes: `python3 tools/market_intel.py --research "<query>"`
  - Returns command result envelope.

### Trading Memory (Cortex-scoped)

Allowed categories:
- `clawdbot`
- `polymarket`
- `crypto`
- `trading`
- `market-intel`

- `GET /memory/categories`
- `POST /memory/facts/learn`
  - Body: `{ "text": "...", "category": "trading", "curate_now": true }`
  - Writes only under `knowledge/cortex/trading/<category>/`
- `POST /memory/curator/run`
  - Curates only `knowledge/cortex/trading/` paths
- `GET /memory/curator/status`
- `GET /memory/curator/review`
- `POST /memory/curator/facts/status`
  - Body: `{ "fact_ids": [1,2], "status": "trusted" }`
  - Applies only to fact IDs linked to trading-scoped sources.

## Compatibility Notes

- Trading routes are removed from `api/mobile_api.py`.
- Work app should continue using work-only routes on Mobile API.
- Trading app should point to Trading API base URL.
