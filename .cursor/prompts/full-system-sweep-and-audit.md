# Full System Sweep & Audit

You just loaded `CLAUDE.md` and `AGENTS.md`. Prove it by using their context
throughout — do not re-explore the codebase from scratch.

This is the rollup-level full-stack pass that runs on top of the per-category
campaign (see `ops/verification/20260417-093739-category-campaign-tracker.txt`
and `20260417-101800-category-campaign-final.txt`). Run it when:

- Matt asks for a "full sweep" or "full audit";
- after a string of drift-y commits;
- after a multi-day gap where something may have regressed silently.

## Authoritative artifact paths

- This prompt: `.cursor/prompts/full-system-sweep-and-audit.md`
- Status file: `STATUS_REPORT.md` (note: underscore, not `STATUSREPORT.md`)
- Verification file: `ops/verification/YYYYMMDD-HHMMSS-full-system-sweep-and-audit.txt`
- Protocol: `ops/AGENT_VERIFICATION_PROTOCOL.md` — follow "tee-to-file + commit" rule.

## TASK: Produce a comprehensive state-of-stack snapshot

### Phase 1 — Live health

Use bounded one-liners only. Every section goes to the verification file via
`tee`.

- `docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"`
- `docker ps -q | wc -l` (container count — should equal `docker compose
  config --services | wc -l`)
- HTTP `/health` sweep on every host-exposed port (8091–8103, 8115, 8430,
  8765, 8199 — the iMessage bridge).
- `docker exec redis redis-cli -a "$REDIS_PW" PING` (source `.env` for
  password; do NOT hardcode). `LLEN events:log`, `PUBSUB NUMSUB events:imessage`.
- `bash scripts/verify-deploy.sh` — record every FAIL / WARN it emits.
- `bash scripts/compose-drift-check.sh` — every WARN must be explained
  against `ops/REPO_LAYOUT.md` allowlist.

### Phase 2 — Data pipeline spot-check

- SQLite row counts on the 6 canonical DBs (see
  `data/DATABASE_SCHEMA.md`):
  `jobs.db::jobs`, `jobs.db::client_preferences`,
  `decision_journal.db::pending_approvals` by status,
  `emails.db::emails` by `(read, responded)`,
  `follow_ups.db::follow_ups` and `follow_ups.db::follow_up_log`,
  `brain.db::memories`,
  `x_intake/queue.db::x_intake_queue` by status.
- If `follow_up_log` is still 0 rows, keep it on the regressions list until
  the auto-send loop fires once.
- Cortex: `curl http://127.0.0.1:8102/api/bluebubbles/health` — last inbound
  timestamp, `private_api` flag (expected `false` while SIP stays on),
  ping latency.

### Phase 3 — Autonomy surface

- Queue snapshot: `python3 ops/task_queue_status.py` — record pending /
  completed / failed / rejected / blocked and the oldest pending age.
- Preflight: `python3 ops/task_runner_preflight.py` — must be
  `ok=True resolved=0 staged=0 unsafe=0 report=`.
- Task-runner health: `python3 ops/task_runner_health.py` if present.
- launchd inventory: `launchctl list | grep -c symphony` and spot-check
  that `com.symphony.task-runner`, `com.symphony.bob-watchdog`,
  `com.symphony.task-runner-watchdog`, `com.symphony.realized-change-watcher`,
  `com.symphony.imessage-bridge`, `com.symphony.bluebubbles-watchdog` are all
  loaded.
- `cat data/task_runner/bob_watchdog_heartbeat.txt` — must be within the last
  ~90 s.
- `ls ops/verification/ | wc -l` — raw artifact count; if any single `<topic>`
  has >50 artifacts in the last 24 h it indicates a hot loop (see
  Regressions section of this prompt) and should be flagged.

### Phase 4 — Regression scan

Each of these is a known-to-recur failure mode — call out live status for all
of them:

1. **`_host_redis_url` drift in `scripts/imessage-server.py`** — the helper
   must rewrite `@redis:` → `@127.0.0.1:`. Check: `grep -n "_host_redis_url"
   scripts/imessage-server.py`.
2. **openclaw `redis_event_listener` attribute error** — if logs show
   `'Orchestrator' object has no attribute '_get_redis'` or similar, the
   method is out of sync with its caller. Tail `docker logs openclaw --tail
   60 | grep redis_event_listener`.
3. **verify-deploy.sh Redis PING without `-a`** — `grep -n "redis-cli PING"
   scripts/verify-deploy.sh`. If it does not pass `-a "$REDIS_PW"`, the FAIL
   at the top of the script is a false negative.
4. **Task-runner verify-dump loop** — if `ls ops/verification/*watchdog-install*
   | wc -l` is >50 the watchdog install task is stuck in pending and
   re-verifying forever. Root cause is usually that the verify script
   returns non-zero or the task file doesn't move out of `pending/`.
5. **`.env` unquoted comment lines** — `grep -nE "^[A-Z_]+=.*[A-Za-z] " .env
   | head -20` finds values like `KRAKEN_NOTES=Bank Transfer` which break
   `source .env` under `set -euo pipefail`.
6. **Pending approvals backlog** — total `pending` count should trend toward
   0. Alert if >200 and the oldest row is >7 days old — the drain
   (`scripts/prompt_t_drain.py`) needs to run again.
7. **Follow-up auto-send never fires** — `follow_up_log` row count. If 0 for
   >7 days, mark the engine as dormant and include it in Next.
8. **Dropbox `/preview/` links anywhere** — run
   `bash scripts/dropbox-link-validate.sh` against `knowledge/` and
   `STATUS_REPORT.md`.

### Phase 5 — Doc / drift accuracy

- Container count in `CLAUDE.md` and `.clinerules` must match
  `docker compose config --services | wc -l`.
- `ops/REPO_LAYOUT.md` stale-dir allowlist must match the Dockerfile-bearing
  dirs warned by `scripts/compose-drift-check.sh`.
- `docs/DATABASE_SCHEMA.md` live snapshot section age — re-append if >30 d.

### Phase 6 — Write STATUS_REPORT update

Prepend a new section to `STATUS_REPORT.md` with a dated heading:

    ## Full system sweep (YYYY-MM-DD HH:MM MDT, Cline)

Structure:

1. Headline state (🟢 / 🟡 / 🔴 per pillar: containers, data pipeline,
   autonomy, messaging, trading).
2. Concrete counts (containers healthy, cortex memories, emails,
   pending_approvals, x_intake queue distribution, follow_up_log).
3. Regressions table — one row per Phase-4 item, with CURRENT VALUE and
   STATUS.
4. New follow-ups using the `- [FOLLOWUP]` / `- [NEEDS_MATT]` tag conventions
   described at the top of STATUS_REPORT.md.

Keep the update tight — < 120 lines. Don't duplicate the per-category audit
bodies; link to them.

### Phase 7 — Write verification artifact

Write `ops/verification/<stamp>-full-system-sweep-and-audit.txt` containing
(in this order):

1. Header: stamp, git SHA, branch, container count, launchd count.
2. Phase 1 raw command output (bounded).
3. Phase 2 raw SQL counts.
4. Phase 3 queue + launchd inventory.
5. Phase 4 regression table with greps / log tails inline.
6. Phase 5 drift list.
7. Summary block matching the STATUS_REPORT headline.
8. Recommended next actions (highest-leverage 3–5 items only).

### Phase 8 — Commit + push

```
git add STATUS_REPORT.md ops/verification/<stamp>-full-system-sweep-and-audit.txt
git add .cursor/prompts/full-system-sweep-and-audit.md   # first-time only
git commit -m "ops(full-sweep): state-of-stack snapshot YYYYMMDD"
bash scripts/pull.sh   # reconcile first, never bare git pull
git push origin main
```

Never ask Matt to paste terminal output back. One paste in, one commit out,
another agent reads the file directly.

## Definition of done

- [ ] All 8 phases executed; verification artifact committed + pushed.
- [ ] STATUS_REPORT.md has a new dated section with the 🟢/🟡/🔴 headline
  and counts.
- [ ] Every Phase-4 regression has a concrete current-value and status.
- [ ] Recommended next actions are ≤5 bullets and reference existing prompts
  or tickets (do NOT invent parallel plans).
- [ ] No paste-back requested.
