# Cline Prompt K: Wire X Intake → Polymarket Bot Signal Pipeline

## Objective
Build a real-time bridge so every X post analyzed by x-intake automatically feeds actionable trading intelligence into the polymarket-bot's decision pipeline via Redis signals and the knowledge graph. Currently x-intake only sends iMessage summaries to Matt — the bot itself never sees any of this intel.

## Architecture Overview

```
X post arrives via iMessage
    → x-intake container analyzes (existing)
    → NEW: extract Polymarket-specific signals
    → NEW: publish to Redis polymarket:intel_signals channel
    → NEW: publish to Redis polymarket:x_strategies channel  
    → NEW: ingest into knowledge graph via HTTP
    → existing: send iMessage summary to Matt
    
polymarket-bot (already listens on polymarket:intel_signals)
    → signal_bus receives intel signal
    → strategies can query knowledge graph for X-sourced alpha
    → NEW: x_intel_strategy processes high-relevance signals
```

## Changes Required

### 1. Add Polymarket Signal Extraction to x-intake (`integrations/x_intake/main.py`)

After the existing `_analyze_with_llm()` call, add a second LLM call specifically for Polymarket signal extraction. Add this function:

```python
def _extract_polymarket_signals(text: str, author: str, transcript: str = "") -> dict:
    """Extract Polymarket-specific trading signals from analyzed content."""
    api_key = OPENAI_API_KEY
    if not api_key:
        return {"signals": [], "strategies": [], "market_keywords": []}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        content = f"Post by @{author}:\n{text}"
        if transcript:
            content += f"\n\nVideo transcript:\n{transcript[:6000]}"

        prompt = f"""You are a Polymarket trading signal extractor. Analyze this X post for actionable Polymarket trading intelligence.

{content}

Extract in this exact JSON format:
{{
    "signals": [
        {{
            "market_keyword": "search term to find this market on Polymarket",
            "direction": "yes|no",
            "confidence": 0.0-1.0,
            "reasoning": "why this signal matters",
            "timeframe": "hours|days|weeks",
            "source_credibility": "high|medium|low"
        }}
    ],
    "strategies": [
        {{
            "name": "strategy name",
            "description": "what to implement",
            "parameters": {{}},
            "applicable_to": ["weather_trader", "copytrade", "spread_arb", "mean_reversion", "presolution_scalp"]
        }}
    ],
    "market_keywords": ["keywords to search Polymarket API for related markets"],
    "risk_warnings": ["any warnings about current positions or market conditions"],
    "alpha_insights": ["specific edges or inefficiencies mentioned"]
}}

Rules:
- Only include signals with genuine predictive value for Polymarket outcomes
- market_keyword should match how Polymarket titles their markets (e.g. "Will Bitcoin reach $100k", "Fed rate cut", "Trump win")
- If the post discusses a strategy that could improve our bot, include it in strategies
- applicable_to should reference our actual strategy names
- Be conservative with confidence scores
- If the post has no Polymarket relevance, return empty arrays"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=800,
            temperature=0.2,
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        logger.warning("polymarket_signal_extraction_failed", error=str(e)[:200])
        return {"signals": [], "strategies": [], "market_keywords": []}
```

### 2. Add Redis Signal Publisher to x-intake (`integrations/x_intake/main.py`)

Add a function to publish extracted signals to the bot's Redis channels:

```python
async def _publish_to_bot(url: str, author: str, analysis: dict, poly_signals: dict) -> None:
    """Publish trading signals to polymarket-bot via Redis."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(REDIS_URL, decode_responses=True)

        relevance = analysis.get("relevance", 0)
        
        # Publish to polymarket:intel_signals (bot already listens here)
        intel_payload = {
            "source": "x_intake",
            "author": author,
            "url": url,
            "relevance": relevance,
            "summary": analysis.get("summary", "")[:500],
            "type": analysis.get("type", "info"),
            "action": analysis.get("action", "none"),
            "signals": poly_signals.get("signals", []),
            "market_keywords": poly_signals.get("market_keywords", []),
            "risk_warnings": poly_signals.get("risk_warnings", []),
            "alpha_insights": poly_signals.get("alpha_insights", []),
            "timestamp": int(__import__("time").time()),
        }
        
        # Only publish to bot if relevance >= 40 (avoid noise)
        if relevance >= 40 or poly_signals.get("signals"):
            await client.publish("polymarket:intel_signals", json.dumps(intel_payload))
            logger.info("published_to_bot_intel", author=author, relevance=relevance)

        # Publish strategy suggestions to dedicated channel
        if poly_signals.get("strategies"):
            strat_payload = {
                "source": "x_intake",
                "author": author,
                "url": url,
                "strategies": poly_signals["strategies"],
                "timestamp": int(__import__("time").time()),
            }
            await client.publish("polymarket:x_strategies", json.dumps(strat_payload))
            logger.info("published_strategy_suggestions", count=len(poly_signals["strategies"]))

        await client.aclose()

    except Exception as exc:
        logger.warning("redis_publish_to_bot_failed", error=str(exc)[:200])
```

### 3. Wire Into the Existing Pipeline (`integrations/x_intake/main.py`)

Modify `_process_url_and_reply()` to call the new functions. Find the existing function and update it:

```python
async def _process_url_and_reply(url: str) -> None:
    """Analyze a tweet URL, publish signals to bot, and send result via iMessage."""
    try:
        result = await asyncio.to_thread(_analyze_url_sync, url)
        summary = ""
        author = ""
        transcript = ""
        
        if isinstance(result, dict):
            analysis = result.get("analysis", {})
            author = result.get("author", "")
            if isinstance(analysis, dict):
                summary = analysis.get("summary", "")
            
            # NEW: Extract Polymarket-specific signals
            post_text = summary  # Use the summary as context
            poly_signals = await asyncio.to_thread(
                _extract_polymarket_signals, post_text, author, transcript
            )
            
            # NEW: Publish to polymarket-bot via Redis
            relevance = 0
            if isinstance(analysis, dict):
                # Parse relevance from summary text
                import re as _re
                rel_match = _re.search(r"Relevance:\s*(\d+)%", summary)
                if rel_match:
                    relevance = int(rel_match.group(1))
            
            await _publish_to_bot(url, author, {
                "summary": summary,
                "relevance": relevance,
                "type": "info",
                "action": "none",
            }, poly_signals)
            
            # NEW: Ingest into knowledge graph if high relevance
            if relevance >= 50 or poly_signals.get("signals"):
                await _ingest_to_knowledge(url, author, summary, poly_signals)
        
        if summary:
            await _send_reply(f"X Analysis:\n{summary}")
        elif isinstance(result, dict) and result.get("error"):
            logger.warning("analysis_error", url=url, error=result["error"])
    except Exception as exc:
        logger.warning("url_analysis_failed", url=url, error=str(exc)[:200])
        tb = traceback.format_exc()
        logger.debug("url_analysis_traceback", traceback=tb[:500])
```

### 4. Add Knowledge Graph Ingestion (`integrations/x_intake/main.py`)

Add a function to feed intel into the bot's knowledge graph via its internal API:

```python
async def _ingest_to_knowledge(url: str, author: str, summary: str, poly_signals: dict) -> None:
    """Ingest X post analysis into the polymarket-bot knowledge graph via Redis."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(REDIS_URL, decode_responses=True)

        # Build a structured knowledge payload
        knowledge_text = f"X Intel from @{author}:\n{summary}\n\n"
        
        if poly_signals.get("alpha_insights"):
            knowledge_text += "Alpha Insights:\n"
            for insight in poly_signals["alpha_insights"]:
                knowledge_text += f"- {insight}\n"
        
        if poly_signals.get("strategies"):
            knowledge_text += "\nStrategy Suggestions:\n"
            for strat in poly_signals["strategies"]:
                if isinstance(strat, dict):
                    knowledge_text += f"- {strat.get('name', '')}: {strat.get('description', '')}\n"
                    if strat.get("parameters"):
                        knowledge_text += f"  Parameters: {json.dumps(strat['parameters'])}\n"
        
        if poly_signals.get("risk_warnings"):
            knowledge_text += "\nRisk Warnings:\n"
            for warning in poly_signals["risk_warnings"]:
                knowledge_text += f"- {warning}\n"

        payload = {
            "action": "ingest",
            "source_url": url,
            "source_type": "x_intake",
            "author": author,
            "text": knowledge_text,
            "signals": poly_signals.get("signals", []),
            "market_keywords": poly_signals.get("market_keywords", []),
            "timestamp": int(__import__("time").time()),
        }
        
        await client.publish("polymarket:knowledge_ingest", json.dumps(payload))
        logger.info("knowledge_ingest_published", author=author)
        await client.aclose()

    except Exception as exc:
        logger.warning("knowledge_ingest_failed", error=str(exc)[:200])
```

### 5. Add Knowledge Ingest Listener to polymarket-bot (`polymarket-bot/src/main.py`)

In the `_start_redis_listener` function, add `polymarket:knowledge_ingest` and `polymarket:x_strategies` to the subscription list.

Find the existing subscribe call:
```python
await pubsub.subscribe(
    "polymarket:ta_signals",
    "polymarket:intel_signals",
    "polymarket:volume_alerts",
)
```

Replace with:
```python
await pubsub.subscribe(
    "polymarket:ta_signals",
    "polymarket:intel_signals",
    "polymarket:volume_alerts",
    "polymarket:knowledge_ingest",
    "polymarket:x_strategies",
)
```

Add handlers inside the `async for message in pubsub.listen():` loop, after the existing `elif channel == "polymarket:volume_alerts":` block:

```python
                    elif channel == "polymarket:knowledge_ingest":
                        # Ingest X intel into knowledge graph
                        try:
                            from knowledge.ingest import KnowledgeIngester
                            ingester = KnowledgeIngester()
                            await ingester.ingest_text(
                                text=data.get("text", ""),
                                source_url=data.get("source_url"),
                                source_type="x_intake",
                            )
                            log.info(
                                "x_intel_ingested",
                                author=data.get("author", ""),
                                source_url=data.get("source_url", ""),
                            )
                        except Exception as ingest_exc:
                            log.warning("x_intel_ingest_failed", error=str(ingest_exc)[:200])
                    
                    elif channel == "polymarket:x_strategies":
                        # Log strategy suggestions for heartbeat review
                        strategies = data.get("strategies", [])
                        for strat in strategies:
                            if isinstance(strat, dict):
                                signal = Signal(
                                    signal_type=SignalType.MARKET_DATA,
                                    source="x_strategy_suggestion",
                                    data={
                                        "strategy_name": strat.get("name", ""),
                                        "description": strat.get("description", ""),
                                        "applicable_to": strat.get("applicable_to", []),
                                        "parameters": strat.get("parameters", {}),
                                        "author": data.get("author", ""),
                                    },
                                )
                                await signal_bus.publish(signal)
                        log.info(
                            "x_strategy_suggestions_received",
                            count=len(strategies),
                            author=data.get("author", ""),
                        )
```

Update the log line to include the new channels:
```python
log.info(
    "redis_listener_started",
    channels=["polymarket:ta_signals", "polymarket:intel_signals", "polymarket:volume_alerts", "polymarket:knowledge_ingest", "polymarket:x_strategies"],
)
```

### 6. Enhance the Intel Signal Handler for X-Sourced Market Searches

Currently the bot receives intel signals at relevance >= 80 but does nothing market-specific with them. Add a handler in the strategy manager or create a lightweight intel processor.

Create a new file `polymarket-bot/strategies/x_intel_processor.py`:

```python
"""X Intel Processor — converts X intake signals into market search + position review.

Listens for high-relevance X intel signals on the signal bus and:
1. Searches Polymarket for markets matching signal keywords
2. Cross-references with current positions
3. Logs actionable opportunities to ideas.txt
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

IDEAS_FILE = Path(__file__).parent.parent / "ideas.txt"


class XIntelProcessor:
    """Processes X intake signals into actionable Polymarket opportunities."""

    def __init__(self, market_scanner=None):
        self.market_scanner = market_scanner
        self._last_processed: dict[str, float] = {}  # url -> timestamp (dedup)

    async def on_intel_signal(self, signal) -> None:
        """Handle an intel signal from the signal bus."""
        data = signal.data
        source = data.get("source", "")
        
        if source != "x_intake":
            return  # Only process X intake signals
        
        url = data.get("url", "")
        
        # Dedup: skip if we processed this URL in the last 5 minutes
        now = time.time()
        if url in self._last_processed and (now - self._last_processed[url]) < 300:
            return
        self._last_processed[url] = now
        
        # Clean up old entries
        cutoff = now - 3600
        self._last_processed = {k: v for k, v in self._last_processed.items() if v > cutoff}

        relevance = data.get("relevance", 0)
        signals = data.get("signals", [])
        market_keywords = data.get("market_keywords", [])
        alpha_insights = data.get("alpha_insights", [])
        risk_warnings = data.get("risk_warnings", [])
        author = data.get("author", "unknown")

        logger.info(
            "x_intel_processing",
            author=author,
            relevance=relevance,
            signal_count=len(signals),
            keyword_count=len(market_keywords),
        )

        ideas = []

        # Process trading signals
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            confidence = sig.get("confidence", 0)
            if confidence < 0.4:
                continue
            
            keyword = sig.get("market_keyword", "")
            direction = sig.get("direction", "")
            reasoning = sig.get("reasoning", "")
            
            ideas.append(
                f"[X-INTEL] @{author} | Market: {keyword} | "
                f"Direction: {direction} | Confidence: {confidence:.0%} | "
                f"Reasoning: {reasoning[:120]}"
            )

        # Log alpha insights
        for insight in alpha_insights:
            ideas.append(f"[X-ALPHA] @{author} | {insight[:200]}")

        # Log risk warnings
        for warning in risk_warnings:
            ideas.append(f"[X-RISK] @{author} | {warning[:200]}")

        # Write to ideas.txt (strategy manager reads this)
        if ideas:
            self._append_ideas(ideas)
            logger.info("x_intel_ideas_logged", count=len(ideas), author=author)

    def _append_ideas(self, ideas: list[str]) -> None:
        """Append ideas to ideas.txt with timestamp."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        
        lines = [f"\n--- X Intel [{timestamp}] ---"]
        lines.extend(ideas)
        lines.append("")
        
        try:
            with open(IDEAS_FILE, "a") as f:
                f.write("\n".join(lines))
        except Exception as exc:
            logger.warning("ideas_write_failed", error=str(exc)[:100])
```

### 7. Register the XIntelProcessor in main.py

In `polymarket-bot/src/main.py`, inside the `lifespan` function (after the signal bus is created and started), add:

Find where the signal bus is started (look for `await signal_bus.start()` or similar). After it, add:

```python
    # Register X Intel Processor
    try:
        from strategies.x_intel_processor import XIntelProcessor
        x_intel = XIntelProcessor()
        signal_bus.subscribe(SignalType.MARKET_DATA, x_intel.on_intel_signal)
        log.info("x_intel_processor_registered")
    except Exception as exc:
        log.warning("x_intel_processor_failed", error=str(exc)[:100])
```

### 8. Add WATCHED_MARKETS Env Var to x-intake Docker Config

In `docker-compose.yml`, under the `x-intake` service environment section, add:

```yaml
      - WATCHED_MARKETS=bitcoin,ethereum,fed,election,ai,trump,recession,interest rate
```

This feeds the keyword list to the pipeline.py analyzer for better Polymarket category matching.

## Verification Steps

After all changes, run these checks:

```zsh
cd ~/AI-Server

printf "=== Check 1: x-intake has _extract_polymarket_signals function ===\n"
grep -c "_extract_polymarket_signals" integrations/x_intake/main.py

printf "\n=== Check 2: x-intake has _publish_to_bot function ===\n"
grep -c "_publish_to_bot" integrations/x_intake/main.py

printf "\n=== Check 3: x-intake has _ingest_to_knowledge function ===\n"
grep -c "_ingest_to_knowledge" integrations/x_intake/main.py

printf "\n=== Check 4: bot subscribes to knowledge_ingest channel ===\n"
grep -c "knowledge_ingest" polymarket-bot/src/main.py

printf "\n=== Check 5: bot subscribes to x_strategies channel ===\n"
grep -c "x_strategies" polymarket-bot/src/main.py

printf "\n=== Check 6: XIntelProcessor exists ===\n"
test -f polymarket-bot/strategies/x_intel_processor.py && echo "EXISTS" || echo "MISSING"

printf "\n=== Check 7: XIntelProcessor registered in main.py ===\n"
grep -c "x_intel_processor" polymarket-bot/src/main.py

printf "\n=== Check 8: docker-compose has WATCHED_MARKETS ===\n"
grep -c "WATCHED_MARKETS" docker-compose.yml

printf "\n=== Check 9: No syntax errors in x_intel_processor.py ===\n"
python3 -c "import ast; ast.parse(open('polymarket-bot/strategies/x_intel_processor.py').read()); print('SYNTAX OK')"

printf "\n=== Check 10: No syntax errors in modified main.py ===\n"
python3 -c "import ast; ast.parse(open('polymarket-bot/src/main.py').read()); print('SYNTAX OK')"
```

All 10 checks should pass. After deploying:
1. Send an X link via iMessage to trigger the pipeline
2. Check x-intake logs for `published_to_bot_intel` and `knowledge_ingest_published`
3. Check polymarket-bot logs for `x_intel_ingested` and `x_intel_ideas_logged`
4. Check `ideas.txt` for new `[X-INTEL]` and `[X-ALPHA]` entries

## Important Notes
- All code must be zsh-compatible
- Do not use the number sign character in any bash/zsh scripts — replace with `printf` or alternatives
- Commit message format: `feat: wire x-intake signals into polymarket-bot pipeline`
- Push to remote when done
