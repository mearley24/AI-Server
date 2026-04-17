# DECOMMISSIONED — mission_control/

**Status:** no longer deployed. **Do not add new code here.**

Dissolved into the `cortex/` service (single brain + dashboard) as part
of Prompt S on 2026-04-12. `cortex/` at port 8102 now serves both the
memory store (`POST /remember`) and the web UI (`/dashboard`).

- See `cortex/dashboard.py` for the migrated API endpoints.
- See `cortex/static/index.html` for the migrated UI.
- See `STATUS_REPORT.md` section "Mission Control dissolved" for context.

Files in this directory are retained for historical reference only.
Removal is tracked as a future MEDIUM-risk cleanup task (deletion waits
until this marker has been in place ≥ one week).
