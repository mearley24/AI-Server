# Fix X-Intake Import Error + Email Monitor Classification Noise

**Priority:** Run NOW — both issues are actively producing bad notifications on Bob.
**Two bugs, independent fixes. Do them in order.**

---

## Read First

- `integrations/x_intake/main.py` — the FastAPI service (contains the import error)
- `integrations/x_intake/analyzer.py` — uses relative import `from .post_fetcher import PostData`
- `integrations/x_intake/post_fetcher.py` — the fetcher module
- `integrations/x_intake/pipeline.py` — the pipeline module (has `REDIS_CHANNEL_OUT`, `publish_to_redis`, `_get_redis`)
- `integrations/x_intake/bridge.py` — imports from pipeline
- `email-monitor/monitor.py` — email classification + digest builder
- `openclaw/orchestrator.py` — builds the "You have N new email(s)" iMessage digest

---

## Bug 1: X-Intake — "pipeline modules not importable"

### Root Cause

In `integrations/x_intake/main.py`, the `_analyze_url()` function tries:
```python
from post_fetcher import PostFetcher
from analyzer import PostAnalyzer
```

This flat import fails because `analyzer.py` uses a relative import internally:
```python
from .post_fetcher import PostData
```

A relative import (`from .something`) only works when the module is loaded as part of a package. When main.py does `from analyzer import PostAnalyzer`, Python loads analyzer.py as a standalone module (not as part of `integrations.x_intake`), so the relative `from .post_fetcher` fails with `ImportError: attempted relative import in non-package`.

The fallback then tries:
```python
from integrations.x_intake.post_fetcher import PostFetcher
from integrations.x_intake.analyzer import PostAnalyzer
```

This also fails because inside the Docker container, the code is at `/app/` (not `/app/integrations/x_intake/`). There's no `integrations` parent package.

### Fix

In `integrations/x_intake/main.py`, replace the entire import block inside `_analyze_url()`:

```python
async def _analyze_url(url: str) -> dict:
    """Run the existing pipeline on a single tweet URL."""
    try:
        from post_fetcher import PostFetcher
        from analyzer import PostAnalyzer
    except ImportError:
        try:
            from integrations.x_intake.post_fetcher import PostFetcher
            from integrations.x_intake.analyzer import PostAnalyzer
        except ImportError:
            return {"error": "pipeline modules not importable", "url": url}
```

Replace with:

```python
async def _analyze_url(url: str) -> dict:
    """Run the existing pipeline on a single tweet URL."""
    try:
        # Inside Docker container: code is at /app/, flat imports work
        # BUT analyzer.py uses relative imports (from .post_fetcher),
        # so we must import it as a package submodule.
        import importlib
        import sys

        # Ensure /app is on path
        app_dir = os.path.dirname(os.path.abspath(__file__))
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)

        # Try package-style import by making current dir a package
        # The __init__.py already exists and exports these
        if "post_fetcher" in sys.modules:
            PostFetcher = sys.modules["post_fetcher"].PostFetcher
        else:
            # Rewrite relative imports: load post_fetcher first as flat module,
            # then patch analyzer's reference
            import post_fetcher as _pf
            PostFetcher = _pf.PostFetcher

        # For analyzer, we need to handle the relative import.
        # Temporarily make this directory look like a package.
        _pkg_name = "x_intake_pkg"
        if _pkg_name not in sys.modules:
            import types
            pkg = types.ModuleType(_pkg_name)
            pkg.__path__ = [app_dir]
            pkg.__package__ = _pkg_name
            sys.modules[_pkg_name] = pkg

        # Now load analyzer as a submodule of our fake package
        if "x_intake_pkg.analyzer" in sys.modules:
            PostAnalyzer = sys.modules["x_intake_pkg.analyzer"].PostAnalyzer
        else:
            # Simpler approach: just fix the relative import at source
            pass
    except Exception:
        pass
```

**Actually — the simplest fix is to change `analyzer.py` to use a conditional import instead of a relative one.** This is cleaner and doesn't require import hacks.

### Real Fix — change analyzer.py

In `integrations/x_intake/analyzer.py`, replace:
```python
from .post_fetcher import PostData
```

With:
```python
try:
    from .post_fetcher import PostData
except ImportError:
    from post_fetcher import PostData
```

This makes analyzer.py work both as a package submodule (when imported from the repo root) AND as a flat module (when running inside the Docker container at /app/).

Then in `integrations/x_intake/main.py`, the existing first try block will work:
```python
from post_fetcher import PostFetcher
from analyzer import PostAnalyzer
```

### Also fix: bridge.py has the same pattern

In `integrations/x_intake/bridge.py`, the import:
```python
from integrations.x_intake.pipeline import (
    REDIS_CHANNEL_OUT,
    publish_to_redis,
    _get_redis,
)
```

This will fail inside Docker. Add a fallback:
```python
try:
    from integrations.x_intake.pipeline import (
        REDIS_CHANNEL_OUT,
        publish_to_redis,
        _get_redis,
    )
except ImportError:
    from pipeline import (
        REDIS_CHANNEL_OUT,
        publish_to_redis,
        _get_redis,
    )
```

### Also fix: pipeline.py has the same pattern

In `integrations/x_intake/pipeline.py`:
```python
from integrations.x_intake.post_fetcher import PostFetcher, find_tweet_urls, FetchError
from integrations.x_intake.analyzer import PostAnalyzer, AnalysisResult
```

Add fallback:
```python
try:
    from integrations.x_intake.post_fetcher import PostFetcher, find_tweet_urls, FetchError
    from integrations.x_intake.analyzer import PostAnalyzer, AnalysisResult
except ImportError:
    from post_fetcher import PostFetcher, find_tweet_urls, FetchError
    from analyzer import PostAnalyzer, AnalysisResult
```

### Also fix: __init__.py has relative imports that break in Docker

In `integrations/x_intake/__init__.py`:
```python
from .post_fetcher import PostFetcher, PostData
from .analyzer import PostAnalyzer, AnalysisResult
from .bridge import XIntakeBridge
from .pipeline import XIntakePipeline
```

This will fail when main.py does `sys.path.insert(0, os.path.dirname(__file__))` and something triggers __init__.py. Wrap it:

```python
try:
    from .post_fetcher import PostFetcher, PostData
    from .analyzer import PostAnalyzer, AnalysisResult
    from .bridge import XIntakeBridge
    from .pipeline import XIntakePipeline
except ImportError:
    # Running inside Docker container where files are flat in /app/
    try:
        from post_fetcher import PostFetcher, PostData
        from analyzer import PostAnalyzer, AnalysisResult
        from bridge import XIntakeBridge
        from pipeline import XIntakePipeline
    except ImportError:
        pass  # Some modules may not be needed in all contexts
```

### After fixing all imports, rebuild:
```bash
docker compose up -d --build x-intake
sleep 5
docker logs x-intake --tail 10
curl -s http://127.0.0.1:8101/health
# Test the analyze endpoint
curl -s -X POST http://127.0.0.1:8101/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/elonmusk/status/1234567890"}' | python3 -m json.tool
```

The test should return analysis data, NOT `{"error": "pipeline modules not importable"}`.

### Also fix: x-intake Redis URL

The docker-compose has a wrong Redis password for x-intake:
```yaml
REDIS_URL=${REDIS_URL:-redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379}
```

Check if this matches the actual REDIS_PASSWORD in .env. If .env has REDIS_URL set, this default won't matter. But if not, this hardcoded fallback password may be wrong (the correct one is `d1fff1065992d132b000c01d6012fa52`).

**Fix:** Change the default to not include a password — rely on the .env REDIS_URL:
```yaml
REDIS_URL=${REDIS_URL}
```

Or ensure .env has `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379` and all services inherit it.

---

## Bug 2: Email Monitor — Cursor Prompt Spam + Marketing Noise in Digest

### Problem A: "Re: Cursor Prompt" classified as CLIENT_INQUIRY

Bob sends himself emails via Cursor (subject: "Cursor Prompt"). Replies to those emails ("Re: Cursor Prompt") are being classified as `CLIENT_INQUIRY` because the keyword "inquiry" isn't matching — but some other keyword path or default is triggering it. Most likely the sender is Bob himself (bob@symphonysh.com) and the email contains text that matches `CLIENT_INQUIRY` keywords like "interested in" or "would like to discuss" from the Cursor prompt content.

**Fix:** In `email-monitor/monitor.py`, in the `categorize_email()` function, add a self-email check at the very top, BEFORE all other classification:

```python
def categorize_email(subject: str, sender: str, body_snippet: str = "") -> tuple[str, str]:
    """
    Categorize an email: self-emails, active clients, routed senders, marketing patterns, then keywords.
    """
    # Skip self-sent emails (Cursor prompts, test emails, internal automation)
    email_addr = _sender_email_addr(sender)
    own_addresses = {
        "bob@symphonysh.com",
        "admin@symphonysh.com",
        "noreply@symphonysh.com",
    }
    own_addresses.add(os.environ.get("ZOHO_EMAIL", "").lower())
    if email_addr and email_addr.lower() in own_addresses:
        return "INTERNAL", "none"

    # Also skip "Re: Cursor Prompt" by subject pattern
    subject_lower = (subject or "").lower().strip()
    if "cursor prompt" in subject_lower:
        return "INTERNAL", "none"
```

Then add `"INTERNAL"` to the skip function:
```python
def _skip_notification_noise(category: str, priority: str) -> bool:
    """Skip LLM analysis and Redis publish for marketing / no-priority noise."""
    if category in ("MARKETING", "INTERNAL"):
        return True
    if (priority or "").lower() == "none":
        return True
    return False
```

And in `openclaw/orchestrator.py`, update `_orchestrator_skip_email()`:
```python
def _orchestrator_skip_email(em: dict) -> bool:
    """Skip decision logging / notifications for marketing, internal, and low-signal vendor mail."""
    cat = (em.get("category") or "GENERAL").upper()
    subj = (em.get("subject") or "").lower()
    if cat in ("MARKETING", "INTERNAL"):
        return True
    if cat == "VENDOR":
        if not any(kw in subj for kw in ("order", "shipping", "tracking", "invoice")):
            return True
    return False
```

### Problem B: Marketing noise still showing in digest

The digest at line ~451 of `openclaw/orchestrator.py` shows ALL non-skipped emails, including GENERAL ones that are clearly marketing (Dropbox, Amazon, Edmunds, xTool, Crexi, The TV Shield, Raouf Chebri). These get through because:

1. They're not caught by the marketing patterns in routing_config.json
2. They don't match any MARKETING keywords
3. They fall through to GENERAL

**Fix 1:** Add missing marketing patterns to `email-monitor/routing_config.json`. In the `marketing_patterns` array, add:

```json
"dropbox.com",
"amazon.com",
"edmunds.com",
"xtool.com",
"thetvshield.com",
"tv shield",
"savings are here",
"member's day",
"go-to brands",
"cars with the most",
"best suv deals",
"happy easter",
"reviewer appreciation",
"replit.com",
"product updates",
"recommended for you",
"new properties recommended"
```

**Fix 2:** In the orchestrator digest (line ~451 of `openclaw/orchestrator.py`), skip GENERAL/low-priority emails from the summary entirely — they're noise. Only show actionable categories:

Replace:
```python
            # Send a summary digest of ALL new emails
            actionable = [em for em in new_emails if not _orchestrator_skip_email(em)]
            noise_n = len(new_emails) - len(actionable)
            summary_lines = [f"You have {len(new_emails)} new email(s)" + (f" ({noise_n} filtered as marketing/vendor noise)" if noise_n else "") + ":"]
            for em in actionable:
                sender = em.get("sender_name") or em.get("sender", "unknown")
                subject = em.get("subject", "(no subject)")
                category = em.get("category", "GENERAL")
                summary_lines.append(f"  - [{category}] {sender}: {subject}")

            await self.notify("email", "\n".join(summary_lines))
```

With:
```python
            # Send a summary digest — only actionable emails, suppress noise
            actionable = [em for em in new_emails if not _orchestrator_skip_email(em)]
            noise_n = len(new_emails) - len(actionable)

            # Further split: important vs general noise
            IMPORTANT_CATS = {"BID_INVITE", "CLIENT_INQUIRY", "ACTIVE_CLIENT",
                              "FOLLOW_UP_NEEDED", "SCHEDULING", "INVOICE"}
            important = [em for em in actionable if em.get("category", "GENERAL") in IMPORTANT_CATS]
            general = [em for em in actionable if em.get("category", "GENERAL") not in IMPORTANT_CATS]

            if not important and not general:
                # Everything was noise — don't send a digest at all
                logger.info("All %d new emails were noise/marketing — no digest sent", len(new_emails))
            else:
                total_filtered = noise_n + len(general)
                header = f"You have {len(important)} actionable email(s)"
                if total_filtered:
                    header += f" ({total_filtered} filtered)"
                summary_lines = [header + ":"]

                for em in important:
                    sender = em.get("sender_name") or em.get("sender", "unknown")
                    subject = em.get("subject", "(no subject)")
                    category = em.get("category", "GENERAL")
                    summary_lines.append(f"  - [{category}] {sender}: {subject}")

                # Show general only as a count, not line-by-line
                if general:
                    summary_lines.append(f"  + {len(general)} other non-urgent email(s)")

                await self.notify("email", "\n".join(summary_lines))
```

This means the iMessage digest will look like:
```
You have 2 actionable email(s) (23 filtered):
  - [BID_INVITE] CE Pro: What Makes a Good Business Partner
  - [CLIENT_INQUIRY] John Smith: Smart home estimate request
  + 3 other non-urgent email(s)
```

Instead of the current 25-line dump.

### After both fixes, rebuild:
```bash
docker compose up -d --build email-monitor x-intake
# OpenClaw needs restart too (orchestrator.py changed)
docker compose up -d --force-recreate openclaw
```

---

## Verification

```bash
# X-Intake: should NOT return "pipeline modules not importable"
curl -s -X POST http://127.0.0.1:8101/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/test/status/1"}' | python3 -m json.tool

# Email Monitor: check classification
docker exec email-monitor python3 -c "
from monitor import categorize_email
# Self-email should be INTERNAL
print(categorize_email('Re: Cursor Prompt', 'bob@symphonysh.com', 'test'))
# Marketing should be MARKETING
print(categorize_email('Happy Easter Sale', 'news@thetvshield.com', 'unsubscribe'))
# Real client should still be CLIENT_INQUIRY
print(categorize_email('Smart home estimate', 'john@gmail.com', 'interested in automation'))
"
# Expected:
#   ('INTERNAL', 'none')
#   ('MARKETING', 'none')
#   ('CLIENT_INQUIRY', 'high')
```

---

## Bug 3: Intel Alert — Raw JSON Dumped to iMessage

### Problem

The intel_feeds `signal_aggregator.py` publishes critical alerts to `notifications:trading` with this payload:
```json
{"type": "intel_alert", "urgency": "critical", "source": "polymarket:odds_movement", "summary": "Odds movement [UP 30.0%]...", "relevance_score": 100, ...}
```

The notification-hub's `redis_subscriber()` (in `notification-hub/main.py`) receives it and does:
```python
title = data.get("title", data.get("type", "Notification"))
body = data.get("body", data.get("message", json.dumps(data)))
```

The payload has no `title`, `body`, or `message` key. So:
- `title` = `"intel_alert"` (from the `type` field)
- `body` = `json.dumps(data)` — the entire raw JSON blob

This gets sent as-is to iMessage. Matt sees raw JSON.

### Fix Option A — Fix at source (signal_aggregator.py)

In `integrations/intel_feeds/signal_aggregator.py`, around line 291, where the notification dict is built, add `title` and `body` keys that the notification-hub expects:

```python
        if relevance >= self.critical_threshold:
            # Format human-readable alert for notification-hub
            urgency_icon = {"critical": "🚨", "high": "⚠️", "medium": "📊"}.get(urgency, "📌")
            source_label = signal.get("source", "unknown").replace("polymarket:", "").replace("_", " ").title()

            notification = {
                "type": "intel_alert",
                "title": f"{urgency_icon} Intel Alert: {source_label}",
                "body": summary,
                "urgency": urgency,
                "priority": "high" if urgency == "critical" else "normal",
                "source": signal.get("source", ""),
                "summary": summary,
                "relevance_score": relevance,
                "category": signal.get("category", ""),
                "markets_affected": signal.get("markets_affected", []),
                "timestamp": signal.get("timestamp", ""),
            }
```

This way the notification-hub's existing `data.get("title")` and `data.get("body")` will find real values instead of falling through to raw JSON.

### Fix Option B — Fix at receiver (notification-hub/main.py)

In `notification-hub/main.py`, in the `redis_subscriber()` function, add intel_alert formatting before the generic fallback. Around line 238:

Replace:
```python
                    title = data.get("title", data.get("type", "Notification"))
                    body = data.get("body", data.get("message", json.dumps(data)))
                    priority = data.get("priority", "normal")
                    await dispatch(title, body, priority, source=channel)
```

With:
```python
                    # Format known notification types into human-readable messages
                    msg_type = data.get("type", "")
                    if msg_type == "intel_alert":
                        urgency = data.get("urgency", "medium")
                        icon = {"critical": "🚨", "high": "⚠️", "medium": "📊"}.get(urgency, "📌")
                        source_label = data.get("source", "unknown").replace("polymarket:", "").replace("_", " ").title()
                        title = f"{icon} Intel Alert: {source_label}"
                        body = data.get("summary", "No summary available")
                        markets = data.get("markets_affected", [])
                        if markets:
                            body += f"\nMarkets: {len(markets)} affected"
                        body += f"\nRelevance: {data.get('relevance_score', 'N/A')}%"
                        priority = "high" if urgency == "critical" else "normal"
                    else:
                        title = data.get("title", data.get("type", "Notification"))
                        body = data.get("body", data.get("message", json.dumps(data)))
                        priority = data.get("priority", "normal")
                    await dispatch(title, body, priority, source=channel)
```

### Recommended: Do BOTH fixes

Fix A ensures the payload is well-formed at the source. Fix B ensures the notification-hub never sends raw JSON for any known type — defense in depth.

### Expected iMessage after fix:
```
🚨 Intel Alert: Odds Movement
Odds movement [UP 30.0%] on "US x Iran ceasefire by April 15?" 0.10 → 0.13
Relevance: 100%
```

Instead of raw JSON.

### Rebuild:
```bash
docker compose up -d --build intel-feeds notification-hub
```

---

## Rules

- **Read before writing.** Every file listed above must be read before editing.
- **Config change = rebuild.** `docker compose up -d --build email-monitor x-intake intel-feeds notification-hub` then `--force-recreate openclaw`.
- **No secrets in code.** All credentials from `.env` via `os.environ.get()`.
- **Test after each fix.** Don't batch — fix x-intake, test, then fix email, test, then fix intel alerts, test.
