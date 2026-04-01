# Intel Feeds — Trading Intelligence Gathering Layer

The "trading cortex" — always-on monitoring of public sources that feeds signals into the bot's decision making. Runs alongside the whale scanner, copytrade strategy, and weather validation (METAR/NOAA).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        PUBLIC SOURCES                           │
│                                                                 │
│  r/Polymarket          AP News          Polymarket CLOB/Gamma   │
│  r/sportsbetting       NOAA Alerts      Volume spikes           │
│  r/predictit           ESPN RSS         Odds movements          │
│                        CoinDesk RSS                             │
│                        FRED/Fed RSS                             │
└──────┬──────────────────────┬───────────────────┬──────────────┘
       │                      │                   │
       ▼                      ▼                   ▼
┌─────────────┐   ┌───────────────────┐   ┌───────────────────┐
│reddit_monitor│   │  news_monitor.py  │   │polymarket_monitor │
│    .py      │   │  (every 10 min)   │   │      .py          │
│(every 15min)│   │                   │   │  (every 5 min)    │
└──────┬───────┘   └────────┬──────────┘   └────────┬──────────┘
       │                    │                        │
       │   Redis pub/sub    │                        │
       ▼                    ▼                        ▼
   intel:reddit         intel:news           intel:polymarket
       │                    │                        │
       └────────────────────┼────────────────────────┘
                            │
                            ▼
                ┌─────────────────────┐
                │  signal_aggregator  │
                │       .py           │
                │  • dedup            │
                │  • score            │
                │  • route            │
                └──────────┬──────────┘
                           │
              ┌────────────┼────────────────┐
              ▼            ▼                ▼
   notifications:    SQLite DB          HTTP API
     trading       /data/intel_feeds/  :8765/sentiment
   (iMessage)       signals.db         :8765/signals
   score ≥ 80      score ≥ 40          :8765/briefing
                                       :8765/health
```

---

## Signal Flow

1. **Source monitors** poll their respective public endpoints on a schedule
2. Each monitor applies lightweight scoring and deduplication locally
3. Signals are published to Redis `intel:*` pub/sub channels as JSON
4. **Signal aggregator** subscribes to all `intel:*` channels via pattern subscription
5. Aggregator deduplicates (content hash + 1-hour bucket), scores, and routes:
   - `relevance_score ≥ 80` → published immediately to `notifications:trading` for iMessage
   - `relevance_score ≥ 40` → persisted to SQLite for daily briefing
   - `relevance_score < 40` → logged and discarded
6. The **bot** queries the aggregator's HTTP API to get real-time context before placing trades

---

## Signal Schema

Every signal published to Redis is a JSON object with these fields:

| Field | Type | Description |
|---|---|---|
| `source` | string | e.g. `"reddit:r/Polymarket"`, `"rss:ap_news_top"`, `"polymarket:volume_spike"` |
| `timestamp` | string | ISO-8601 UTC |
| `relevance_score` | int | 0–100 |
| `urgency` | string | `"low"` / `"medium"` / `"high"` / `"critical"` |
| `category` | string | `"weather"` / `"sports"` / `"crypto"` / `"politics"` / `"economics"` / `"general"` |
| `markets_affected` | array | List of Polymarket condition IDs or market slugs |
| `summary` | string | Human-readable one-liner |
| `raw` | object | Full source payload |

---

## Configuration

All settings are environment variables (safe to set in Docker `-e` flags or `docker-compose.yml`):

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://172.18.0.100:6379` | Redis connection |
| `INTEL_HEALTH_PORT` | `8765` | HTTP health/query server port |
| `REDDIT_POLL_SEC` | `900` | Reddit poll interval (seconds) |
| `NEWS_POLL_SEC` | `600` | RSS news poll interval (seconds) |
| `POLYMARKET_POLL_SEC` | `300` | Polymarket poll interval (seconds) |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Running

### Docker (recommended)

```bash
# Build
docker build -t intel_feeds integrations/intel_feeds/

# Run (data volume keeps SQLite between restarts)
docker run -d \
  --name intel_feeds \
  --network host \
  -e REDIS_URL=redis://172.18.0.100:6379 \
  -v /opt/bot/data:/data \
  intel_feeds

# Health check
curl http://localhost:8765/health
```

### docker-compose snippet

```yaml
services:
  intel_feeds:
    build:
      context: .
      dockerfile: integrations/intel_feeds/Dockerfile
    environment:
      REDIS_URL: redis://172.18.0.100:6379
      LOG_LEVEL: INFO
    volumes:
      - bot_data:/data
    ports:
      - "8765:8765"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fs", "http://localhost:8765/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Local development

```bash
pip install -r integrations/intel_feeds/requirements.txt
python -m integrations.intel_feeds.runner --log-level DEBUG
```

---

## HTTP API

All endpoints return JSON.

### `GET /health`
```json
{
  "status": "ok",
  "uptime_sec": 3600,
  "monitors": {
    "reddit": "running",
    "news": "running",
    "polymarket": "running",
    "aggregator": "running"
  }
}
```

### `GET /sentiment?topic=bitcoin`
Query the last 24 hours of intelligence for any keyword or market name.

```json
{
  "topic": "bitcoin",
  "signal_count": 12,
  "avg_relevance": 62.5,
  "max_relevance": 91,
  "categories": {"crypto": 8, "economics": 3, "general": 1},
  "urgency_counts": {"high": 4, "medium": 6, "low": 2},
  "verdict": "high_activity",
  "signals": [...]
}
```

### `GET /signals?hours=1&min_relevance=60&category=crypto`
Recent signals from the in-memory cache. All parameters optional.

### `GET /briefing`
Daily briefing grouped by category, sorted by relevance.

---

## Adding New Sources

### New RSS feed

Edit `news_monitor.py` and add a tuple to `RSS_FEEDS`:

```python
RSS_FEEDS = [
    ...
    ("my_feed", "https://example.com/feed.rss", "politics"),
]
```

Categories: `general`, `weather`, `sports`, `crypto`, `politics`, `economics`

Add relevant keywords to `PREDICTION_MARKET_KEYWORDS` and `CATEGORY_KEYWORDS` as needed.

### New Reddit subreddit

Edit `reddit_monitor.py`:

```python
SUBREDDITS = [
    "Polymarket",
    "sportsbetting",
    "predictit",
    "politics",        # ← add here
]
```

### New data source (custom monitor)

1. Create `integrations/intel_feeds/my_monitor.py`
2. Implement an async class with a `run()` method
3. Publish signals to a new `intel:mysource` Redis channel — the aggregator picks up all `intel:*` channels automatically via pattern subscription
4. Import and instantiate the monitor in `runner.py`, add it to the task list

No changes needed to the aggregator or signal schema.

### Adjusting alert thresholds

In `signal_aggregator.py`:

```python
CRITICAL_THRESHOLD = 80   # score ≥ this → iMessage alert
MEDIUM_THRESHOLD   = 40   # score ≥ this → stored in SQLite
```

In `polymarket_monitor.py`:

```python
ODDS_MOVEMENT_THRESHOLD = 0.10   # 10% price move
VOLUME_SPIKE_MULTIPLIER = 2.0    # 2× volume spike
```

---

## Persistence

SQLite database at `/data/intel_feeds/signals.db` (mount a volume in Docker).

Tables:
- `signals` — all medium+ signals, rolling 24-hour window
- `dedup_seen` — hash-based dedup index, auto-pruned hourly

The aggregator prunes both tables hourly to keep the database compact.

---

## Design Principles

- **No API keys** — all sources use public endpoints
- **Fail gracefully** — each monitor catches its own exceptions; if one source goes down the others keep running
- **No spam** — content-hash deduplication + 1-hour buckets prevent repeated alerts for the same event
- **Structured logs** — all log output is JSON for easy ingestion by any log aggregator
- **Async throughout** — `asyncio` + `httpx` + `redis.asyncio` with no blocking I/O on the event loop (SQLite runs in a thread executor)
