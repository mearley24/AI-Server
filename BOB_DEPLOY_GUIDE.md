# Bob Deployment Guide — Multi-Platform Trading

> Updated March 23, 2026. Covers Kalshi + crypto (Kraken) + Polymarket observer mode.

---

## Prerequisites

- Bob (Mac Mini M4) with Docker installed
- AI-Server repo cloned at `~/AI-Server`
- Internet connection (API access)

---

## Step 1: Pull Latest Code

```bash
cd ~/AI-Server

# If you have local changes (like .env edits):
git stash
git pull origin main
git stash pop

# If no local changes:
git pull origin main
```

---

## Step 2: Sign Up for Kalshi (Trade Today)

Kalshi is CFTC-regulated, no waitlist, available in all 50 US states.

1. Go to [kalshi.com](https://kalshi.com) and create an account
2. Complete identity verification (KYC) — automated, takes minutes
3. Navigate to **Account & Security → API Keys**
4. Click **Create New API Key**
5. **Save the private key file** — it's shown once and cannot be recovered
6. Save the **API Key ID** (UUID) displayed on screen

```bash
# Store Kalshi private key securely
mkdir -p ~/AI-Server/secrets
cp ~/Downloads/your-kalshi-key.key ~/AI-Server/secrets/kalshi.key
chmod 600 ~/AI-Server/secrets/kalshi.key
```

### Fund Your Kalshi Account (Optional — can paper trade first)
- ACH bank transfer: Free, 1-3 business days
- Debit card (Visa/MC): 2% fee, instant
- No minimum deposit required

---

## Step 3: Sign Up for Kraken (Crypto Trading)

Kraken has the best API, lowest fees, and lists all your tokens (XRP, HBAR, XCN, PI).

1. Go to [kraken.com](https://www.kraken.com) and create an account
2. Complete identity verification (KYC)
3. Navigate to **Settings → API** and create a new API key
4. Enable permissions: **Query Funds**, **Query Open Orders & Trades**, **Create & Modify Orders**
5. Save both the **API Key** and **Private Key**

### Fund Your Kraken Account (Optional — can paper trade first)
- Bank transfer or crypto deposit
- Transfer XRP/HBAR from existing wallets if desired

---

## Step 4: Configure Environment

```bash
cd ~/AI-Server
cp .env.example .env
nano .env   # or use any editor
```

Add/update these variables:

```bash
# === Kalshi (Prediction Markets) ===
KALSHI_API_KEY_ID=your-kalshi-uuid-here
KALSHI_PRIVATE_KEY_PATH=/app/secrets/kalshi.key
KALSHI_ENVIRONMENT=demo          # Start with "demo" — switch to "production" when ready
KALSHI_DRY_RUN=true              # Paper trading ON

# === Kraken (Crypto) ===
KRAKEN_API_KEY=your-kraken-api-key
KRAKEN_API_SECRET=your-kraken-secret
KRAKEN_DRY_RUN=true              # Paper trading ON

# === Polymarket (Observer Mode) ===
POLY_DRY_RUN=true                # Observer mode — watching only

# === Enable Platforms ===
PLATFORMS_ENABLED=kalshi,crypto   # Add "polymarket" when US access is granted

# === AI (for debate engine) ===
ANTHROPIC_API_KEY=your-anthropic-key
```

---

## Step 5: Start Everything

```bash
cd ~/AI-Server
docker compose up -d
```

### Verify It's Running

```bash
# Check all containers are up
docker compose ps

# Check bot health
curl localhost:8430/health

# Check platform status — should show Kalshi + crypto connected
curl localhost:8430/status

# Watch live logs
docker compose logs -f polymarket-bot
```

### Expected `/status` Response

```json
{
  "status": "running",
  "platforms": {
    "kalshi": {
      "connected": true,
      "environment": "demo",
      "dry_run": true,
      "balance": "$10,000.00 (demo)"
    },
    "crypto": {
      "connected": true,
      "exchange": "kraken",
      "dry_run": true,
      "symbols": ["XRP/USD", "HBAR/USD", "XCN/USD", "PI/USD"]
    },
    "polymarket": {
      "connected": false,
      "dry_run": true,
      "status": "observer_mode"
    }
  },
  "active_strategies": 9,
  "open_positions": 0
}
```

---

## Step 6: Paper Trading Phase

Let the bot run in paper trading mode for at least a few days. Monitor performance:

```bash
# Check simulated positions
curl localhost:8430/positions

# Check paper P&L
curl localhost:8430/pnl

# Check specific platform
curl localhost:8430/positions?platform=kalshi
curl localhost:8430/positions?platform=crypto
```

### What to Watch For
- Are strategies generating signals? (Check logs)
- Is the debate engine approving/rejecting trades? (Claude bull vs bear)
- Paper P&L trending positive?
- Any errors or rate limit issues?

---

## Step 7: Go Live (When Ready)

### Switch Kalshi to Production
```bash
# Edit .env
KALSHI_ENVIRONMENT=production
KALSHI_DRY_RUN=false

# Restart
docker compose restart polymarket-bot
```

### Switch Crypto to Live Trading
```bash
# Edit .env
KRAKEN_DRY_RUN=false

# Restart
docker compose restart polymarket-bot
```

### Switch Polymarket Live (When US Access Granted)
```bash
# Edit .env
PLATFORMS_ENABLED=kalshi,crypto,polymarket
POLY_DRY_RUN=false
# Add Polymarket US API keys when received

# Restart
docker compose restart polymarket-bot
```

---

## Quick Reference

| Command | What It Does |
|---------|-------------|
| `docker compose up -d` | Start all services |
| `docker compose logs -f polymarket-bot` | Live bot logs |
| `docker compose restart polymarket-bot` | Restart after config change |
| `docker compose down` | Stop everything |
| `curl localhost:8430/health` | Health check |
| `curl localhost:8430/status` | Platform + strategy status |
| `curl localhost:8430/positions` | Open positions |
| `curl localhost:8430/pnl` | Profit & loss |

---

## Troubleshooting

### "Kalshi auth failed"
- Verify `KALSHI_API_KEY_ID` is the UUID (not the key file contents)
- Verify `kalshi.key` is at the path specified in `KALSHI_PRIVATE_KEY_PATH`
- For Docker: the path should be `/app/secrets/kalshi.key` (mapped via volume)

### "Kraken rate limit"
- CCXT handles this automatically with `enableRateLimit=True`
- If persistent: reduce `poll_interval_seconds` in config

### "Git merge conflict on pull"
```bash
git stash
git pull origin main
git stash pop
# Resolve any conflicts in .env manually
```

### "Container won't start"
```bash
docker compose logs polymarket-bot  # Check error
docker compose down
docker compose build --no-cache polymarket-bot
docker compose up -d
```
