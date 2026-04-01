# X (Twitter) Link Intake Pipeline

Bob's iMessage-to-X integration. When Matt sends Bob a tweet link, this pipeline:

1. Detects the X/Twitter URL in the iMessage
2. Fetches the post content (text, media, stats, thread context)
3. Analyzes it for trading signals, sentiment, and Polymarket relevance
4. Replies via iMessage with a concise briefing

---

## Architecture

```
Matt's iPhone
    │
    │ iMessage with tweet URL
    ▼
iMessage Bridge (host.docker.internal:8199)
    │
    │ publishes to Redis
    ▼
Redis (172.18.0.100:6379)  ←── pipeline subscribes
    │
    ▼
x_intake pipeline
    ├── post_fetcher.py    fetches tweet content (no API key)
    ├── analyzer.py        trading signal analysis
    └── pipeline.py        orchestration + response formatting
    │
    │ publishes to notification-hub
    ▼
Redis → iMessage bridge → Matt's iPhone
```

---

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports |
| `post_fetcher.py` | Fetches tweet content via fxtwitter → vxtwitter → Nitter → x.com |
| `analyzer.py` | Keyword-based trading signal analysis and Polymarket relevance detection |
| `pipeline.py` | Main orchestrator: Redis daemon, bridge polling, and CLI mode |
| `README.md` | This file |

---

## How the Fetcher Works

X aggressively blocks scrapers. The fetcher tries four methods in order:

1. **fxtwitter API** (`api.fxtwitter.com`) — Rich JSON, usually works. Returns text, media, stats, thread data. No API key needed.
2. **vxtwitter API** (`api.vxtwitter.com`) — Similar JSON API, different hosting.
3. **Nitter instances** — Tries a rotation of public Nitter mirrors. HTML parsing, no JS rendering required. Falls back to the next instance if one is down.
4. **Direct x.com** — Last resort. Fetches meta tags only (og:description). Works for public posts when all else fails.

If all methods fail (deleted post, private account, rate limit), Bob sends a clean error message to Matt explaining the failure.

**Thread context:** If the fetched post is a reply, the pipeline automatically fetches the parent post so Bob has full context.

---

## How the Analyzer Works

v1 uses keyword matching — no LLM, no API keys required.

**What it detects:**
- **Assets**: Crypto tickers (BTC, ETH, SOL, 100+ more) and stock tickers (AAPL, TSLA, NVDA, etc.)
- **Sentiment**: Bullish/bearish keyword scoring (buy, moon, pump vs sell, dump, crash)
- **Price targets**: Patterns like `$50k`, `100k`, `1000x`
- **Whale activity**: Large order mentions, on-chain references, institutional language
- **Polymarket categories**: Election, crypto, Fed/rates, sports, AI, geopolitical, finance events
- **Prediction market signals**: Direct Polymarket/Kalshi mentions, probability language
- **Open position hits**: Cross-references against Bob's current positions
- **Strategy signals**: Entry/exit mentions, risk/reward setups, DCA, options language

**Relevance score**: 0–100% composite score weighted by position hits, whale activity, and signal density.

---

## Configuration

All settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `172.18.0.100` | Redis server host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_CHANNEL_IN` | `imessage-in` | Channel to subscribe for incoming messages |
| `REDIS_CHANNEL_OUT` | `notification-hub` | Channel to publish responses |
| `IMESSAGE_BRIDGE_URL` | `http://host.docker.internal:8199` | iMessage bridge URL |
| `MATT_PHONE` | (empty) | Matt's iMessage address — fallback if bridge doesn't provide sender |
| `OPEN_POSITIONS` | (empty) | Comma-separated tickers to watch: `BTC,ETH,SOL` |
| `WATCHED_MARKETS` | (empty) | Comma-separated Polymarket keywords |
| `POLL_INTERVAL` | `10` | Bridge poll interval (seconds, polling mode only) |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING` |

---

## Setup

### Dependencies

```bash
pip install redis
# No other external dependencies — uses only Python stdlib
```

### Docker Compose snippet

```yaml
x_intake:
  build: .
  command: python -m integrations.x_intake.pipeline --daemon
  environment:
    - REDIS_HOST=172.18.0.100
    - REDIS_PORT=6379
    - REDIS_CHANNEL_IN=imessage-in
    - REDIS_CHANNEL_OUT=notification-hub
    - IMESSAGE_BRIDGE_URL=http://host.docker.internal:8199
    - MATT_PHONE=+15551234567
    - OPEN_POSITIONS=BTC,ETH,SOL
    - WATCHED_MARKETS=election,crypto,fed
    - LOG_LEVEL=INFO
  extra_hosts:
    - "host.docker.internal:host-gateway"
  restart: unless-stopped
```

### Redis message format (incoming)

The pipeline expects messages on `imessage-in` in this JSON format:

```json
{
  "type": "imessage",
  "sender": "+15551234567",
  "text": "Check this out https://x.com/elonmusk/status/1234567890",
  "timestamp": 1712345678
}
```

Any field named `text`, `body`, or `content` will be scanned for tweet URLs.
The sender is read from `sender`, `from`, or `address`.

### Redis message format (outgoing)

Responses are published to `notification-hub`:

```json
{
  "type": "imessage_reply",
  "to": "+15551234567",
  "text": "🐦 @elonmusk: \"...\"\n\n🟢 BULLISH | Assets: DOGE, TSLA\n...",
  "source": "x_intake",
  "trigger_url": "https://x.com/elonmusk/status/1234567890",
  "timestamp": 1712345679
}
```

---

## Usage

### CLI mode (testing)

```bash
# Test with a single tweet URL
python -m integrations.x_intake.pipeline "https://x.com/user/status/123456789"

# With positions
OPEN_POSITIONS=BTC,ETH python -m integrations.x_intake.pipeline "https://x.com/user/status/123"

# Or with flags
python -m integrations.x_intake.pipeline "https://x.com/user/status/123" --positions BTC,ETH,SOL
```

Or run individual modules directly:

```bash
# Just the fetcher
python integrations/x_intake/post_fetcher.py "https://x.com/user/status/123"

# Just the analyzer (fetches + analyzes)
python -m integrations.x_intake.analyzer "https://x.com/user/status/123" "BTC,ETH"
```

### Daemon mode (production)

```bash
# Redis pub/sub (default, preferred)
python -m integrations.x_intake.pipeline --daemon

# Bridge polling (if Redis unavailable)
python -m integrations.x_intake.pipeline --daemon --mode poll

# With runtime position override
python -m integrations.x_intake.pipeline --daemon --positions BTC,ETH,SOL --markets election,crypto
```

---

## Example iMessage Response

When Matt sends: `"Interesting take https://x.com/investorA/status/9876543210"`

Bob replies:

```
🐦 @investorA: "BTC breaking out above 72k resistance, institutional 
accumulation on-chain confirms. Target 85k by end of month."

❤️ 4,821  🔁 1,203  👁 890,000

🟢 BULLISH | Assets: BTC
⚠️  Hits your positions: BTC (bullish)
🐳 Whale activity mentioned
📈 Polymarket: crypto

💰 price_targets: $72k, $85k

✅ What to do:
  • Consider adding to BTC position — post is bullish on BTC
  • Whale activity detected — check on-chain data for confirmation
  • Search Polymarket for open 'crypto' markets
  • Bullish signal on BTC — evaluate entry opportunity

Relevance: 82% ▓▓▓▓░
Source: https://x.com/investorA/status/9876543210
```

---

## Updating Nitter Instances

Nitter instances go up and down. Update the `NITTER_INSTANCES` list in `post_fetcher.py` as needed.

Check live status at: https://status.d420.de/ (Nitter instance monitor)

---

## Upgrading to LLM Analysis (v2)

The `PostAnalyzer` class in `analyzer.py` is designed for easy LLM extension.
To add LLM analysis, override `PostAnalyzer.analyze()` or add a new method that:

1. Formats `post.text` as an LLM prompt
2. Calls Bob's local LLM (Ollama, OpenAI-compatible endpoint, etc.)
3. Parses structured JSON from the response
4. Merges with keyword-matched results

The `AnalysisResult` dataclass is already structured for LLM output compatibility.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| All Nitter instances fail | Update `NITTER_INSTANCES` in `post_fetcher.py` |
| Redis connection refused | Check `REDIS_HOST`/`REDIS_PORT`; ensure Bob container can reach Redis |
| Bridge unreachable | Verify `host.docker.internal` DNS resolves; check `extra_hosts` in compose |
| Post shows as `fetch_method: direct_meta` | fxtwitter + Nitter are both down; content may be truncated |
| No response to Matt | Confirm `MATT_PHONE` is set or bridge correctly echoes sender in message JSON |
