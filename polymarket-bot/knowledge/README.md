# Knowledge Pipeline — Bob's Trading Brain

Bob's continuous learning system: a git-versioned, human-readable markdown knowledge graph for trading intelligence.

## How It Works

```
Raw Input → Extract → Classify → Store → Link → Log
```

1. **Raw intel** comes in via API endpoint, trade results, or manual drops
2. **Claude extracts** structured knowledge (title, type, tags, key facts, action items)
3. **Classifier** routes it to the right knowledge directory (strategies, markets, wallets, research)
4. **Storage** creates or appends to the appropriate markdown file
5. **Linker** adds `[[wikilinks]]` cross-references between related files
6. **Logger** appends to the daily learning log

## Directory Structure

```
knowledge/
├── ingest.py           # Ingestion pipeline — processes raw intel via Claude API
├── query.py            # Query interface — strategies ask questions
├── digest.py           # Daily digest — summarizes today's learnings
├── sources/            # Raw intel drops (ephemeral, processed → archived)
├── strategies/         # Strategy-specific knowledge
│   ├── latency_patterns.md
│   ├── weather_edges.md
│   ├── fed_calendar.md
│   ├── sports_patterns.md
│   ├── crypto_correlations.md
│   └── mean_reversion_params.md
├── markets/            # Market-specific intel
│   ├── kalshi_markets.md
│   ├── polymarket_markets.md
│   └── crypto_tokens.md
├── wallets/            # Tracked whale wallet patterns
│   ├── _index.md
│   ├── latency_167m.md
│   ├── sports_619k.md
│   └── coldmath_80k.md
├── research/           # Longer-form research
│   ├── moon_dev_rbi.md
│   └── marginal_polytope.md
└── log/                # Daily learning entries
    └── YYYY-MM-DD.md
```

## Knowledge File Format

Every file follows this template:

```markdown
# [Title]

> Type: strategy | market | wallet | research | pattern
> Tags: [comma-separated]
> Created: YYYY-MM-DD
> Updated: YYYY-MM-DD
> Confidence: high | medium | low
> Status: active | stale | archived

## Summary
1-2 sentence executive summary.

## Key Facts
- Fact 1
- Fact 2

## Links
- Related: [[other_file.md]]

## Raw Notes
Detailed notes.

## Action Items
- [ ] Things to track or implement
```

## API Endpoints

```bash
# Ingest new knowledge
curl -X POST localhost:8430/knowledge/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text": "BTC flash crash pattern detected...", "source_url": "https://..."}'

# Ingest from URL
curl -X POST localhost:8430/knowledge/ingest \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://..."}'

# Search knowledge
curl 'localhost:8430/knowledge/search?q=weather&type=strategy'

# Get strategy knowledge
curl localhost:8430/knowledge/strategy/latency_patterns

# Get today's digest
curl localhost:8430/knowledge/digest

# Get recent learnings
curl 'localhost:8430/knowledge/recent?days=7'
```

## Usage from Strategies

```python
from knowledge.query import KnowledgeQuery

knowledge = KnowledgeQuery()

# Get strategy-specific knowledge
intel = knowledge.get_strategy_knowledge("latency_patterns")

# Search across all knowledge
results = knowledge.search("BTC momentum", ktype="strategy")

# Get market intel
kalshi_info = knowledge.get_market_intel("kalshi")

# Get wallet patterns
whale_data = knowledge.get_wallet_patterns("latency")
```

## Why Markdown (Not Vector Embeddings)

- **Human-readable** — open any file and see exactly what Bob knows
- **Git-versioned** — every knowledge update tracked, rollback possible
- **Agent-accessible** — AI reads/writes directly, no middleware
- **Structured** — types, tags, `[[wikilinks]]` between concepts
- **Portable** — works with Obsidian, VS Code, any text editor
