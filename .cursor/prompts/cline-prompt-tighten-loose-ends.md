> **Before starting:** Read CLAUDE.md at the repo root. Follow every rule in it, especially the Shell/Terminal section. No heredocs, no multi-line quoted strings, no inline interpreters, bounded commands only.

# Tighten Loose Ends — Finish Security Cleanup + Small Fixes

## Overview
The security-consolidation prompt partially landed but missed critical items in docker-compose.yml. This prompt finishes those plus additional small fixes. No new services, no architecture changes.

---

## Fix 0A — Remove Hardcoded Redis Password from docker-compose.yml

There are 11 lines in `docker-compose.yml` that still hardcode the Redis password. Replace every occurrence of:
```
REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
```
with:
```
REDIS_URL=${REDIS_URL}
```

This is on lines 102, 212, 284, 320, 413, 462, 498, 527, 583, 640, 700.

Also fix `scripts/imessage-server.py` line 103 — replace the hardcoded Redis URL with:
```python
os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
```

**Verification:** `grep -c "d19c9b0faebeee9927555eb8d6b28ec9" docker-compose.yml scripts/imessage-server.py` must return 0 for both files.

---

## Fix 0B — Remove Zoho Secret Default from docker-compose.yml

Find the line with:
```yaml
- ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET:-1be316a2f0448b2a62bc9659f5a4e01fc800936810}
```
Change to:
```yaml
- ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET}
```

Also find the Zoho Client ID default near it:
```yaml
- ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID:-1000.MO1TLB2AXFHH2YABDD2TSSIJ68SK5J}
```
Change to:
```yaml
- ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}
```

**Verification:** `grep "1be316a2f0448b2a62bc9659f5a4e01fc800936810" docker-compose.yml` must return nothing.

---

## Fix 0C — Remove Dead Services from docker-compose.yml

Remove the entire service block for each of these three services:

1. **remediator** — find `remediator:` as a top-level service key, delete everything from that line through the end of its block (before the next top-level service)
2. **knowledge-scanner** — same approach
3. **context-preprocessor** — same approach

**Verification:** `grep -c "remediator:\|knowledge-scanner:\|context-preprocessor:" docker-compose.yml` must return 0.

---

## Fix 1 — Update CLAUDE.md Service Table

The Docker Services Quick Reference table in `CLAUDE.md` has stale entries. Update it to match the current state of `docker-compose.yml`.

**Remove these rows:**
- `knowledge-scanner` (removed from compose)
- `context-preprocessor` (removed from compose)
- `remediator` (removed from compose)
- `openwebui` (already removed from compose)
- Any `browser-agent` reference (never existed)

**Add these missing rows:**
- `cortex-autobuilder | 8115 | Python | Bob/Betty research loop + topic scanning`
- `x-alpha-collector | — | Python | Monitors 40+ X accounts via RSSHub every 10 min`
- `rsshub | 1200 (internal) | Node.js | RSS feed proxy for X accounts`

**Fix these existing rows:**
- `client-portal` — remove "(no published host port)" note, it has a health endpoint
- Container count references — update any "20 containers" to the actual count after removals (count services in docker-compose.yml)

Also in the Repository Map comment at the top, update the docker-compose.yml container count.

---

## Fix 2 — Update .clinerules Service Table

Same changes as Fix 1 but in `.clinerules`. Remove knowledge-scanner, context-preprocessor, remediator, openwebui rows. Add cortex-autobuilder, x-alpha-collector, rsshub. Update container count.

---

## Fix 3 — Fix imessage-server _re Scoping

In `scripts/imessage-server.py`, `_re` is defined inside individual functions with `import re as _re` (around lines 399, 430, 702). This re-imports on every call.

Add at the top of the file (near the other imports):
```python
import re as _re
```

Then remove the three redundant `import re as _re` lines inside the functions.

---

## Fix 4 — Fix x-intake asyncio.new_event_loop() Anti-pattern

In `integrations/x_intake/main.py` around line 350, there is a call to `asyncio.new_event_loop()`. This creates a nested event loop inside an already-running async app.

Replace with direct `await` calls since x-intake is an async FastAPI app, or use `asyncio.get_event_loop().run_until_complete()` if the caller is synchronous. Check the calling context to determine the right fix.

---

## Fix 5 — Remove Redis Password from CLAUDE.md

`CLAUDE.md` still has the hardcoded Redis password in multiple places:
- The Redis section under "HARD RULES"
- The "Quick Commands" section
- The "Startup Health Checks" section
- The `.clinerules` file

After Fix 0A runs, the password is in `.env` only. Update both files:

1. Replace all instances of `d19c9b0faebeee9927555eb8d6b28ec9` with references to the env var
2. Redis CLI examples: change `redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9` to `redis-cli -a "$REDIS_PASSWORD"`
3. Redis URL examples: change to `redis://<from-env>@redis:6379` with a note "(credentials in .env, never hardcode)"
4. In the Security section, remove the line about "Redis password is in this file for operational convenience"

**Verification:** `grep -c "d19c9b0faebeee9927555eb8d6b28ec9" CLAUDE.md .clinerules` must return 0 for both files.

---

## Fix 6 — Update STATUS_REPORT.md

Update the "Now" and "Next" sections:

**Now section** — add completion notes:
- KRAKEN_SECRET: "Still pending Matt action"
- Fund Polymarket wallet: "Still pending Matt action ($750+ in positions as of April 12)"

**Next section** — mark done:
- "x-intake listener watchdog" — done, implemented at line 658 of x_intake/main.py
- "Fix CLAUDE.md service table" — done by this prompt

**Add to Done section:**
- Security consolidation (hardcoded secrets removed, 3 orphaned services merged/removed, PORTS.md created)
- CLAUDE.md heredoc/dquote rules added
- Cortex autobuilder deployed (Bob/Betty research loop + topic scanning)
- Symphony ops tab added to cortex dashboard
- Mobile API replaced with slim gateway
- ChatGPT cortex import tool created

---

## Fix 7 — Clean Up Supabase Dead References

In `.env.example`, if there are `SUPABASE_*` variables, add a comment above them:
```
## SUPABASE -- UNUSED by any Docker service. Safe to remove. Kept for symphonysh migration reference.
```

---

## Git Commit

```
git add -A
git commit -m "finish security cleanup: remove secrets from compose, kill dead services, update docs and status"
git push origin main
```
