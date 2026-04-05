# Fix: X/Twitter Intake Pipeline — Bridge → Redis → x-intake → Reply

The X/Twitter intake pipeline is broken end-to-end. When I send X links via iMessage, the bridge processes them locally via `ask_openclaw()` → `research_link()` but NEVER publishes them to Redis for the `x-intake` container. Three bugs to fix:

## Bug A: iMessage bridge doesn't publish to Redis (`scripts/imessage-server.py`)

The `monitor_loop()` function (around line 1220) receives messages and sends them straight to `ask_openclaw()`. It never publishes to Redis `events:imessage` — the channel that `x-intake` subscribes to.

**Fix**: Add Redis publishing to `monitor_loop()`. Before calling `ask_openclaw()`, publish every incoming message to Redis:

1. At the top of the file (after existing imports), add:
```python
import redis as _redis_lib

_REDIS_URL = os.environ.get("REDIS_URL", "redis://:d19c9b0faebeee9927555eb8d6b28ec9@127.0.0.1:6379")
_redis_pub = None

def _get_redis_pub():
    global _redis_pub
    if _redis_pub is None:
        try:
            _redis_pub = _redis_lib.from_url(_REDIS_URL, decode_responses=True)
            _redis_pub.ping()
            log.info("[redis] Connected for publish")
        except Exception as e:
            log.warning("[redis] Publish connection failed: %s", e)
            _redis_pub = None
    return _redis_pub
```

2. In `monitor_loop()`, right after `log.info("[monitor] Received: %s", text)` and BEFORE `response = ask_openclaw(text)`, add:
```python
# Publish to Redis for x-intake and other downstream consumers
_rpub = _get_redis_pub()
if _rpub:
    try:
        _rpub.publish("events:imessage", json.dumps({
            "text": text,
            "from": msg.get("from", REPLY_TO),
            "timestamp": time.time(),
        }))
    except Exception as _re:
        log.warning("[redis] Publish failed: %s", _re)
```

3. In `ask_openclaw()`, make X/Twitter URLs skip local processing so x-intake handles them exclusively. In the URL detection block (around line 795), where it does `if urls:`, change to:
```python
if urls:
    import re as _re
    x_pattern = _re.compile(r'https?://(?:x\.com|twitter\.com)/.+/status/', _re.I)
    x_urls = [u for u in urls if x_pattern.search(u)]
    non_x_urls = [u for u in urls if not x_pattern.search(u)]
    
    if x_urls and not non_x_urls:
        return "Analyzing your X link(s) — detailed analysis incoming shortly via x-intake."
    
    if non_x_urls:
        context = _re.sub(r'https?://[^\s<>"]+', '', message).strip()
        results = []
        for url in non_x_urls[:2]:
            results.append(research_link(url, context))
        if x_urls:
            results.append("X links are being analyzed separately — results incoming.")
        return "\n\n---\n\n".join(results)
```

## Bug B: x-intake replies to wrong endpoint (`integrations/x_intake/main.py`)

The `_send_reply()` function posts to `{IMESSAGE_BRIDGE_URL}/send` but the bridge's HTTP handler only serves the root path `/`. Also sends `{"text": text}` but the bridge expects `"message"` key (it accepts "body", "text", or "message" but be explicit).

**Fix**: In `_send_reply()` (around line 78), change:
```python
await client.post(f"{IMESSAGE_BRIDGE_URL}/send", json={"text": text})
```
to:
```python
await client.post(IMESSAGE_BRIDGE_URL, json={"message": text})
```

## Bug C: Add `redis` to bridge requirements

The bridge runs natively on macOS (not Docker). Ensure the `redis` Python package is available. On Bob run: `pip3 install redis`

## Files to modify
- `scripts/imessage-server.py`
- `integrations/x_intake/main.py`
