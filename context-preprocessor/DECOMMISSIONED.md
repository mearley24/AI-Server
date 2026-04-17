# DECOMMISSIONED — context-preprocessor/

**Status:** no longer deployed. **Do not add new code here.**

Consolidated into Cortex memory + the x-intake pipeline.

Per STATUS_REPORT Prompt N cleanup, this service was removed from
`docker-compose.yml`. The functions it provided (context summarization
for feeding into Cortex) are now handled directly by
`integrations/x_intake/transcript_analyst.py` and the
`integrations/cortex_autobuilder/daemon.py` research loop, both of
which POST results to Cortex `POST /remember` on port 8102.

Files in this directory are retained for historical reference only.
Removal is tracked as a future MEDIUM-risk cleanup task (deletion waits
until this marker has been in place >= one week).
