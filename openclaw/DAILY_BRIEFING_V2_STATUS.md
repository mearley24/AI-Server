# daily_briefing_v2.py — status

**Canonical briefing: `openclaw/daily_briefing.py`.**

`daily_briefing_v2.py` is an in-flight experimental rewrite and is NOT
wired into the 6 AM iMessage send path as of 2026-04-17.

## What to use

- Production path: `openclaw/daily_briefing.py` → `send_briefing()`.
  Called by `openclaw/orchestrator.py`. Posts to Cortex on send.
- Calendar feed comes from the `/calendar/daily-briefing` endpoint on
  the calendar-agent service, wired into the briefing assembly on
  2026-04-13 (STATUS_REPORT Prompt N Done).

## What v2 represents

An attempt at a richer briefing format. Details are in the v2 file
itself; treat as work-in-progress.

## Before deleting v2

1. Confirm no launchd plist references it.
2. Run `grep -r "daily_briefing_v2" --include='*.py'` and verify no
   callers.
3. Confirm no Cortex task or decision journal entry references its
   output.

If the above are all empty, v2 can be removed; otherwise merge its
improvements back into the canonical file first.
