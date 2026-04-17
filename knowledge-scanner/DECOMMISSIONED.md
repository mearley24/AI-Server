# DECOMMISSIONED — knowledge-scanner/

**Status:** no longer deployed. **Do not add new code here.**

Replaced by `integrations/cortex_autobuilder/` + `transcript_analyst`.

Knowledge scanning is now performed by
`integrations/cortex_autobuilder/daemon.py` on a research loop, and by
`integrations/x_intake/transcript_analyst.py` for video-derived
insights. Results land in Cortex `brain.db` via `POST /remember`.

Files in this directory are retained for historical reference only.
Removal is tracked as a future MEDIUM-risk cleanup task (deletion waits
until this marker has been in place >= one week).
