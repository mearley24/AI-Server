#!/usr/bin/env python3
"""Import ChatGPT conversation export into Cortex memory.

Usage:
    python3 tools/chatgpt_to_cortex.py /path/to/conversations.json

The script:
1. Parses the ChatGPT conversations.json export
2. Extracts messages from each conversation (tree walk)
3. Summarizes each conversation into a compact memory
4. Publishes each memory to cortex:learn via Redis
5. Logs progress and stats

Categories assigned based on conversation content:
- trading_knowledge: crypto, polymarket, trading, strategies
- business_operations: symphony, client, project, invoice, billing
- technical_architecture: docker, api, server, deploy, code
- product_design: website, ui, design, logo, branding
- personal_planning: goals, ideas, plans, vision
- general_knowledge: everything else
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://:d1fff1065992d132b000c01d6012fa52@redis:6379")


def extract_messages(conversation: dict) -> list[dict]:
    """Walk the message tree from current_node to root, return in chronological order."""
    messages = []
    current = conversation.get("current_node")
    mapping = conversation.get("mapping", {})

    while current:
        node = mapping.get(current, {})
        msg = node.get("message") if node else None
        if msg:
            author = msg.get("author", {}).get("role", "unknown")
            content = msg.get("content", {})
            parts = content.get("parts", []) if content.get("content_type") == "text" else []
            text = ""
            for part in parts:
                if isinstance(part, str) and part.strip():
                    text = part.strip()
                    break
            if text and author in ("user", "assistant"):
                messages.append({
                    "role": author,
                    "text": text,
                    "time": msg.get("create_time"),
                })
        current = node.get("parent") if node else None

    return list(reversed(messages))


def categorize(title: str, messages: list[dict]) -> tuple[str, list[str]]:
    """Assign a category and tags based on conversation content."""
    combined = (title + " " + " ".join(m["text"][:200] for m in messages[:5])).lower()

    categories = {
        "trading_knowledge": ["polymarket", "trading", "crypto", "kraken", "copytrade", "strategy", "bankroll", "whale", "arbitrage", "kalshi"],
        "business_operations": ["symphony", "client", "project", "invoice", "billing", "d-tools", "dtools", "proposal", "topletz", "job site"],
        "technical_architecture": ["docker", "compose", "api", "server", "deploy", "redis", "container", "cortex", "orchestrat"],
        "product_design": ["website", "symphonysh", "lovable", "ui", "design", "logo", "brand", "shirt", "qr code"],
        "personal_planning": ["goal", "vision", "plan", "idea", "roadmap", "priority", "milestone"],
    }

    tags = []
    best_cat = "general_knowledge"
    best_score = 0

    for cat, keywords in categories.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_cat = cat
        for kw in keywords:
            if kw in combined and kw not in tags:
                tags.append(kw)

    return best_cat, tags[:8]


def summarize_conversation(title: str, messages: list[dict], max_chars: int = 2000) -> str:
    """Create a compact summary of the conversation for memory storage."""
    lines = [f"Conversation: {title}"]

    # Include key user messages and assistant conclusions
    user_msgs = [m for m in messages if m["role"] == "user"]
    asst_msgs = [m for m in messages if m["role"] == "assistant"]

    # First user message (the ask)
    if user_msgs:
        lines.append(f"User asked: {user_msgs[0]['text'][:300]}")

    # Last assistant message (the conclusion/answer)
    if asst_msgs:
        lines.append(f"Result: {asst_msgs[-1]['text'][:500]}")

    # Key decisions or action items
    for msg in messages:
        text_lower = msg["text"].lower()
        if any(kw in text_lower for kw in ["decided", "going with", "let's do", "approved", "confirmed", "we should"]):
            lines.append(f"Decision: {msg['text'][:200]}")

    result = "\n".join(lines)
    return result[:max_chars]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/chatgpt_to_cortex.py /path/to/conversations.json")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"File not found: {json_path}")
        sys.exit(1)

    print(f"Loading {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        conversations = json.load(f)

    print(f"Found {len(conversations)} conversations")

    rc = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)
    rc.ping()
    print("Redis connected")

    stats = {"imported": 0, "skipped": 0, "errors": 0}

    for i, conv in enumerate(conversations):
        try:
            title = conv.get("title", "Untitled")
            create_time = conv.get("create_time")
            messages = extract_messages(conv)

            # Skip empty or very short conversations
            if len(messages) < 2:
                stats["skipped"] += 1
                continue

            # Skip system-only or trivial conversations
            user_text = " ".join(m["text"] for m in messages if m["role"] == "user")
            if len(user_text) < 50:
                stats["skipped"] += 1
                continue

            category, tags = categorize(title, messages)
            summary = summarize_conversation(title, messages)

            # Determine importance based on conversation length and content
            importance = 5
            if len(messages) > 20:
                importance = 7
            if len(messages) > 50:
                importance = 8
            if any(kw in title.lower() for kw in ["symphony", "bob", "trading", "strategy", "architecture"]):
                importance = min(importance + 1, 9)

            # Create the date string for metadata
            date_str = ""
            if create_time:
                date_str = datetime.fromtimestamp(create_time, tz=timezone.utc).strftime("%Y-%m-%d")

            payload = {
                "category": category,
                "title": f"[ChatGPT {date_str}] {title}",
                "content": summary,
                "source": "chatgpt_import",
                "confidence": 0.7,
                "importance": importance,
                "tags": tags + ["chatgpt_import"],
            }

            rc.publish("cortex:learn", json.dumps(payload))
            stats["imported"] += 1

            if (i + 1) % 50 == 0:
                print(f"  Processed {i+1}/{len(conversations)} — imported: {stats['imported']}, skipped: {stats['skipped']}")
                time.sleep(0.5)  # Don't flood Redis

            # Small delay to not overwhelm Cortex
            time.sleep(0.05)

        except Exception as e:
            stats["errors"] += 1
            print(f"  Error on conversation {i}: {e}")

    rc.close()
    print(f"\nDone! Imported: {stats['imported']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    print(f"Memories are now in Cortex. Query them at http://localhost:8102/memories")


if __name__ == "__main__":
    main()
