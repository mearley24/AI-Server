"""Scan topics for the cortex-autobuilder topic scanner loop.

Each topic is queried on its own frequency_hours schedule.
Trading topics run aggressively (every 1 h); slower industry topics
run every 8–12 h to stay within API budget.
"""

SCAN_TOPICS = [
    {
        "query": "latest Polymarket prediction market trading strategies edges techniques Reddit",
        "category": "trading",
        "frequency_hours": 1,
    },
    {
        "query": "latest crypto market making strategies DeFi automated trading bots Reddit",
        "category": "trading",
        "frequency_hours": 1,
    },
    {
        "query": "Polymarket new markets high volume emerging events today",
        "category": "trading",
        "frequency_hours": 1,
    },
    {
        "query": "latest AI agent orchestration frameworks tools multi-agent systems",
        "category": "ai_tools",
        "frequency_hours": 2,
    },
    {
        "query": "latest AI coding assistants developer tools automation 2026",
        "category": "ai_tools",
        "frequency_hours": 2,
    },
    {
        "query": "latest smart home automation Control4 Savant Crestron trends innovations 2026",
        "category": "smart_home",
        "frequency_hours": 8,
    },
    {
        "query": "latest RFID NFC IoT tracking innovations real-time location systems",
        "category": "iot",
        "frequency_hours": 12,
    },
]

SCAN_PROCESS_PROMPT = """You are a knowledge extraction assistant. Given raw search results, extract actionable insights.

For each distinct insight, return a JSON object with:
- "topic": short topic title (max 80 chars)
- "category": one of: trading, smart_home, iot, ai_tools, business, general
- "insight": the actionable insight (2-3 sentences)
- "source_summary": brief summary of where this info came from
- "relevance_score": 1-10 rating of relevance to a tech entrepreneur running a smart home integration business who also trades crypto and prediction markets

Return a JSON array of objects. Return ONLY valid JSON, no markdown."""
