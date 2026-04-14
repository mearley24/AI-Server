> **Before starting:** Read CLAUDE.md at the repo root. Follow every rule in it, especially the Shell/Terminal section. No heredocs, no multi-line quoted strings, no inline interpreters, bounded commands only.

# Tighten Loose Ends — Small Fixes Across the Stack

## Overview
Seven small, independent fixes. Each is 1-10 lines of code. No new services, no architecture changes.

---

## Fix 1 — Update CLAUDE.md Service Table

The Docker Services Quick Reference table in `CLAUDE.md` has stale entries. Update it to match the current state of `docker-compose.yml`.

**Remove these rows:**
- `knowledge-scanner` (being removed by security-consolidation prompt)
- `context-preprocessor` (being removed by security-consolidation prompt)
- `remediator` (being removed by security-consolidation prompt)
- `openwebui` (already removed from compose)
- Any `browser-agent` reference (never existed in compose)

**Add these missing rows:**
- `cortex-autobuilder | 8115 | Python | Bob/Betty research loop + topic scanning`
- `x-alpha-collector | — | Python | Monitors 40+ X accounts via RSSHub every 10 min`
- `rsshub | 1200 (internal) | Node.js | RSS feed proxy for X accounts`

**Fix these existing rows:**
- `client-portal` — remove "(no published host port)" note, it does have a health endpoint now
- Container count references — update any mention of "20 containers" to reflect the actual count after removals (should be ~17-18, count from docker-compose.yml)

Also in the Repository Map comment at the top:
- Change `docker-compose.yml     # 20 containers` to the correct count

---

## Fix 2 — Update .clinerules Service Table

Same changes as Fix 1 but in `.clinerules`. Remove knowledge-scanner, context-preprocessor, remediator, openwebui rows. Add cortex-autobuilder, x-alpha-collector, rsshub. Update container count.

---

## Fix 3 — Fix imessage-server _re Scoping

In `scripts/imessage-server.py`, the `_re` variable is defined inside individual functions with `import re as _re` (lines 399, 430, 702). This works but is wasteful — it re-imports on every call.

Add at the top of the file (near the other imports around line 1-40):

```python
import re as _re
```

Then remove the three redundant `import re as _re` lines inside the functions (lines 399, 430, 702). The functions will use the module-level import instead.

---

## Fix 4 — Fix x-intake `asyncio.new_event_loop()` Anti-pattern

In `integrations/x_intake/main.py` around line 350, there is a call to `asyncio.new_event_loop()`. This creates a nested event loop which can cause issues inside an already-running async app.

Find the function that uses `asyncio.new_event_loop()` and replace it with direct `await` calls since x-intake is already an async FastAPI app. If the function is synchronous and being called from a sync context, use `asyncio.get_event_loop().run_until_complete()` instead of creating a new loop. Check the calling context to determine the right fix.

---

## Fix 5 — Remove Redis Password from CLAUDE.md

`CLAUDE.md` still has the hardcoded Redis password in multiple places:
- The Redis section under "HARD RULES"
- The "Quick Commands" section
- The "Startup Health Checks" section

After the security-consolidation prompt runs, the password will be in `.env` only. Update CLAUDE.md:

1. In the Redis rule, change:
   `redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379`
   to:
   `redis://<password-from-env>@redis:6379` (credentials in .env, never hardcode)

2. In Quick Commands, change the Redis CLI examples from:
   `redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9`
   to:
   `redis-cli -a "$REDIS_PASSWORD"`

3. In Startup Health Checks, same change for the redis-cli commands.

4. In the Security section, remove or update the line about "Redis password is in this file for operational convenience."

---

## Fix 6 — Update STATUS_REPORT.md

Update the "Now" and "Next" sections to reflect current state:

**In the Now section**, mark these as done:
- KRAKEN_SECRET — add note: "Still pending Matt action"  
- Fund Polymarket wallet — add note: "Still pending Matt action ($750+ in positions as of April 12)"

**In the Next section**, mark these as done:
- "x-intake listener watchdog" — mark done, watchdog is implemented at line 658 of x_intake/main.py
- "Fix CLAUDE.md service table" — mark done (this prompt fixes it)

**Add to Done section:**
- Security consolidation (hardcoded secrets removed, 3 orphaned services merged/removed, PORTS.md created)
- CLAUDE.md heredoc/dquote rules added
- Cortex autobuilder deployed (Bob/Betty research loop + topic scanning)
- Symphony ops tab added to cortex dashboard

---

## Fix 7 — Clean Up Supabase Dead References

In `.env.example`, if there are `SUPABASE_*` variables, add a comment above them:
```
# SUPABASE_* — UNUSED by any Docker service. Safe to remove. Kept for symphonysh migration reference.
```

This documents the finding from the audit without breaking anything.

---

## Git Commit

```
git add -A
git commit -m "tighten loose ends: fix service tables, _re scope, remove hardcoded secrets from docs, update status report"
git push origin main
```
