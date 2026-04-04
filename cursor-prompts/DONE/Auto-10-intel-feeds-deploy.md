# Auto-10: Deploy Intel Feeds (Trading Cortex)

## Context Files to Read First
- integrations/intel_feeds/README.md
- integrations/intel_feeds/reddit_monitor.py
- integrations/intel_feeds/news_monitor.py
- integrations/intel_feeds/polymarket_monitor.py
- integrations/intel_feeds/signal_aggregator.py
- integrations/intel_feeds/runner.py
- polymarket-bot/ideas.txt

## Prompt

The intel feeds are built but not deployed. Wire them up and get them running in Docker:

1. **Fix and test each monitor**:
   - `reddit_monitor.py`: Verify it can fetch from r/Polymarket and r/sportsbetting without auth (use old.reddit.com JSON API: `https://old.reddit.com/r/Polymarket/new.json`). Parse titles and body for market-relevant signals.
   - `news_monitor.py`: Verify RSS feeds (AP News, ESPN, CoinDesk, FRED). Parse for events that move prediction markets.
   - `polymarket_monitor.py`: Verify Gamma API polling for volume spikes, new markets, and odds movements. Flag any market that moves >15¢ in an hour.

2. **Signal aggregator** (`signal_aggregator.py`):
   - Dedup signals across sources (same event from Reddit + news = 1 signal)
   - Score each signal 0-100 based on: source reliability, recency, relevance to active markets, number of corroborating sources
   - Signals scoring >80 auto-create entries in `polymarket-bot/ideas.txt` with status "pending" — the RBI pipeline picks them up
   - Signals scoring 50-80 go to Redis `intel:review` for manual review
   - Signals scoring <50 are logged and discarded

3. **Runner** (`integrations/intel_feeds/runner.py`):
   - Async event loop running all three monitors on their configured intervals (Reddit 15min, news 10min, Polymarket 5min)
   - Graceful shutdown on SIGTERM
   - Health heartbeat to Redis every 60s

4. **Docker integration**:
   - Add `intel-feeds` service to docker-compose.yml
   - Depends on Redis (healthy)
   - Mount `polymarket-bot/ideas.txt` as a shared volume so it can write new ideas
   - Environment: Redis URL, any API keys needed

5. **Notification**: When a high-scoring signal (>80) is detected, publish to Redis `notifications:trading` so iMessage bridge picks it up and sends alert.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
