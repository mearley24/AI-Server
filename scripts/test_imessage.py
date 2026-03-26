#!/usr/bin/env python3
"""Test iMessage notification pipeline.

Sends a test message through the full notification chain:
  1. Python → Redis pub/sub (notifications:trading channel)
  2. notification-hub picks it up → dispatches via iMessage bridge
  3. iMessage bridge → AppleScript → Messages.app → your phone

Works with both old (pre-refactor) and new code — uses Redis pub/sub
directly, which is the transport layer both versions rely on.

Usage:
    # From Bob (inside Docker network):
    docker exec -it polymarket-bot python scripts/test_imessage.py

    # Or standalone (if Redis is reachable):
    REDIS_URL=redis://localhost:6379 python scripts/test_imessage.py

    # Custom message:
    python scripts/test_imessage.py "Your custom message here"

    # Via the HTTP API (notification-hub must be running):
    curl -X POST http://localhost:8095/notify \
         -H 'Content-Type: application/json' \
         -d '{"title": "Test", "body": "Hello from curl"}'

    # Via the bot API (polymarket-bot must be running):
    curl -X POST http://localhost:8080/notifications/test \
         -H 'Content-Type: application/json' \
         -d '{"message": "Hello from bot API"}'
"""

import json
import os
import sys
from datetime import datetime


def send_via_redis(message: str) -> bool:
    """Send directly via Redis pub/sub (same path as IMessageNotifier)."""
    try:
        import redis
    except ImportError:
        print("ERROR: redis package not installed. Run: pip install redis")
        return False

    url = os.environ.get("REDIS_URL", "redis://redis:6379")
    print(f"  Redis URL: {url}")

    try:
        r = redis.from_url(url, decode_responses=True, socket_timeout=5)
        r.ping()
        print("  Redis: connected")
    except Exception as e:
        # Try localhost fallback (running outside Docker)
        url = "redis://localhost:6379"
        print(f"  Retrying with {url}...")
        try:
            r = redis.from_url(url, decode_responses=True, socket_timeout=5)
            r.ping()
            print("  Redis: connected (localhost)")
        except Exception as e2:
            print(f"  ERROR: Cannot connect to Redis: {e2}")
            return False

    payload = json.dumps({
        "title": "🧪 iMessage Test",
        "body": message,
        "priority": "normal",
    })

    channel = "notifications:trading"
    listeners = r.publish(channel, payload)
    print(f"  Published to {channel} ({listeners} listener(s))")

    if listeners == 0:
        print("  WARNING: No listeners on Redis channel.")
        print("           Is notification-hub running? Check: docker ps | grep notification-hub")
        return False

    return True


def send_via_http(message: str) -> bool:
    """Send via notification-hub HTTP API (backup method)."""
    try:
        import httpx
    except ImportError:
        try:
            from urllib.request import Request, urlopen
            import json as _json

            # Try Docker internal URL first, then localhost
            for base in ["http://notification-hub:8095", "http://localhost:8095"]:
                url = f"{base}/notify"
                try:
                    req = Request(
                        url,
                        data=_json.dumps({"title": "🧪 iMessage Test", "body": message}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    resp = urlopen(req, timeout=5)
                    result = _json.loads(resp.read())
                    print(f"  HTTP ({url}): {result}")
                    return result.get("status") == "sent"
                except Exception:
                    continue
            print("  ERROR: notification-hub not reachable on any URL")
            return False
        except Exception as e:
            print(f"  ERROR: {e}")
            return False

    for base in ["http://notification-hub:8095", "http://localhost:8095"]:
        url = f"{base}/notify"
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.post(url, json={"title": "🧪 iMessage Test", "body": message})
                result = resp.json()
                print(f"  HTTP ({url}): {result}")
                return result.get("status") == "sent"
        except Exception:
            continue

    print("  ERROR: notification-hub not reachable on any URL")
    return False


def main():
    timestamp = datetime.now().strftime("%I:%M:%S %p")
    custom_msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    message = custom_msg or f"Test notification at {timestamp}. If you see this, iMessage pipeline is working."

    print(f"Testing iMessage pipeline...")
    print(f"Message: {message}")
    print()

    # Method 1: Redis pub/sub (primary — this is how the bot sends notifications)
    print("[1] Redis pub/sub (primary path):")
    redis_ok = send_via_redis(message)
    print(f"  Result: {'OK' if redis_ok else 'FAILED'}")
    print()

    # Method 2: HTTP API (backup — notification-hub REST endpoint)
    print("[2] HTTP API (backup path):")
    http_ok = send_via_http(message)
    print(f"  Result: {'OK' if http_ok else 'FAILED'}")
    print()

    # Summary
    if redis_ok or http_ok:
        print("SUCCESS — message sent. Check your phone in ~5 seconds.")
        print()
        print("If you don't receive it, check:")
        print("  1. iMessage bridge running: launchctl list | grep imessage")
        print("  2. notification-hub channel: docker logs notification-hub --tail 10")
        print("  3. NOTIFICATION_CHANNEL env var is 'imessage' (not 'console')")
    else:
        print("FAILED — could not send via any method.")
        print()
        print("Troubleshooting:")
        print("  1. Is Redis running?  docker ps | grep redis")
        print("  2. Is notification-hub running?  docker ps | grep notification-hub")
        print("  3. Try: curl http://localhost:8095/health")
        sys.exit(1)


if __name__ == "__main__":
    main()
