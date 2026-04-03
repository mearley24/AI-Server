# Auto-23: Cost Optimization — $50/Month Target for 24/7 Operations

## The Vision

Bob runs 16+ services 24/7. Every LLM validation call, every email classification, every trade analysis hits the OpenAI API. At current rates that's potentially $200-500/month. The target is $50/month by using aggressive caching, local model fallbacks, and smart routing.

## Context Files to Read First
- strategies/llm_validator.py (OpenAI calls per trade)
- email-monitor/analyzer.py (OpenAI calls per email)
- polymarket-bot/src/debate_engine.py
- setup/ollama_worker/README.md
- AGENTS.md (continuous learning section — Perplexity API budget)

## Prompt

Build a cost optimization layer that minimizes API spend without reducing quality:

### 1. LLM Router (`core/llm_router.py`)

Central routing layer that every service calls instead of OpenAI directly:

```python
response = await llm_router.complete(
    prompt="Classify this email...",
    quality="low",      # low, medium, high, critical
    max_cost_cents=1,   # budget cap for this call
    cache_key="email_classify_{hash}",
    fallback="local"    # local, skip, error
)
```

Routing logic:
- `quality=low` → Ollama on Maestro (llama3.1:8b) → FREE
  - Email classification, basic categorization, simple summaries
- `quality=medium` → GPT-4o-mini ($0.15/1M input) → CHEAP
  - Trade validation, market analysis, content generation
- `quality=high` → GPT-4o ($2.50/1M input) → MODERATE
  - Proposal generation, complex reasoning, client communications
- `quality=critical` → Claude Sonnet ($3/1M input) → PREMIUM
  - Only when accuracy is paramount and other models failed

### 2. Prompt Caching

- Hash every prompt + relevant context
- Store response in Redis with TTL based on content type:
  - Email classification: 1 hour (same email won't be re-classified)
  - Market category: 24 hours (market categories don't change)
  - Trade validation: 5 minutes (prices change fast)
  - Product specs: 7 days (specs don't change)
- Cache hit rate target: 40%+ (huge savings on repetitive classifications)

### 3. Batch Processing

Instead of one API call per trade/email, batch where possible:
- Collect 5-10 trade validation requests → send as one batched prompt → parse responses
- Email classification: batch all unread emails in one call instead of one-by-one
- Reduces per-request overhead and total token count

### 4. Local Model Fallbacks

When Ollama on Maestro is available (Auto-15):
- Route ALL low-quality calls to local: email triage, basic classification, fact extraction
- Route embeddings to local `nomic-embed-text`
- Only escalate to OpenAI when local model confidence is below threshold
- Track local vs cloud ratio: target 70% local / 30% cloud

### 5. Cost Tracking (`core/cost_tracker.py`)

Track every API call with cost:
- Log: service, model, input tokens, output tokens, cost, cache hit/miss, timestamp
- Store in SQLite `data/api_costs.db`
- Daily summary: total cost, cost by service, cost by model, cache hit rate
- Weekly trend: are costs going up or down?
- Alert if daily cost exceeds $5 (something is wrong)
- Monthly report via iMessage: "API costs this month: $47. Breakdown: trading $22, email $12, learning $8, other $5"

### 6. Specific Optimizations

a) **Trade validation** (`strategies/llm_validator.py`):
   - Before calling OpenAI, check if we've validated the same market category + price range in the last hour
   - Sports at 9¢ from an 80% WR wallet? We've seen this pattern 50 times — auto-approve without LLM
   - Build a pattern cache: {category + price_range + wallet_tier} → {approve/reject + confidence}
   - Only call LLM for novel situations

b) **Email classification** (`email-monitor/analyzer.py`):
   - Known senders with established routing → skip LLM entirely
   - Emails from stopletz1@gmail.com always route to Topletz folder — no AI needed
   - Only use LLM for unknown senders or ambiguous content

c) **Continuous learning** (`orchestrator/continuous_learning.py`):
   - Switch from Perplexity `sonar-pro` to `sonar` for learning queries (cheaper)
   - Cap at 30 queries/day instead of 50
   - Cache learning results — don't research the same product twice

d) **Debate engine** (`src/debate_engine.py`):
   - Only trigger for trades >$5 (small trades aren't worth the API cost to validate)
   - Cache market analysis for 30 minutes

### 7. Integration

- All services import `llm_router` instead of calling OpenAI directly
- Cost data published to event bus (API-11)
- Cost dashboard in Mission Control (API-5)
- Monthly cost vs revenue comparison in treasury (API-12)

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
