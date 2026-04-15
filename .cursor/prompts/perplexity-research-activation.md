<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes. Use printf or write-file patterns instead. -->

# Perplexity Research Activation — Fix the Disconnected Pipeline

## Problem

Matt has $98 in Perplexity API credits sitting idle. The research pipeline
is broken because:

1. `cortex-autobuilder/daemon.py` looks for `OPENROUTER_API_KEY` but compose
   never passes it. The scanner loop silently skips every query.
2. `polymarket-bot/src/market_intel.py` calls OpenRouter instead of Perplexity
   directly, using a different API URL and env var.
3. `knowledge-scanner/scanner.py` also uses OpenRouter (dead service, but fix
   for reference).
4. Only `sentiment_engine.py`, `openclaw/main.py`, and `openclaw/research_agent.py`
   correctly call `api.perplexity.ai` with `PERPLEXITY_API_KEY`.

Result: the 24/7 research loop produces nothing. No edges found, no knowledge
built, $98 wasted.

## Fix

Standardize everything on `PERPLEXITY_API_KEY` calling `api.perplexity.ai`
directly. No OpenRouter middleman.

### Step 1: Fix cortex-autobuilder daemon

In `integrations/cortex_autobuilder/daemon.py`, find the `_query_perplexity` function
(around line 188). Replace the OpenRouter call with a direct Perplexity call:

Change:
```python
api_key = os.getenv("OPENROUTER_API_KEY", "")
if not api_key:
    logger.warning("scanner_no_openrouter_key query=%s", query[:60])
    return ""
```

To:
```python
api_key = os.getenv("PERPLEXITY_API_KEY", "")
if not api_key:
    logger.warning("scanner_no_perplexity_key query=%s", query[:60])
    return ""
```

Change the API URL from:
```python
"https://openrouter.ai/api/v1/chat/completions",
```
To:
```python
"https://api.perplexity.ai/chat/completions",
```

Change the model from:
```python
"model": "perplexity/llama-3.1-sonar-small-128k-online",
```
To:
```python
"model": "sonar",
```

Update headers — remove OpenRouter-specific headers, use standard Bearer auth:
```python
headers={
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
},
```

### Step 2: Fix polymarket-bot market_intel.py

In `polymarket-bot/src/market_intel.py`, change:

```python
PERPLEXITY_API_URL = "https://api.openrouter.ai/api/v1/chat/completions"
```
To:
```python
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
```

In `_fetch_perplexity_research`, change the model from:
```python
"model": "perplexity/sonar",
```
To:
```python
"model": "sonar",
```

The env var `PERPLEXITY_API_KEY` is already correct in this file.

### Step 3: Add PERPLEXITY_API_KEY to cortex-autobuilder in compose

In `docker-compose.yml`, find the `cortex-autobuilder` service environment
section. Add:

```yaml
- PERPLEXITY_API_KEY=${PERPLEXITY_API_KEY:-}
```

### Step 4: Verify all services that need the key have it

Check these services in docker-compose.yml and ensure `PERPLEXITY_API_KEY`
is in their environment block:

- `cortex-autobuilder` — ADD (missing)
- `polymarket-bot` — already has it (verify)
- `openclaw` — already has it (verify)

If any are missing, add `- PERPLEXITY_API_KEY=${PERPLEXITY_API_KEY:-}`.

### Step 5: Budget the $98

At ~$0.005 per query (sonar model), $98 = ~19,600 queries.

Current scan_topics.py has 7 topics:
- 3 trading topics at 1h frequency = 72 queries/day
- 2 AI tools topics at 2h frequency = 24 queries/day
- 1 smart home topic at 8h frequency = 3 queries/day
- 1 IoT topic at 12h frequency = 2 queries/day

Total: ~101 queries/day = ~$0.50/day = 196 days of budget.

That is very conservative. Add more aggressive topics to `scan_topics.py`:

```python
# Additional topics — use the $98 budget more aggressively
{
    "query": "Kalshi prediction market new contracts opportunities edges 2026",
    "category": "trading",
    "frequency_hours": 2,
},
{
    "query": "latest Ollama Gemma LLM local AI models benchmarks releases",
    "category": "ai_tools",
    "frequency_hours": 4,
},
{
    "query": "Mac Mini server homelab self-hosting automation Docker 2026",
    "category": "ai_tools",
    "frequency_hours": 8,
},
{
    "query": "prediction market arbitrage strategies Polymarket Kalshi spread",
    "category": "trading",
    "frequency_hours": 2,
},
{
    "query": "weather prediction market strategies NOAA forecast edge Kalshi",
    "category": "trading",
    "frequency_hours": 4,
},
{
    "query": "autonomous AI agent business automation revenue generation 2026",
    "category": "business",
    "frequency_hours": 6,
},
{
    "query": "D-Tools Cloud API automation smart home proposals integrations",
    "category": "smart_home",
    "frequency_hours": 12,
},
```

Updated daily budget: ~160 queries/day = ~$0.80/day = 122 days.
Still very sustainable. Can increase further if results are good.

### Step 6: Add Perplexity to x-intake for deep analysis

In `integrations/x_intake/main.py`, when a post has relevance >= 70 and
is tagged as "build" or "alpha" or "tool", do a follow-up Perplexity
research query to gather more context:

```python
async def _deep_research(topic: str, url: str) -> str:
    """Use Perplexity to research a topic identified from an X post."""
    api_key = os.getenv("PERPLEXITY_API_KEY", "")
    if not api_key:
        return ""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [{"role": "user", "content": f"Research this topic for practical implementation: {topic}. Focus on: how to build it, what tools are needed, costs, and whether anyone has done it successfully."}],
                    "max_tokens": 1024,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("deep_research_failed", error=str(exc)[:200])
        return ""
```

Wire it into `_process_url_and_reply()` — after the initial analysis, if
relevance >= 70 and type is "build"/"alpha"/"tool":

```python
if relevance >= 70 and analysis.get("type") in ("build", "alpha", "tool"):
    research = await _deep_research(analysis.get("action", summary[:200]), url)
    if research:
        # Save the deep research to Cortex
        await _save_to_cortex(url, author, {
            **analysis,
            "summary": f"DEEP RESEARCH: {research[:2000]}",
            "type": "research",
        }, poly_signals)
        # Also send to Matt via iMessage
        research_msg = f"Deep dive on @{author}'s post:\n\n{research[:1500]}\n\nSource: {url}"
        await _send_imessage(research_msg)
```

Also add `PERPLEXITY_API_KEY` to the x-intake service in docker-compose.yml
if not already present:
```yaml
- PERPLEXITY_API_KEY=${PERPLEXITY_API_KEY:-}
```

## Verification

After changes:

```
docker compose config --quiet && echo "Compose valid"
grep -rn "openrouter" integrations/cortex_autobuilder/daemon.py polymarket-bot/src/market_intel.py
```

The second command should return NO results (all OpenRouter references removed
from active code).

Commit and push:
```
feat: activate Perplexity research pipeline — fix disconnected API calls

- Standardize all services on PERPLEXITY_API_KEY + api.perplexity.ai
- Remove OpenRouter middleman from cortex-autobuilder and market_intel
- Add PERPLEXITY_API_KEY to cortex-autobuilder compose env
- Add 7 new scan topics (trading, AI, business, smart home)
- Add deep research follow-up for high-relevance X posts
- Budget: ~160 queries/day = $0.80/day = 122 days on $98
```
