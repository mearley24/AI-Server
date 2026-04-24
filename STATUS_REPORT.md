# STATUS REPORT — Symphony AI-Server

Generated: 2026-04-11 | Last updated: 2026-04-23 MDT
Host: Bob (Mac Mini M4), branch: main.
Audit series: Prompt Q (full audit) → Prompt S (Cortex merge) → Z3–Z14 patches → autonomy gap-closer (2026-04-18) → X Intake reply-leg fix (2026-04-18) → **iMessage bridge host_redis_url helper land (2026-04-18 09:04, Cline)** → **STATUS_REPORT auto-summarizer (2026-04-18 10:45, Cline)** → **bob-watchdog + x-intake lane health (2026-04-21 11:49, Cline)** → **BlueBubbles integration + hardening (2026-04-21 13:02, Cline)** → **full-system sweep & audit (2026-04-21 14:35, Cline)** → **close yellow gaps (2026-04-21 15:03, Cline)** → **X-intake deep-dive audit + reply-action design + testbed spec (2026-04-23, Claude Code)** → **watchdog hotfix fully deployed + install script hardened (2026-04-23 08:10, Claude Code)** → **watchdog LaunchDaemon repo-root resolution fix (2026-04-23 14:14, Claude Code)** → **watchdog bash-3.2 + required-services override hotfix (2026-04-23 14:46, Claude Code)** → **watchdog required-source subshell fix + [FOLLOWUP] alert (2026-04-23 14:58, Claude Code)** → **network-dropout-watch LaunchAgent plist added + network-guard crash documented (2026-04-23 09:15, Claude Code)** → **network-monitoring verification run 2 — plist spec confirmed, guard still broken (2026-04-23 09:34, Claude Code)** → **network-dropout-watch armed + PATH fix (2026-04-23 09:37, Claude Code)** → **network-monitoring verification run 3 — dropout-watch confirmed healthy (2026-04-23 09:38, Claude Code)** → **network-monitoring phase-2 Cline prompt drafted — fix security_utils import (2026-04-23 15:26, Claude Code)**.

### Tagging conventions (for the summarizer)

`ops/status_report_summarizer.py` parses this file and produces a short
owner-readable digest at `ops/verification/<stamp>-status-report-summary.md`.
To help it, use these bullet prefixes when adding new items:

- `- [FOLLOWUP]` — an open follow-up task that no one is blocked on; the
  summarizer groups these under "Follow-ups".
- `- [NEEDS_MATT]` — requires a real-world decision or input from Matt
  (pricing, credentials, funding, testimonials, approvals); the summarizer
  groups these under "Needs Matt".
- `- ~~...~~ ✅` — strikethrough + green check means the item is done and
  can stay in its original section as a history trail.

Legacy prose like `[Matt]`, `Fund ... wallet`, `Requires approval` still
works — the summarizer's regex picks it up — but the explicit tags are
preferred for new entries. See `ops/AGENT_VERIFICATION_PROTOCOL.md` →
"STATUS_REPORT conventions" for the full rule.


---

## Port & API Surface Audit — prompt armed (2026-04-24 UTC, Claude Code)

Parent-agent docs-only pass. Matt asked (a) whether a recent full audit
of all Bob ports exists and (b) whether the BlueBubbles API connection
should be turned off now. No Bob runtime actions were taken this pass —
no `docker`, `launchctl`, `sudo`, firewall, `.env`, or secret mutations.

Answers from committed repo evidence:

- **Recent full port audit?** Partial and stale. The closest snapshot is
  `ops/verification/20260421-143522-full-system-sweep-and-audit.txt`
  (2026-04-21, ~3 days old). It captured docker-compose port bindings
  (19 services), `/health` sweep on the Symphony 8091–8765 range, 50
  loaded launchd agents, and BlueBubbles inbound counters. It did not
  enumerate every host listening socket, did not classify loopback vs
  LAN vs Tailscale, did not map each listener to its owning plist/
  container, and did not classify ports as REQUIRED/OPTIONAL/STALE/
  UNKNOWN. A fresh, complete audit is warranted.

- **Turn off BlueBubbles now?** No — not before the audit ships.
  Inbound webhook was confirmed live on 2026-04-24
  (`ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`,
  verdict `PASS-webhook-only`, commit `e610cddb`). Disabling the inbound
  leg breaks Cortex message ingest and x-intake reply fan-in. Outbound
  leg (`cortex.bluebubbles.BlueBubblesClient.send_text`) is the primary
  send path; the AppleScript bridge on `:8199` is a fallback only.
  x-intake reply-leg live smoke is `PRECHECKS_PASSED` and depends on
  BlueBubbles outbound.

Artifacts armed this pass:

- Cline prompt: `.cursor/prompts/2026-04-24-cline-full-port-api-surface-audit.md`
  (bounded checks: `lsof -nP -iTCP -sTCP:LISTEN`, `docker ps` port map,
  launchd plist→port inventory, BlueBubbles inbound+outbound surface,
  classification table, hard no-mutation list).
- Runbook: `ops/runbooks/2026-04-24-full-port-api-surface-audit.md`
  (Status: ARMED).
- Receipt: `ops/verification/20260424-port-api-surface-audit-prompt-armed.txt`.

- [FOLLOWUP] Run the armed prompt on Bob (ACT MODE) to emit
  `ops/verification/${STAMP}-port-api-surface-audit/` and replace this
  entry's "partial + stale" finding with a full classification table.
- [FOLLOWUP: bluebubbles-disable-gate] Any proposal to disable
  BlueBubbles must ship with a rollback plan, a verification that the
  AppleScript bridge (`:8199`) is healthy as a fallback outbound path,
  and confirmation that `BLUEBUBBLES_SERVER_URL` is Tailscale-only.

---

## Loose-Ends Reconciliation (2026-04-24 UTC, Claude Code)

Parent-agent docs-only pass reconciling stale `Status: active` prompts
and runbooks against committed evidence. No Bob runtime actions, no
`launchctl`, `docker`, `sudo`, env mutation, external sends, ports,
secrets, money/trading, or destructive changes.

Closed this pass (closure blocks added, citing existing evidence):

- `.cursor/prompts/2026-04-23-cline-bluebubbles-health-plist.md` → `done`
- `.cursor/prompts/2026-04-23-cline-bluebubbles-attachment-bodies.md` → `done`
- `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md` → `done`
- `.cursor/prompts/2026-04-23-cline-x-intake-reply-leg-phases-2-6.md` → `done`
- `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md` → `done` (Verdict `PASS-webhook-only`, receipt `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`)
- `.cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md` → `done` (APPROVE ALL applied, commit `275f2a83`)
- `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` → `Status: DONE`
- `ops/runbooks/2026-04-24-bob-docker-crash-diagnostic.md` → `Status: DONE`

Top-level STATUS_REPORT BlueBubbles webhook entry annotated as
**superseded**; three companion `[NEEDS_MATT]` / `[FOLLOWUP]` bullets
struck through with ✅ and receipts.

Remaining open items (intentionally not closed — evidence still pending):

- X-Intake reply-leg **live smoke** (outbound BlueBubbles `send_text`)
  — authoritative runbook `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
  (`Status: PRECHECKS_PASSED`); follow-up evidence prompt
  `.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`.
- Docker Desktop restart + watchdog system-deploy + translocated-path
  reinstall (tracked at L55–L57 above).
- NEEDS_MATT orchestration prompt — kept `active` because it wraps the
  still-open reply-leg gate.

Full audit: `docs/audits/2026-04-24-loose-ends-reconciliation.md`.

---

## BlueBubbles → Cortex Live Webhook Verification (2026-04-24 UTC, Claude Code) — superseded

_Superseded by the re-run at `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md` (verdict **`PASS-webhook-only`**) after the webhook URL was corrected from `http://cortex:8102/...` (Docker-only hostname) to `http://127.0.0.1:8102/hooks/bluebubbles` (loopback form). The entries below are preserved as history._

- Prompt: `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md` (now `Status: done`)
- First run: `ops/verification/20260424-154222-bluebubbles-cortex-live-webhook.md` — Verdict `FAIL-no-webhook` (URL misconfigured)
- Re-run (authoritative): `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md` — Verdict **`PASS-webhook-only`**; webhook leg live, allowlist is the gate.
- `~~[FOLLOWUP: bluebubbles-private-api-disabled]~~` ✅ Resolved — root cause was Webhook URL misconfiguration, not Private API. Fixed per commit `e610cddb`.
- [FOLLOWUP] To reach `PASS-webhook-and-policy`, add a trusted test number to `config/bluebubbles_routing.json` `inbound.allowed_phones`.
- [FOLLOWUP: structured-log-visibility] `bluebubbles_webhook` `logger.info` lines not appearing in `docker logs cortex` despite `CORTEX_LOG_LEVEL=INFO`; investigate logging handler configuration in `cortex/engine.py:33`.

---

## Bob Docker/Memory Optimization Applied (2026-04-24 09:25 MDT, Claude Code)

APPROVE ALL executed. Changes applied:

- `scripts/bob-watchdog.sh` — Docker cooldown 180s → **300s** (WATCHDOG_VERSION bump needed for system copy)
- `docker-compose.yml` — **x-intake-lab decommissioned** (512m freed, container stopped)
- `~/Library/Application Support Docker Desktop/settings-store.json` — **MemoryMiB 4096 → 6144** (takes effect after Docker Desktop restart)
- `~/Library/LaunchAgents/com.ollama.plist` — **KEEP_ALIVE 5m → 0**, MAX_LOADED_MODELS 2 → 1 (Ollama reloaded)
- `docker system prune -a` + `docker builder prune -a` — **~11.5 GB disk reclaimed**

Before/after:
  Disk: 95% → 90% (11 GB → 22 GB free)
  Memory pages free: 8,572 → 12,727
  Ollama RAM: ~5.7 GB (models evicted, KEEP_ALIVE=0 prevents reload)
  Docker VM: 4 GB → 6 GB (active after Docker Desktop restart)

- [NEEDS_MATT] Restart Docker Desktop to apply the 6 GB VM memory setting
- [NEEDS_MATT] `sudo setup/install_bob_watchdog.sh --deploy-system` to sync 300s cooldown to system copy
- [FOLLOWUP] Move Docker Desktop from translocated path to `/Applications/` (reinstall)

---

## BlueBubbles → Cortex Live Webhook Verification Prompt Added (2026-04-24 UTC, Claude Code)

Parent-agent repo pass documenting the one remaining follow-up Matt
flagged: fully-live BlueBubbles → Cortex webhook leg. Self-to-self
iMessage does not trigger the webhook (expected Apple iMessage-routing
behavior — not a bug); full-leg proof requires a message from a
**different** phone number. **No runtime/external action performed by
this repo pass** — no curl, no docker exec, no BlueBubbles UI
inspection, no message send, no settings mutation, no service restart,
no port change, no secret read. Dirty harness-owned files
(`.claude/**`, `.mcp.json`, `CLAUDE.md`) preserved.

Added, Bob-safe, bounded, read-only by design:

- `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`
  — autonomous Cline prompt (Category: messaging, Risk: high, Trigger:
  manual, Status: active). Phases 0–10 emit bounded evidence to
  `ops/verification/<stamp>-bluebubbles-cortex-live-webhook.md` and
  classify into `PASS-webhook-and-policy`, `PASS-webhook-only`,
  `FAIL-no-webhook`, `BLOCKED-no-external-sender`,
  `BLOCKED-ui-inaccessible`, or `BLOCKED-unhealthy-baseline`. Any
  settings/config mutation deferred to follow-up prompts gated on
  `APPROVE: bluebubbles-webhook-url` (or similar).
- `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` —
  human-approved companion runbook: pre-flight, bounded command
  reference, UI check checklist, redaction rules, verdict taxonomy,
  escalation paths, explicit non-authorizations. No autonomy metadata
  (dispatcher skips runbooks).
- `ops/verification/20260424-bluebubbles-cortex-live-webhook-prompt-creation.md`
  — receipt for this repo pass: prompt/runbook existence, path greps,
  no-runtime-action attestation.

Key design choices recorded in the prompt:

- **Source-of-truth webhook URL = `http://127.0.0.1:8102/hooks/bluebubbles`**
  (loopback form), per `cortex/bluebubbles.py:680` and
  `docs/bluebubbles/MANUAL_WEBHOOK_TEST.md:9`. The `cortex` hostname
  form only resolves inside the Docker compose network; BlueBubbles
  runs as a host-side LaunchAgent, so the loopback form is correct.
  Both forms are captured in evidence to prevent repeat confusion.
- **External send is manual and out-of-band.** The prompt prints a
  nonce (`BBCX-<UTC-YYYYMMDD>-<6hex>`) and instructs Matt to arrange a
  human on a distinct phone number to send it. The agent never sends
  a message.
- **UI inspection is `[NEEDS_MATT]`.** Matt pastes a redacted
  screenshot description of the BlueBubbles Settings Webhook URL field
  into the verification file. The agent does not click into the UI
  and does not edit the field.
- **Event watching is time-windowed polling** (≤ 12 polls × 10 s);
  no `tail -f`, no `--follow`, no `watch`.
- **Redaction mandatory.** Phone numbers → last-4; message bodies →
  nonce-only; BlueBubbles API password/token → `***REDACTED***`;
  email local-parts → `***@example.com`.

Follow-up ownership:

- ~~[FOLLOWUP] Matt runs `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md` on Bob via Cline after coordinating an external sender.~~ ✅ Ran 2026-04-24 — receipt `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`, verdict `PASS-webhook-only`.
- ~~[NEEDS_MATT] Inspect BlueBubbles Settings UI Webhook URL and record under Step 2.~~ ✅ Done 2026-04-24 — URL corrected from `http://cortex:8102/...` to `http://127.0.0.1:8102/hooks/bluebubbles` (commits `03dddc34`, `e610cddb`).
- ~~[NEEDS_MATT] Coordinate external-number iMessage send for Step 5 (nonce supplied by prompt Step 0).~~ ✅ Done 2026-04-24 — external send from `+1XXXXXXX1850` at ~2026-04-24T16:17 UTC triggered 3 HTTP-200 POSTs to `/hooks/bluebubbles`.

_Created by Claude Code on 2026-04-24 UTC. No runtime/external message
action performed by this repo pass. Closed 2026-04-24 — see loose-ends
reconciliation `docs/audits/2026-04-24-loose-ends-reconciliation.md`._

---

## Bob Docker Crash / Memory Diagnostic Prompt Added (2026-04-24 UTC, Claude Code)

User-reported symptom: "something keeps crashing docker, it needs to be
looked into and see how we can optimize docker and Bob as it may be a
memory problem." Parent-agent repo pass; **no runtime action performed
by this pass** — no `docker` invocation, no container/daemon restart, no
prune, no launchctl, no sudo, no secret read, no external send. Dirty
harness-owned files (`.claude/**`, `.mcp.json`, `CLAUDE.md`) preserved.

Added, Bob-safe, bounded, read-only by design:

- `.cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md`
  — autonomous Cline prompt (Category: ops, Risk: high, Trigger: manual,
  Status: active) for Docker crash / memory-pressure diagnosis on Bob.
  Phases 0–10 emit evidence to
  `ops/verification/<stamp>-bob-docker-crash-diagnostic.md` and classify
  into A–H (host memory / container memory / disk / restart loop /
  Docker Desktop crash / watchdog false recovery / compose misconfig /
  unknown). All mutations deferred to follow-up prompts gated on
  explicit approval strings (`APPROVE: docker-desktop-resources`,
  `APPROVE: compose-memory-limits`, `APPROVE: watchdog-throttle`,
  `APPROVE: log-rotation`, `APPROVE: container-decommission <name>`).
- `ops/runbooks/2026-04-24-bob-docker-crash-diagnostic.md` — human
  runbook companion: how to kick off the prompt on Bob, how to read the
  classification, what the prompt intentionally does not do, and what
  to do if the diagnostic itself hangs. No autonomy metadata (runbook,
  not autonomous prompt).
- `ops/verification/20260424-bob-docker-crash-diagnostic-prompt-added.txt`
  — receipt: prompt + runbook paths, header checks, git commit hash.

Exact command for Matt to run on Bob in Cline:

```
Run .cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md.
Follow every step. Read-only evidence phases run under AUTO_APPROVE=true.
Any mutation requires the approval strings listed in §Safety gates.
Do not restart Docker. Do not restart containers. Do not prune.
Do not touch secrets. Commit and push at the end.
Return the final report fields listed in the prompt.
```

- [FOLLOWUP] After the diagnostic runs on Bob and produces a
  classification, Matt decides which approval string(s) to type in a
  subsequent Cline session to unblock a follow-up mutation prompt.

---

## NEEDS_MATT Clearance Reconciliation — Runbook Outcomes (2026-04-24 UTC, Claude Code)

Parent-agent reconciliation pass against committed evidence for the
three Bob-runtime `[NEEDS_MATT]` runbooks added in commit `4dd114ce`.
**No runtime actions were performed:** no docker, no launchctl, no env
mutation, no sudo, no external sends, no secrets read. Harness-owned
dirty working-tree items (`.claude/**`, `.mcp.json`, `CLAUDE.md`)
preserved as-is. Historical `ops/verification/` receipts untouched.

Per-gate outcomes:

| Gate | Runbook | Outcome | Evidence |
|------|---------|---------|----------|
| Cortex dedup live `--apply` | `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md` (`Status: DONE`) | **ARMED — already ran** | `ops/verification/20260423-173120-cortex-dedup-backfill.json` + `20260423-173840-cortex-dedup-backfill.json` (each `rows_deleted=1`, idempotent). Runbook appendix records live DB state: 53,972 rows, `idx_memories_dedupe_key` present. |
| BlueBubbles health plist | `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md` (`Status: DONE`) | **ARMED — LaunchAgent live** | `ops/verification/20260424-083518-bluebubbles-health-arm.txt` — `run interval = 300`, `.err` empty, 269 log lines, BlueBubbles 1.9.9 healthy. |
| X-intake reply-leg live smoke | `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md` (`Status: [NEEDS_MATT]`) | **DEFERRED — no evidence** | No `ops/verification/*x-intake-reply-leg-live-smoke*` receipt exists. Runbook remains gated (Matt-only allowlist + supervised DRY_RUN flip + immediate restore). External-send posture preserved. |

Actions taken in this pass (repo-only):

- Closed stale `[NEEDS_MATT]` bullets for cortex-dedup (L353, L390,
  L410) and bluebubbles-health (L354, L448) by strikethrough + ✅
  pointing to the runbook status + evidence receipts already
  committed prior to this pass. Bullets are not deleted — the audit
  history stays intact.
- Left the two x-intake live-smoke `[NEEDS_MATT]` bullets (L355 +
  L374) open. Annotated both to point at the authoritative runbook
  and the new evidence-capture prompt.
- Added `.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`
  — a targeted, self-contained orchestration prompt that either
  (a) runs the runbook's Appendix dry-run-only variant to capture
  reproducible evidence without any external send, or
  (b) under explicit `SMOKE: x-intake-reply-leg TO=<matts-own-number>`
  authorization, runs the full supervised live smoke. Default posture
  is dry-run-only.
- Ran `python3 scripts/needs_matt_inventory.py` before and after the
  strikethroughs to quantify the reduction in actionable surface.

No edits to files under `ops/verification/` older than this run. No
changes to Polymarket funding markers (L1140, L1141, L1808). No
changes to network-monitoring / watchdog / sudoers markers — separate
tracks.

Verification receipt for this pass:
`ops/verification/20260424-150000-needs-matt-clearance-reconciliation.txt`
(timestamps, per-gate probe outputs, inventory before/after, commit
hash appended post-commit).

---

## BlueBubbles Health — LaunchAgent Armed on Bob (2026-04-24 08:35 MDT, Claude Code)

`com.symphony.bluebubbles-health` LaunchAgent confirmed ARMED. Was installed
2026-04-23 10:15 by a prior session; this run documents the verified state.

- `run interval = 300 seconds` ✓
- BlueBubbles server 1.9.9: healthy on every run ✓
- `.err` log: empty (no crashes) ✓
- 269 log lines from ~22+ runs since Apr 23 ✓
- `last exit code = 1` — expected; script exits 1 when Cortex 404s (known FOLLOWUP)

- ~~[NEEDS_MATT] Arm the LaunchAgent~~ ✅ Armed 2026-04-23 10:15 MDT
- [FOLLOWUP] `docker compose up -d --build cortex` — stale image means `/api/bluebubbles/health` still 404s; rebuild clears it and drops exit code to 0.

Verification: `ops/verification/20260424-083518-bluebubbles-health-arm.txt`

---

## NEEDS_MATT Clearance Artifacts — Bob Runtime Runbooks (2026-04-23 UTC, Claude Code)

Parent-agent docs-only pass to cover the three outstanding
`[NEEDS_MATT]` gates with human-approved runbooks under
`ops/runbooks/` — same split-off pattern used for the (now-closed)
Cortex embeddings arm. **No runtime actions were performed by this
repo pass:** no docker, no launchctl, no env mutations, no sudo, no
external sends, no posts/messages, no opened ports, no secrets read.
Harness-owned dirty working-tree items (`.claude/**`, `.mcp.json`,
`CLAUDE.md`) preserved as-is per parent instruction.

Classification of current `[NEEDS_MATT]` items relevant to this pass:

| Gate | Class | New artifact |
|------|-------|--------------|
| Cortex dedup live `--apply` on `brain.db` | (d) stale from evidence + (b) for future re-runs — prior `--apply` receipts already exist (`20260423-173120`, `20260423-173840` = `rows_deleted=1` each); runbook covers any future re-run with mandatory backup + dry-run + idempotency guards. | `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md` |
| Arm `com.symphony.bluebubbles-health.plist` | (b) local Bob runtime action — user-scope `launchctl bootstrap`; no sudo, no external surface. | `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md` |
| X-intake reply-leg live smoke | (c) external-send — kept gated behind Matt-only allowlist + DRY_RUN flip + immediate restore + emergency rollback one-liner. Safer dry-run-only alternative included. | `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md` |

Each runbook:

- Is explicitly marked `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` + "NOT
  auto-run by Computer / Cline / Claude Code / task-runner /
  self-improvement loop" in its header.
- Has no `<!-- autonomy: start -->` metadata, so the autonomous
  dispatchers skip it.
- Carries: prechecks (clean tree, container health, schema state,
  disabled-vs-loaded check, disk/lock check as applicable), an
  ordered bounded arm sequence, required verification receipt path,
  STATUS_REPORT entry template, commit message, rollback/stop
  conditions, and an explicit forbids list.
- Reuses existing helpers only (`scripts/set-env.sh`, the in-repo
  backfill scripts, `docker compose`, `launchctl bootstrap` under
  `gui/$(id -u)`). No new scripts authored.

Out-of-scope for this pass (other open `[NEEDS_MATT]` markers
unrelated to the three current gates, retained as-is):

- Polymarket wallet funding (L994-995, L1662) — external economic
  action, separate track.
- Stale strikethroughs lower in the file (network-monitoring,
  watchdog system-copy) are already marked `✅` and remain as
  history.

Verification this pass: path-exists for the three runbooks;
`grep [NEEDS_MATT]` census; `xml.etree` parse of the already-lint-
clean `setup/launchd/com.symphony.bluebubbles-health.plist` from the
sandbox (plutil not available on Linux). No code or config changed.

---

## NEEDS_MATT Clearance Orchestration Prompt Added (2026-04-24 UTC, Claude Code)

Parent-agent docs-only pass added a single orchestration prompt that
reconciles the three remaining Bob-runtime `[NEEDS_MATT]` gates
against committed evidence and drives their matching runbooks under
explicit per-gate operator authorization. **No runtime actions were
performed by this repo pass:** no docker, no launchctl, no env
mutation, no sudo, no external sends, no posts/messages, no opened
ports, no secrets read. Harness-owned dirty working-tree items
(`.claude/**`, `.mcp.json`, `CLAUDE.md`) preserved as-is per parent
instruction.

- New prompt: `.cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md`
  — Status: `active`, Risk tier: `high`, Trigger: `manual`.
- Orchestrates (does not duplicate) the three existing runbooks:
  `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md`,
  `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md`,
  `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`.
- Gates each action behind a per-gate authorization string
  (`ARM:`, `SMOKE:`, `DRY_RUN:`, `SKIP:`) the operator types in
  chat; default posture for the x-intake live smoke stays
  `DRY_RUN_ONLY`.
- Leaves Polymarket funding markers (L1045/1046/1713), the
  historical `ops/verification/*` receipts, and all doc/code-comment
  `[NEEDS_MATT]` references untouched. Explicitly excludes editing
  `ops/verification/` files older than the run.
- Verification receipt for this repo pass:
  `ops/verification/20260424-needs-matt-classification.txt`
  (classification + path-exists + grep census; no code or config
  changed).

---

## NEEDS_MATT Hygiene Mechanism — Policy + Inventory Script (2026-04-24 UTC, Claude Code)

Follow-up durable prevention pass so stale `[NEEDS_MATT]` markers stop
causing confusion. **No runtime actions:** no docker, no launchctl, no
sudo, no env mutation, no external sends. Repo-owned artifacts only.

New artifacts:

- `docs/needs-matt-policy.md` — authoritative policy. Classes (active /
  closed / runbook-header / doc-reference / prompt-reference /
  historical), required metadata for active markers (Owner, Opened,
  Review-by, Evidence, Next), closure rules (strikethrough + ✅ with
  evidence, never delete), duplicate handling, and the scope of the
  inventory script.
- `scripts/needs_matt_inventory.py` — pure-stdlib Python scanner.
  Classifies every `[NEEDS_MATT]` hit, flags active markers that are
  stale (past `Review-by`, or older than a default 14-day window) or
  under-specified (missing required metadata). Excludes
  `ops/verification/*` by default so frozen receipts don't inflate the
  surface. Exit code is always 0 — advisory, not a CI blocker.
- `.cursor/prompts/needs-matt-hygiene-check.md` — periodic cleanup
  prompt (Category: docs, Risk tier: low, Trigger: manual). Runs the
  checker, closes stale markers by evidence, adds missing metadata,
  writes a timestamped receipt.

Command to find/remove stale markers in the future:

```
python3 scripts/needs_matt_inventory.py
python3 scripts/needs_matt_inventory.py --all
python3 scripts/needs_matt_inventory.py --write ops/verification/<stamp>-needs-matt-inventory.txt
```

The 2026-04-24 clearance orchestration prompt now includes a
mandatory Phase-3.5 step that runs the inventory script after any
ARMED gate and verifies the STATUS_REPORT strikethrough landed
before the final commit.

Verification receipt for this repo pass:
`ops/verification/20260424-needs-matt-prevention-mechanism.txt`
(first-run counts + path-exists + policy doc diff stats).

---

## Cortex Embeddings — Live Arm on Bob (2026-04-23 13:14 MDT, Claude Code)

Runbook `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md` executed.

- Backup: `brain.db.bak.20260423-113026` (160 MB)
- Dedup backfill `--apply`: 1 duplicate removed (X Signal)
- `nomic-embed-text:latest` pulled (274 MB, dim=768)
- `CORTEX_EMBEDDINGS_ENABLED=1` set in `.env` + `docker-compose.yml`
- Schema fix: dedupe_key UNIQUE index moved from `_SCHEMA` → `_MIGRATE_INDEXES` (commit `4f2fac4`)
- Backfill partial: **4,506 / 53,215 rows embedded (8.5%)** — Docker daemon crash-loops
  every 2-9 min, killing each `docker exec` run before completion. DB integrity OK throughout.
- Semantic search working: `GET /memories?semantic=1` returns ranked results.
- Embed worker ON (`CORTEX_EMBEDDINGS_ENABLED=1`) — new memories embedded in real-time.

- [FOLLOWUP] Complete historical backfill during Docker-stable window:
  `docker exec cortex python3 /app/scripts/cortex_embed_backfill.py --apply --provider ollama --db /data/cortex/brain.db`
- [FOLLOWUP] Fix Docker daemon crash-loop on Bob (zombie-daemon issue, ~10 min MTBF)

Commits: `4f2fac4`, `dce5064`
Verification: `ops/verification/20260423-131459-cortex-embeddings-live-arm.txt`

---

## Cortex Embeddings Reconciliation (2026-04-23 17:05 UTC, Claude Code)

Parent-agent pass after the embeddings Cline prompt ran. No code
paths touched; no runtime action taken. Harness-owned dirty files
(`.claude/`, `.mcp.json`, `CLAUDE.md`) preserved.

Reviewed state:

- Embeddings code/tests **landed** on `origin/main`: `9f0b7c4`,
  `89ad9fc`, `814f746`, `7eab1eb`. 8/8 tests pass (`NullProvider`, no
  network).
- Default posture confirmed: `CORTEX_EMBEDDINGS_ENABLED=0`
  (`cortex/config.py:43`). Writer hook is a no-op until armed.
- Dedup prerequisite **satisfied** repo-side
  (`716b14a`/`da532f3`/`758b31f`/`bc8ffdf`/`50feea8`); live `--apply`
  on `brain.db` is still `[NEEDS_MATT]`.
- Five-prompt reconciliation receipt
  `ops/verification/20260423-164850-five-prompt-reconciliation.md`
  was written in a window where embeddings were still "unrun";
  addendum appended with the correct outcome.
- Embeddings prompt header flipped `Status: active` → `Status: done`
  with a closure block pointing at the runbook.
- Unfinished-setup audit §1 "Cortex cross-source dedup (UNIQUE/upsert)
  and embeddings" now marks repo-side closure and references the new
  runbook.

Added:

- `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md` — gated
  runtime arm runbook (`[NEEDS_MATT]` + `[BOB_CLINE_ONLY]`, explicitly
  NOT auto-run by Computer / Cline / task-runner / self-improvement
  loop). Includes prechecks, ordered arm sequence, verification
  receipt requirements, and rollback/stop conditions.
- Reconciliation receipt
  `ops/verification/20260423-170500-cortex-embeddings-reconciliation.txt`.

- ~~[NEEDS_MATT] Remaining action is the runtime arm sequence on Bob.
  Start from `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md`;
  do not re-run the Cline prompt.~~ ✅ (closed 2026-04-23 UTC — runbook
  executed on Bob; see §"Cortex Embeddings — Live Arm on Bob" L29 and
  §"Cortex Embeddings Arm Closure" below.)

---

## Cortex Embeddings Arm Closure (2026-04-23 20:02 UTC, Claude Code)

Parent-agent closure pass after Cline ran
`.cursor/prompts/2026-04-23-cline-cortex-embeddings-arm-evidence.md`
on Bob and reported VERDICT: ARMED. Repo-side reconciliation only —
no runtime action, no docker, no env flip, no sudo, no external
messages. Harness-owned dirty files (`.claude/`, `.mcp.json`,
`CLAUDE.md`) preserved.

All three acceptance conditions met and recorded on `origin/main`:

- `.env`: `CORTEX_EMBEDDINGS_ENABLED=1`
- `memory_embeddings` rows: 4559 (`nomic-embed-text`, dim=768)
- Cortex `/health`: HTTP 200, `status=alive`

Committed evidence:

- `ops/verification/20260423-131459-cortex-embeddings-live-arm.txt`
  (commit `555274cd` — runbook receipt, arm steps 1-8 + smoke test)
- `ops/verification/20260423-135512-cortex-embed-arm-evidence.txt`
  (commit `412ec2bc` — independent arm-evidence probe, VERDICT: ARMED)
- `ops/verification/20260423-200253-cortex-embed-arm-closure.txt`
  (this pass — reconciliation receipt + superseded-marker map)
- Runbook `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md`
  has a "Closure (2026-04-23 UTC)" section appended pointing at
  the three receipts above.
- Evidence-capture prompt
  `.cursor/prompts/2026-04-23-cline-cortex-embeddings-arm-evidence.md`
  flipped `Status: active` → `Status: done` to prevent re-probe.

Superseded markers (preserved as history per strikethrough convention):

- L88-89 "[NEEDS_MATT] Remaining action is the runtime arm sequence
  on Bob" — now struck. ✅
- L108-114 "[NEEDS_MATT] Ordered arm sequence" (under Phase-1 Author+Test
  entry) — arm sequence has now been executed; the entry is retained
  for historical accuracy but the live-arm entry at L29 and this
  closure entry are authoritative.

Embed worker is ON — all new memories are embedded in real time by
`embed_worker`. Only the historical-backfill [FOLLOWUP] remains; it is
not a gate on arm.

- [FOLLOWUP] Complete historical backfill of the remaining ~48k rows
  (see L43-44 under the 13:14 live-arm entry).
- [FOLLOWUP] Docker daemon zombie-crash on Bob (~10 min MTBF) —
  tracked separately; unrelated to embeddings.

Out-of-scope for this pass (other open [NEEDS_MATT] markers unrelated
to Cortex embed arm, retained as-is for future passes):

- L140 "[NEEDS_MATT] Cortex dedup live `--apply`" — the live-arm
  receipt L37-38 records a dedup `--apply` run that removed 1
  duplicate + wrote 53055 rows
  (`ops/verification/20260423-190359-cortex-dedup-backfill.json`);
  dedicated closure deferred to a separate pass.
- L141 "[NEEDS_MATT] Arm `com.symphony.bluebubbles-health.plist`"
  — unrelated; unchanged.
- L142 "[NEEDS_MATT] X-intake reply-leg live smoke" — unrelated;
  unchanged.

Verification: `ops/verification/20260423-200253-cortex-embed-arm-closure.txt`

---

## Cortex Embeddings Phase-1 Author+Test (2026-04-23 10:57 MDT, Claude Code)

Commits: `9f0b7c4`, `89ad9fc`, `814f746`, `7eab1eb`

- `cortex/config.py` — `CORTEX_EMBEDDINGS_ENABLED` (default `0`), `CORTEX_EMBED_OPENAI_OK`, model/host vars
- `cortex/embeddings.py` — `OllamaProvider`, `OpenAIProvider`, `NullProvider`; `pack_vector`/`unpack_vector`; `embed_worker` async task
- `cortex/memory.py` — `memory_embeddings` table; `_embed_queue` + `set_embed_queue()`; `_maybe_enqueue()` hook in `store()` + `store_or_update()`; `search_semantic()`
- `cortex/engine.py` — `/memories?semantic=1` blended keyword+vector search; `embed_worker` task started on startup (guarded by flag)
- `scripts/cortex_embed_backfill.py` — `--dry-run` default, `--apply`, batched, JSON summary
- `ops/tests/test_cortex_embeddings.py` — 8 tests, all pass (NullProvider, no network)

**Default posture: `CORTEX_EMBEDDINGS_ENABLED=0` — embeddings disabled in this PR.**
Ollama is reachable on Bob but `nomic-embed-text` not yet pulled.

- [NEEDS_MATT] Ordered arm sequence (do in order):
  1. Run dedup backfill first: `docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --apply`
  2. Pull embedding model: `ollama pull nomic-embed-text`
  3. `bash scripts/set-env.sh CORTEX_EMBEDDINGS_ENABLED 1`
  4. `docker compose restart cortex`
  5. `docker exec cortex python3 /app/scripts/cortex_embed_backfill.py --apply --provider ollama`
  6. Verify: `docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memory_embeddings;"`

Verification: `ops/verification/20260423-105744-cortex-embeddings.txt`

---

## Five-Prompt Reconciliation (2026-04-23 10:48 MDT, Claude Code)

Parent-agent audit of the five prompts added in `361ac56`. MacBook
checkout is in sync with `origin/main` at `15484a3` — nothing pushed,
nothing rebased, harness-owned `.claude/` / `.mcp.json` / `CLAUDE.md`
dirty state preserved.

| # | Prompt | Outcome |
|---|--------|---------|
| 1 | `bluebubbles-health-plist` | Completed + verified — `4b7485f` |
| 2 | `bluebubbles-attachment-bodies` | Completed + verified — `fe5f778`, `525940d` |
| 3 | `cortex-dedup-upsert` | Completed + verified (re-run) — `716b14a`, `da532f3`, `758b31f`, `bc8ffdf`, `50feea8` |
| 4 | `cortex-embeddings` | **Not run** — no commits, no verification, no STATUS_REPORT entry |
| 5 | `x-intake-reply-leg-phases-2-6` | Completed + verified — `6aa2102`, `7bc0f5e`, `cce41c4`, `c0b9d1f`, `15484a3` |

Embeddings was the only unrun prompt. Its stop-condition ("dedup must
land first") is now satisfied, so it is cleared to run.

- [FOLLOWUP] Run `.cursor/prompts/2026-04-23-cline-cortex-embeddings.md` — author+test only; live `--apply` on `brain.db` stays `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]`.
- [FOLLOWUP] `docker compose up -d --build cortex` on Bob — unblocks three items in one command: exposes `GET /api/bluebubbles/health` (clears `cortex_http_404`); lets attachment-enrichment run against live webhooks; permits V6 live-DB inspection of `idx_memories_dedupe_key`.
- ~~[NEEDS_MATT] Cortex dedup live `--apply` (after backup + rebuild).~~ ✅ Apply ran 2026-04-23 — receipts `ops/verification/20260423-173120-cortex-dedup-backfill.json` + `20260423-173840-cortex-dedup-backfill.json` (each `rows_deleted=1`); runbook `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md` marked `Status: DONE`.
- ~~[NEEDS_MATT] Arm `com.symphony.bluebubbles-health.plist` via `cp` + `launchctl load`.~~ ✅ Armed 2026-04-23 10:15 MDT — receipt `ops/verification/20260424-083518-bluebubbles-health-arm.txt` (`run interval = 300`, `.err` empty, BlueBubbles 1.9.9 healthy).
- [NEEDS_MATT] X-intake reply-leg live smoke — `ALLOWED_TEST_RECIPIENTS`, `CORTEX_REPLY_DRY_RUN=0`, rebuild, one reply to Matt's own number, then restore `=1`. (No evidence yet — runbook `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md` still `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` + `[EXTERNAL_SEND]`. See also `.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`.)

Verification: `ops/verification/20260423-164850-five-prompt-reconciliation.md`

---

## X-Intake Reply-Leg Phases 2–6 — Author+Test (2026-04-23 10:44 MDT, Claude Code)

Commits: `6aa2102`, `7bc0f5e`, `cce41c4`, `c0b9d1f`

- `integrations/x_intake/reply_actions/action_store.py` — `thread_guid` column + migration; `AlreadyUsed` exception; `list_open_slots()`; `lookup_by_slot()`
- `integrations/x_intake/reply_actions/listener.py` — `process_message()` + `run_listener()` (subscribes to `events:imessage`, parse → lookup → dispatch → ack)
- `integrations/x_intake/reply_actions/dispatcher.py` — `HANDLER_REGISTRY` (3 handlers: `cortex_remember`, `cortex_dismiss`, `escalate_to_matt`); `Dispatcher` with rate-limit (10/60s) + idempotency
- `integrations/x_intake/reply_actions/ack.py` — `send_ack()` dry-run by default; ring buffer; ndjson log
- `docker-compose.yml` — `CORTEX_REPLY_DRY_RUN=1` + `ALLOWED_TEST_RECIPIENTS` added to x-intake
- `ops/tests/test_reply_leg_e2e.py` + `test_reply_leg_guards.py` — 11 tests, all pass

**Test result:** 11 passed, 0.03s. **Outbound ACKs remain in `CORTEX_REPLY_DRY_RUN=1` mode.**

- [NEEDS_MATT] Enable live sends (still gated — no evidence of a live smoke; authoritative runbook is `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`, which requires Matt-only `ALLOWED_TEST_RECIPIENTS`, supervised DRY_RUN flip, and immediate restore. Follow-up evidence-capture prompt: `.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`):
  1. `bash scripts/set-env.sh ALLOWED_TEST_RECIPIENTS "iMessage;-;+19705193013"`
  2. `bash scripts/set-env.sh CORTEX_REPLY_DRY_RUN 0`
  3. `docker compose up -d --build x-intake`
  4. Send one test reply; verify `data/x_intake/reply_acks.ndjson` + Cortex memory
  5. Re-set `CORTEX_REPLY_DRY_RUN=1` after test

Verification: `ops/verification/20260423-104458-x-intake-reply-leg-phases-2-6.txt`

---

## Cortex Dedup — re-run verification (2026-04-23 10:34 MDT, Claude Code)

Re-run confirming all prior dedup work intact. 12 tests pass (0.03s). Dry-run backfill
produces correct merge plan. Docker not running so V6 live DB inspection deferred.

- ~~[NEEDS_MATT] Live backfill (after Docker up):
  `cp /data/cortex/brain.db /data/cortex/brain.db.bak.$(date +%Y%m%d-%H%M%S)`
  `docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --apply`~~ ✅ Ran 2026-04-23; receipts `ops/verification/20260423-173120-cortex-dedup-backfill.json` + `20260423-173840-cortex-dedup-backfill.json` (each `rows_deleted=1`, idempotent).
- [FOLLOWUP] V6 live index verification once Cortex container is running.

Verification: `ops/verification/20260423-103428-cortex-dedup.txt`

---

## Cortex Dedup (UNIQUE/Upsert) Phase-1 Author+Test (2026-04-23 10:32 MDT, Claude Code)

Commits: `716b14a`, `da532f3`, `758b31f`

- `cortex/memory.py` — `dedupe_key TEXT DEFAULT NULL` column; `CREATE UNIQUE INDEX … WHERE dedupe_key IS NOT NULL`; `_MIGRATE_COLUMNS` + `_MIGRATE_INDEXES` for existing DBs; `_canonical_key()` (hint → URL → msg-prefix → None); `store_or_update()` upsert (merges importance/tags/metadata on collision)
- `cortex/engine.py` — `/remember` accepts optional `dedupe_hint` + `overwrite_content`, routes to `store_or_update`
- `scripts/cortex_dedup_backfill.py` — `--dry-run` (default) / `--apply`; prints backup command; writes JSON summary to `ops/verification/` on apply; refuses to run on locked DB
- `ops/tests/test_cortex_dedup.py` — 12 tests, all pass (0.07s)

**Test result:** 12 passed in 0.07s

- ~~[NEEDS_MATT] Live backfill against `brain.db` (run after `docker compose up -d --build cortex`):
  1. `cp /data/cortex/brain.db /data/cortex/brain.db.bak.$(date +%Y%m%d-%H%M%S)`
  2. Verify Cortex is not actively writing (or stop container)
  3. `docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --apply`~~ ✅ Ran 2026-04-23 — receipts `ops/verification/20260423-173120-cortex-dedup-backfill.json` + `20260423-173840-cortex-dedup-backfill.json`; runbook `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md` `Status: DONE`.
- [FOLLOWUP] V6 live DB inspection once Docker is up — confirm `idx_memories_dedupe_key` present

Verification: `ops/verification/20260423-103234-cortex-dedup.txt`

---

## BlueBubbles Attachment Bodies + Reply Consolidation (2026-04-23 10:20 MDT, Claude Code)

Commits: `fe5f778`, `525940d`

- `cortex/bluebubbles.py` — `AttachmentRef` + `MessageEvent` TypedDicts; `normalize_webhook_payload` returns `MessageEvent`; `_enrich_attachments` fetches+stores bodies (5 MiB/attachment, 8 MiB/event cap, 9-type MIME allowlist, sha256 dedup, atomic write)
- `cortex/dashboard.py` — `/api/symphony/bluebubbles/health` now routes through `BlueBubblesClient().ping()` (removed direct httpx block)
- `.gitignore` — `data/bluebubbles/attachments/` added
- `ops/tests/test_bluebubbles_attachments.py` — 14 tests, all pass
- `ops/tests/fixtures/bluebubbles/tiny.png` — 69-byte 1×1 PNG fixture

**Test result:** 14 passed in 0.07s

- [FOLLOWUP] `docker compose up -d --build cortex` — running container is pre-fix; `/api/bluebubbles/health` will 404 until rebuilt
- [FOLLOWUP] `cortex_http_404` in bluebubbles-health.sh will clear after Cortex rebuild

Verification: `ops/verification/20260423-102015-bluebubbles-attachment-bodies.txt`

---

## BlueBubbles Health Plist — Phase 1 Add+Lint (2026-04-23 10:13 MDT, Claude Code)

Added `setup/launchd/com.symphony.bluebubbles-health.plist`. Not loaded — arm step is `[NEEDS_MATT]`.

- `plutil -lint`: PASS
- `bash -n scripts/bluebubbles-health.sh`: PASS
- All 46 launchd plists lint+label OK (`ops/tests/test_launchd_plists.py` added)
- Live probe: BlueBubbles server healthy (v1.9.9); Cortex `/api/bluebubbles/health` returns 404

- ~~[NEEDS_MATT] Arm the LaunchAgent:
  `cp setup/launchd/com.symphony.bluebubbles-health.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist`~~ ✅ Armed 2026-04-23 10:15 MDT — receipt `ops/verification/20260424-083518-bluebubbles-health-arm.txt` (already-loaded state documented; no double-load performed).
- [FOLLOWUP] Add `GET /api/bluebubbles/health` to Cortex — currently 404; script exits 0 but cortex_health reports "unreachable".

Verification: `ops/verification/20260423-101329-bluebubbles-health-plist.txt`

---

## unfinished-setup audit — remaining-items Cline prompt fan-out (2026-04-23 MDT, Claude Code)

Docs-only pass: wrote five self-contained, copy/paste-runnable Cline
task prompts covering every remaining open item from the 2026-04-23
unfinished-setup audit reconciliation
(`ops/verification/20260423-155053-unfinished-setup-reconciliation.txt`).
No runtime changes were performed on Bob or anywhere else. No launchd
state mutated, no sudo, no ports opened, no secrets read, no external
messages/posts. Unrelated dirty working-tree items (`.claude/**`,
`.mcp.json`, `CLAUDE.md` sandbox churn) were preserved as-is per the
parent instruction.

Prompts added under `.cursor/prompts/`, each with: `autonomy` metadata
block (category / risk / trigger / `Status: active`), goal + non-goals,
explicit safety gates ("no secrets / no destructive / no external sends
/ no recurring jobs loaded / Bob runtime marked `[BOB_CLINE_ONLY]` /
live-mutation steps marked `[NEEDS_MATT]`"), safe inspection steps,
scoped implementation tasks, bounded verification checklist (static
checks + pytest + path-exists + sample fixtures + optional bounded
`[BOB_CLINE_ONLY]` probes), required artifacts (STATUS_REPORT entry,
`ops/verification/<stamp>-*.txt` receipt, commits, push), and
stop-conditions:

1. `2026-04-23-cline-bluebubbles-attachment-bodies.md` — inbound
   attachment-body capture (size + mime gate, sha256 dedup path) and
   outbound-reply consolidation through `cortex.bluebubbles.send_text`.
2. `2026-04-23-cline-bluebubbles-health-plist.md` — add + lint a
   `com.symphony.bluebubbles-health` LaunchAgent plist wrapping
   `scripts/bluebubbles-health.sh --json`. Phase-1 add/lint only; arming
   via `launchctl` is a separate `[NEEDS_MATT]` step, mirroring how the
   now-closed network-monitoring prompts split add-then-arm.
3. `2026-04-23-cline-cortex-dedup-upsert.md` — Cortex `memories` table
   gets a `dedupe_key` column + partial UNIQUE index, canonical-key
   helper, `store_or_update` upsert path, and a one-shot backfill script
   with a dry-run default. Live `--apply` is `[NEEDS_MATT]` +
   `[BOB_CLINE_ONLY]`, gated on a mandatory DB backup.
4. `2026-04-23-cline-cortex-embeddings.md` — new `memory_embeddings`
   table, local-first Ollama / OpenAI-opt-in / Null-provider
   embedding writer gated by `CORTEX_EMBEDDINGS_ENABLED=0` default,
   `search_semantic` query path, and a dry-run-default backfill script.
   Ordered to run **after** the dedup prompt on Bob.
5. `2026-04-23-cline-x-intake-reply-leg-phases-2-6.md` — adds the
   inbound-reply listener, validator, explicit-allowlist
   executor/router, consolidated outbound ACK (defaulting to
   `CORTEX_REPLY_DRY_RUN=1`), and fixture-driven offline e2e tests.
   Requires the attachment-bodies prompt to have landed first so the
   consolidated `send_text` outbound path exists.

Order for Matt / future Cline to run them:
attachment-bodies → health-plist → dedup → embeddings → reply-leg.

Verification (docs-only):

- `ls .cursor/prompts/2026-04-23-cline-*.md` — five new files visible.
- `grep -nE "^Status:" .cursor/prompts/2026-04-23-cline-*.md` — all
  five are `Status: active`.
- `grep -nE "\[BOB_CLINE_ONLY\]|\[NEEDS_MATT\]"` hits present in every
  file where runtime mutation is scoped.
- `git diff --stat` shows prompt files + this STATUS_REPORT entry
  only; no runtime code touched.

Artifact this pass: this section + the five prompt files. No separate
`ops/verification/*.txt` was written because the work is
prompts-only documentation; the commit itself is the receipt.

---

## unfinished-setup audit reconciliation — network-monitoring closed, stale prompts marked done (2026-04-23 09:50 MDT, Claude Code)

Review-first docs-only pass per parent workflow: inspect what has already
been fixed before acting on the prior "top gap." The review confirmed that
the `docs/audits/2026-04-23-unfinished-setup-audit.md` TL;DR gap
(host-network monitoring supervision) is ✅ as of commit `cece843` and the
Run-4 verification. No runtime work was done on Bob; no launchctl / sudo /
Docker / Redis / external-message action was taken.

**What changed (repo-only, docs + prompt status + verification receipt):**
- `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`
  flipped `Status: active` → `Status: done` with a "Closed" block linking
  to `ops/verification/20260423-094342-network-monitoring-launchd.txt`.
- `.cursor/prompts/2026-04-23-cline-network-monitoring-arm-and-fix.md`
  same flip, noting both blockers closed (arm via `4dbd996`; `security_utils`
  via `329ea8c` — inlined, not shimmed).
- `docs/audits/2026-04-23-unfinished-setup-audit.md` TL;DR now has a
  CLOSED block at the top with evidence; original text preserved below it.
- New artifact: `ops/verification/20260423-155053-unfinished-setup-reconciliation.txt`
  (full review + audit-item reconciliation + safety checklist).

**What was NOT changed:** no edits to `tools/network_guard_daemon.py`,
`tools/network_dropout_watch.py`, or either plist — Run-4 already proved
they are correct. Unrelated sandbox dirty-tree items
(`.claude/**`, `.mcp.json`, `CLAUDE.md`) preserved, not staged.

**Why this, not another gap:** the remaining audit items (BlueBubbles
health plist, Cortex UNIQUE/embeddings, X-intake reply-leg Phases 2–6)
each need more scope than a bounded review pass can safely carry. The
only real durable-artifact risk from the current tree was two
`Status: active` prompts whose goals were already met — leaving them
active would let a future agent re-patch already-correct code or churn
Bob's LaunchAgent state.

- [FOLLOWUP] Housekeeping only (unchanged): prune `logs/network-guard.err`
  (8 MB pre-fix) after a stable day: `cp /dev/null logs/network-guard.err`.
- [FOLLOWUP] Housekeeping only (unchanged): optional
  `cp setup/launchd/com.symphony.network-dropout-watch.plist ~/Library/LaunchAgents/`
  for standard agents-dir visibility.

Verification: `ops/verification/20260423-155053-unfinished-setup-reconciliation.txt`
Source audit: `docs/audits/2026-04-23-unfinished-setup-audit.md`
Closure evidence: `docs/audits/2026-04-23-04-network-monitoring-launchd-verification.md`
                  + `ops/verification/20260423-094342-network-monitoring-launchd.txt`

---

## network-monitoring run 4 — FULL PASS, both agents healthy (2026-04-23 09:43 MDT, Claude Code)

First run where both network-monitoring agents are armed, running, and healthy.

- `com.symphony.network-guard` PID 56949, exit=0, writing healthy records every 60s ✅
- `com.symphony.network-dropout-watch` PID 52527, exit=0, gateway 0.6ms / WAN 13ms ✅
- `logs/network-guard.err` stopped growing at 09:40 (pre-fix); no new errors since.
- Both plists lint PASS. Both tools compile PASS.

- [FOLLOWUP] Prune `logs/network-guard.err` (8 MB / 143k lines of pre-fix tracebacks) after a stable day: `cp /dev/null logs/network-guard.err`
- [FOLLOWUP] Copy dropout-watch plist to `~/Library/LaunchAgents/` for standard agents-dir visibility.

Verification: `ops/verification/20260423-094342-network-monitoring-launchd.txt`
Audit doc: `docs/audits/2026-04-23-04-network-monitoring-launchd-verification.md`

---

## network-monitoring phase-2 prompt drafted — fix security_utils import (2026-04-23 15:26 MDT, Claude Code)

Repo-only planning pass following the Phase-1 commit `9e12fc6`. Reviewed the
two outstanding `[NEEDS_MATT]` blockers against the current tree and
produced a durable Cline prompt + planning artifact so Phase-2 can run on
Bob without another round-trip.

**Review findings (sandbox read-only, no Bob access):**
- Commit `9e12fc6` correctly established both blockers. `git log --all --
  oneline -- '**/security_utils*'` returns empty; the module was never
  committed. Two callers import it: `tools/network_guard_daemon.py:32`
  (`sanitize_for_telegram`) and `tools/imessage_watcher.py:22`
  (`hash_text, mask_contact, mask_name, redact_text`). Any fix must keep
  imessage_watcher working.
- Phase-1 artifacts (plist + audit doc + verification txt + STATUS_REPORT
  entry) are internally consistent and cross-link cleanly.

**New artifacts this pass:**
- `.cursor/prompts/2026-04-23-cline-network-monitoring-arm-and-fix.md` —
  copy-paste-minimal Cline task for Bob. Follows
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md` (Category: ops, Risk
  tier: medium, Trigger: manual, Status: active). Covers both blockers in
  one bounded run: create `tools/security_utils.py` as a stdlib-only shim,
  apply a 3-line `sys.path` bootstrap to both callers, dry-run
  `network_guard_daemon.py --once` with Telegram env unset, bootstrap
  dropout-watch, bootout+bootstrap network-guard, verify state files and
  fresh log lines, prune the 8 MB `.err`, commit and push.
- `ops/verification/20260423-152628-network-monitoring-phase2-plan.txt` —
  planning/verification artifact documenting this review and the Phase-2
  rationale.

- [FOLLOWUP] Run `.cursor/prompts/2026-04-23-cline-network-monitoring-arm-and-fix.md`
  on Bob via Cline. Expected commit message:
  `ops(network-mon): fix security_utils import + arm dropout-watch (phase-2)`.

- [NEEDS_MATT] Still the same two blockers from the Phase-1 section below,
  now bundled into a single Cline task. If Matt wants to arm dropout-watch
  standalone without the full Cline task, the existing one-liner still
  works (no sudo):
  `launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-dropout-watch.plist`
  The network-guard security_utils fix still requires the full Cline task.

Review artifact: `ops/verification/20260423-152628-network-monitoring-phase2-plan.txt`
Phase-2 Cline prompt: `.cursor/prompts/2026-04-23-cline-network-monitoring-arm-and-fix.md`
Phase-1 audit doc: `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`

**Merge note (2026-04-23 15:30):** Between drafting this prompt and pushing,
`origin/main` landed two new commits: `fa914c5` (Phase-1 run-2 verification)
and `4dbd996` (dropout-watch armed + PATH fix — `/sbin:/usr/sbin` added so
`/sbin/ping` resolves under the LaunchAgent). That closes blocker #1
(`[NEEDS_MATT] Arm dropout-watch`) — already ✅ in the section below. The
Phase-2 Cline prompt remains valid for **blocker #2 only** (fix
`security_utils` import and reload `com.symphony.network-guard`). Phases 4
and 6 of that prompt (arm dropout-watch, log prune) can now be skipped or
downgraded to a verification-only check since dropout-watch is already
running.

---

## network-monitoring verification run 3 — dropout-watch confirmed healthy (2026-04-23 09:38 MDT, Claude Code)

Full re-run with dropout-watch now live. All checks pass.

- `com.symphony.network-dropout-watch`: PID 52527, running, health=healthy
  - Gateway 192.168.1.1: ok, 0.549 ms | WAN 1.1.1.1: ok, 15.897 ms
  - `.err` log: empty (0 bytes) — no errors
- `com.symphony.network-guard`: still crash-looping on `security_utils` import
  - `.log` last write: 2026-04-03 | `.err`: 143,415 lines, still growing

- ~~[NEEDS_MATT] Arm dropout-watch~~ ✅ Armed 2026-04-23 09:37 MDT
- [FOLLOWUP] Prune `logs/network-guard.err` once guard is fixed.
- ~~[NEEDS_MATT] Fix `tools/network_guard_daemon.py` `security_utils` crash~~ ✅ Fixed 2026-04-23 09:41 MDT — inlined `sanitize_for_telegram`, daemon now writing healthy records again.

Verification: `ops/verification/20260423-093828-network-monitoring-launchd.txt`
Audit doc: `docs/audits/2026-04-23-03-network-monitoring-launchd-verification.md`

---

## network-dropout-watch armed + PATH fix (2026-04-23 09:37 MDT, Claude Code)

`com.symphony.network-dropout-watch` LaunchAgent bootstrapped and running.
Found `ping` not in PATH (lives at `/sbin/ping`); added `/sbin:/usr/sbin` to
the plist and reloaded. Agent now reporting `health: healthy`:
- Gateway 192.168.1.1: ok, 0.6 ms
- WAN 1.1.1.1: ok, 16.5 ms

State file: `data/network_watch/dropout_watch_status.json` — `running: true`.

- ~~[NEEDS_MATT] Arm dropout-watch LaunchAgent~~ ✅ Done 2026-04-23 09:37 MDT

---

## network-monitoring launchd verification run 2 (2026-04-23 09:34 MDT, Claude Code)

Re-execution of network-monitoring setup prompt. No new files created; all prior
artifacts confirmed intact. Key findings unchanged: guard daemon still crash-looping
on `security_utils` (143k+ err lines, no new log since Apr 3); dropout-watch plist
spec verified key-by-key, all fields correct, not yet armed.

- [FOLLOWUP] Arm dropout-watch and confirm `data/network_watch/dropout_watch_status.json` shows `running: true`.
- [NEEDS_MATT] `launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-dropout-watch.plist`
- [NEEDS_MATT] Fix `tools/network_guard_daemon.py` `security_utils` import, then reload network-guard plist.

Verification: `ops/verification/20260423-093448-network-monitoring-launchd.txt`
Audit doc: `docs/audits/2026-04-23-02-network-monitoring-launchd-verification.md`

---

## network-monitoring launchd setup + verification (2026-04-23 09:15 MDT, Claude Code)

Phase-1 repo-only pass: added `com.symphony.network-dropout-watch` LaunchAgent
plist, observed existing `com.symphony.network-guard` state on Bob, documented
everything. No launchd state was mutated; no services were started or stopped.

**Findings — existing network-guard:**
- Plist lint: PASS. Loaded in `~/Library/LaunchAgents/` (installed Mar 10 — older than repo copy).
- Daemon is crash-looping since ~Apr 3: `ModuleNotFoundError: No module named 'security_utils'`.
  `.log` last wrote 2026-04-03; `.err` is 8 MB of repeated tracebacks today.
  **The network-guard daemon is not producing health records.**

**New artifact:** `setup/launchd/com.symphony.network-dropout-watch.plist`
- LaunchAgent (no sudo), `KeepAlive=true`, `ThrottleInterval=30`.
- Runs `tools/network_dropout_watch.py --watch --interval-sec 2.0`.
- `plutil -lint` PASS. **Not loaded** — arming is gated behind `[NEEDS_MATT]` below.

- [FOLLOWUP] Verify `data/network_watch/dropout_watch_status.json` is populated
  after Matt arms the new LaunchAgent; confirm `"health": "healthy"`.
- [FOLLOWUP] Prune `logs/network-guard.err` once the security_utils crash is fixed
  (currently 8 MB of repeated tracebacks).

- [NEEDS_MATT] Arm dropout-watch LaunchAgent (no sudo required):
  `launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-dropout-watch.plist`
  Then verify: `cat data/network_watch/dropout_watch_status.json`

- [NEEDS_MATT] Fix network-guard crash — resolve `security_utils` import in
  `tools/network_guard_daemon.py`, then reload:
  `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphony.network-guard.plist`
  `launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-guard.plist`

Verification: `ops/verification/20260423-091516-network-monitoring-launchd.txt`
Audit doc: `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`

---

## unfinished-setup audit + network-monitoring launchd follow-up prompt (2026-04-23 15:10, Claude Code)

Docs-only pass answering "look through the entire space and see what we
worked on and never setup." Cross-referenced the two 2026-04-23 audits
(bob-freezing runtime hangs + x-intake deep-dive) against the current
repo tree and produced a classification across *not set up / partially
set up / set up but unverified / already complete / unresolved*.

Correction vs. the prior in-memory summary: `setup/launchd/com.symphony.network-guard.plist`
**is** committed (verified this pass — `ls setup/launchd/` shows it,
and commits referencing it are in-tree). What is actually absent is a
committed launchd plist for `tools/network_dropout_watch.py` and any
committed verification artifact proving either network daemon is
currently loaded/healthy on Bob.

Highest-priority next setup gap identified: the host-network monitoring
supervision story. Scoped as a Cline-first follow-up at
`.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`.
The prompt is read-only on Bob except for writing a verification file
and committing the new plist + docs; it explicitly does **not**
`launchctl load` anything and leaves the actual arm step behind a
`[NEEDS_MATT]` gate.

- [FOLLOWUP] Cline / Bob: run
  `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`
  to capture the current `launchctl list | grep network-guard` state,
  add a committed plist for `tools/network_dropout_watch.py`, write
  the paired `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`
  artifact, and update this report. Do not load the new plist.
- [NEEDS_MATT] Decide when to `sudo launchctl bootstrap` the new
  network-dropout-watch plist on Bob. Repo-only until you say go.

Audit: `docs/audits/2026-04-23-unfinished-setup-audit.md`.
Follow-up prompt: `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`.

TODO references:
- [ ] arm `com.symphony.network-dropout-watch` on Bob (needs Matt)
- [ ] capture `ops/verification/<stamp>-network-monitoring-launchd.txt`
      receipt proving both daemons supervised and producing events
- [ ] resolve approval-drainer plist contradictory status sections
- [ ] prune `pending_approvals` backlog (237) and accumulated
      `ops/verification/` artifacts (pre-existing FOLLOWUPs, unchanged)

---

## bob-watchdog required-source subshell fix + [FOLLOWUP] alert (2026-04-23 14:58, Claude Code)

Bob deployed ba3c298 (the bash-3.2 hotfix) and the log showed:

```
2026-04-23 08:52:52 [watchdog] --- tick --- v=2026-04-23.3-bash3-required repo=/Users/bob/AI-Server resolved=1
2026-04-23 08:52:54 [watchdog]   required services source=none
2026-04-23 08:52:55 [watchdog] --- done ---
```

Repo root resolved, but `source=none` instead of
`override:/Users/bob/AI-Server/ops/bob-watchdog.required`.

**Root cause.** `resolve_required()` is called via command substitution
(`required=$(resolve_required)`) which runs it in a subshell. Assignments
to `REQUIRED_SOURCE` inside the function are discarded when the subshell
exits — the parent shell's copy stays at its module-scoped default of
`"none"`. The override file was being read (grep output populated
`required`), but the source label was always reported wrong.

**Fix (version `2026-04-23.4-required-source-fix`).**

1. `scripts/bob-watchdog.sh` — write the resolved source to
   `$STATE_DIR/required_source` from inside `resolve_required()`, read it
   back in the parent shell in `check_containers()`. Subshell-safe.
   Clear the state file at the top of each tick so a stale value from
   the previous tick cannot leak through if `resolve_required()` is
   never reached (e.g., docker down).
2. `scripts/bob-watchdog.sh` — widen the "no services resolved"
   diagnostic to include `compose_yml`, `override_path`,
   `override_exists`, `override_readable`, `override_lines`. When the
   repo is resolved but the override file is missing/unreadable, emit
   `[FOLLOWUP] required service override missing: <path>` so the
   watchdog cannot silently pass the check. Also require the override
   file be readable, not just present.
3. `setup/install_bob_watchdog.sh` — `--status` now prints the override
   file path, line count, and readable/missing status; `--deploy-system`
   warns (non-fatal) when the override file is absent from the repo.

**Checks run locally.** `bash -n` on both scripts, `--check` passes,
sandbox tick simulation (stub docker, --dry-run) confirms:
- override present → `source=override:<path>` and the missing-container
  list is populated correctly;
- override absent → `source=compose`, detailed diag line, and
  `[FOLLOWUP] required service override missing` alert fire as expected.

- [FOLLOWUP] Cline / Bob: pull, run `bash setup/install_bob_watchdog.sh
  --status` (expect Required-services READABLE with lines ≥ 17), then
  `sudo bash setup/install_bob_watchdog.sh --deploy-system`, kickstart
  the daemon, tail `/usr/local/var/log/bob-watchdog.log` and confirm
  `v=2026-04-23.4-required-source-fix` and
  `required services source=override:/Users/bob/AI-Server/ops/bob-watchdog.required`.
  If the line instead shows `source=compose` with a `[FOLLOWUP]` alert,
  the override file failed to land in the pull — investigate and deploy
  manually.

Verification artifact:
`ops/verification/20260423-145811-watchdog-required-source-diagnostics.txt`.

---

## bob-watchdog bash-3.2 + required-services override hotfix (2026-04-23 14:46, Claude Code)

After the 14:14 root-resolve fix deployed cleanly, the LaunchDaemon log
still showed the tick banner but two downstream problems:

```
/usr/local/bin/bob-watchdog.sh: line 327: mapfile: command not found
container check skipped (no compose services resolved)
```

Root cause: `mapfile` is bash 4+. The root LaunchDaemon runs under
macOS system `/bin/bash` 3.2.57, so the two `mapfile -t file_args < <(...)`
calls silently killed `resolve_required` (line 327) and the recovery
path (line 422). Even with a bash 4 interpreter the compose path was
fragile — `docker compose config --services` fails to expand `.env`
under the root launchd environment.

**Fix (this commit, version marker `2026-04-23.3-bash3-required`):**

1. `scripts/bob-watchdog.sh` — replaced both `mapfile` sites with bash-
   3.2-compatible `while IFS= read -r line; do file_args+=("$line");
   done < <(compose_file_args)`. No bash 4+ features remain (no
   mapfile/readarray, no associative arrays, no `${var^^}` case ops).
   Added `REQUIRED_SOURCE` tracking so every tick logs which source
   the required-service list came from:
   `required services source=override:<path>` | `compose` | `none`.
   Switched `\s` PCRE class → POSIX `[[:space:]]` for BSD grep.
2. `ops/bob-watchdog.required` (new) — authoritative list of 18
   required compose services (derived 2026-04-23 from the
   `services:` block of docker-compose.yml). Optional/lab/decom
   services are explicitly excluded and handled by the existing
   `OPTIONAL_SERVICES` allowlist. `bob-watchdog.sh` reads this
   directly from the repo working copy — no install-side change is
   required; `git pull` is sufficient to place it where the daemon
   looks for it.

**- [NEEDS_MATT] Deploy to Bob (one sudo command):**

```
cd /Users/bob/AI-Server && git pull --ff-only origin main && \
  sudo bash setup/install_bob_watchdog.sh --deploy-system && \
  sleep 70 && tail -n 30 /usr/local/var/log/bob-watchdog.log
```

Expected log shape:

```
--- tick --- v=2026-04-23.3-bash3-required repo=/Users/bob/AI-Server resolved=1
[watchdog]   required services source=override:/Users/bob/AI-Server/ops/bob-watchdog.required
```

and NO `mapfile: command not found` / `container check skipped` lines.

Full report: `ops/verification/20260423-144615-watchdog-bash3-required-services-hotfix.txt`

---

## bob-watchdog LaunchDaemon repo-root resolution fix (2026-04-23 14:14, Claude Code)

After the container-recovery hotfix was deployed to the system copy at
`/usr/local/bin/bob-watchdog.sh`, the LaunchDaemon log began repeating:

```
2026-04-23 08:08:26 [watchdog] container check skipped (no compose services resolved)
```

Root cause: the script's repo-root resolution was fragile when the binary
was run from `/usr/local/bin` by a root-owned LaunchDaemon. If
`$BOB_REPO_DIR` was unset or pointed at an inaccessible path, the fallback
`/Users/bob/AI-Server` silently failed the `docker-compose.yml` existence
check, `resolve_required` returned empty, and `check_containers` emitted
the terse skip line with no diagnostics.

**Fix (this commit):**

1. `scripts/bob-watchdog.sh` — new `resolve_repo_root()` with preference
   order `AI_SERVER_ROOT` → `BOB_REPO_DIR` → `/Users/bob/AI-Server` →
   inferred from `$BASH_SOURCE`. Only candidates that actually contain
   `docker-compose.yml` are accepted. Added `WATCHDOG_VERSION` marker
   (logged every tick — stale `/usr/local/bin` copies are now obvious).
   Skip-path now emits diagnostics (`resolved=… repo_dir=… cwd=…
   compose_yml=present/missing override=…`). When repo is unresolvable,
   main loop logs an actionable `[ALERT]` and skips stack checks instead
   of spinning on empty results. Recovery path now uses explicit
   `-f <repo>/docker-compose.yml` so cwd-relative discovery is never
   depended on.
2. `scripts/com.symphony.bob-watchdog.plist` (LaunchDaemon) and
   `ops/launchd/com.symphony.bob-watchdog.plist` (LaunchAgent) — added
   `<WorkingDirectory>/Users/bob/AI-Server</WorkingDirectory>` and
   `AI_SERVER_ROOT=/Users/bob/AI-Server` to `EnvironmentVariables`.
3. `setup/install_bob_watchdog.sh` — new `--deploy-system` mode for the
   sudo-required path. Installs `/usr/local/bin/bob-watchdog.sh` with
   mode 0755, copies the LaunchDaemon plist, sha256-verifies the system
   copy matches the repo copy (stale detection), reloads the daemon,
   kickstarts one tick.

**- [NEEDS_MATT] Deploy to Bob (one sudo command):**

```
cd /Users/bob/AI-Server && git pull --ff-only origin main && \
  sudo bash setup/install_bob_watchdog.sh --deploy-system && \
  sleep 70 && tail -n 25 /usr/local/var/log/bob-watchdog.log
```

Expected log shape after deploy:

```
--- tick --- v=2026-04-23.2-root-resolve repo=/Users/bob/AI-Server resolved=1
```

and NO `container check skipped` / `repo root not resolvable` / `unknown
shorthand flag: 'd'` lines.

Full report: `ops/verification/20260423-141455-watchdog-launchdaemon-root-fix.txt`

---

## bob-watchdog container-recovery hotfix (2026-04-23, Claude Code)

Fixed a three-bug compound in `scripts/bob-watchdog.sh` that had the
watchdog flapping once a minute:

1. Required-container list was a stale hard-coded literal; it still paged
   on `mission-control`, `knowledge-scanner`, `openwebui`, `remediator`,
   and `context-preprocessor` — all decommissioned and no longer in
   `docker-compose.yml` (see entries at lines 818 / 834 / 953).
2. Recovery command was `$COMPOSE up -d --no-build` (word-split string).
   In environments where the `docker compose` plugin doesn't resolve
   cleanly, docker treated `-d` as a top-level flag and emitted
   `unknown shorthand flag: 'd' in -d`.
3. "Containers recovered" was logged regardless of exit code or post-
   recovery state, so the failed command produced a green log line and
   the alert kept flapping.

Changes:

- `COMPOSE=(docker compose)` array; every call uses `"${COMPOSE[@]}"`.
- Required list now resolves from (1) optional operator-override file
  `ops/bob-watchdog.required`, else (2) `docker compose config --services`
  (bounded 15 s), else (3) skip the check entirely — we never page on a
  phantom list again.
- `OPTIONAL_SERVICES` allowlist for decommissioned/lab containers; misses
  are logged at most once per hour and never trigger recovery.
- Recovery bounded at 180 s; "Containers recovered" is logged only when
  exit == 0 **and** every previously-missing required container is
  visible in `docker ps`. Any other outcome logs an explicit `[ALERT]`.
- New flags: `--check` (bash-n only), `--dry-run` (log-only tick).

Verification: `ops/verification/20260423-134859-watchdog-container-recovery-hotfix.txt`
lists the Bob-side commands (`bash scripts/bob-watchdog.sh --check`,
`--dry-run`, etc.).

---

## bob-watchdog Bob runtime verification (2026-04-23 08:02 MDT, Claude Code)

Runtime check against the LaunchDaemon on Bob. Result: **PARTIAL PASS — manual
sudo step required to complete deployment.**

- `scripts/bob-watchdog.sh` (repo copy): hotfix confirmed correct. Dry-run and
  live invocations both produced clean ticks — no `unknown shorthand flag`,
  no false `Containers recovered`, no alerts for decommissioned containers.
- `/usr/local/bin/bob-watchdog.sh` (system daemon copy): still the pre-hotfix
  version (mtime Apr 4). The LaunchDaemon plist
  (`/Library/LaunchDaemons/com.symphony.bob-watchdog.plist`) runs this path,
  not the repo copy, so all three original bugs remain active in the system log.
- User-level LaunchAgent (`~/Library/LaunchAgents/`) correctly uses the repo
  copy — its log (`data/task_runner/bob-watchdog.log`) shows clean ticks.

- ~~**[NEEDS_MATT] Deploy hotfix to system daemon**~~ ✅ Deployed at 08:08:23 MDT.
  `setup/install_bob_watchdog.sh` now handles this automatically — it deploys
  `scripts/bob-watchdog.sh` to `/usr/local/bin/bob-watchdog.sh` and verifies
  SHA-256 checksum on every install run.

Post-deploy system log confirms all three bugs gone: no `unknown shorthand flag`,
no false `Containers recovered`, no decommissioned-container alerts.

- [FOLLOWUP] Create `ops/bob-watchdog.required` (one service per line) so the
  container-recovery check uses a known-good list instead of `docker compose
  config --services`, which fails in the root launchd environment due to missing
  `.env` expansion. Current safe fallback: check is skipped (logs
  `container check skipped (no compose services resolved)`) — no false alerts,
  but recovery is disabled until the override file exists.

Full reports: `ops/verification/20260423-080233-watchdog-hotfix-bob-runtime-check.txt`,
`ops/verification/20260423-081034-watchdog-hotfix-bob-runtime-check-updated.txt`

---

## X-intake deep-dive audit + reply-action design (2026-04-23, Claude Code)

Audit-and-design pass covering the full X-intake pipeline, BlueBubbles notification path,
and a new interactive reply-action loop. No runtime changes were made.

New artifacts:

- `docs/audits/x-intake-deep-dive-audit.md` — end-to-end audit: fetch depth, thread
  hydration, link expansion, LLM summarization, Cortex writes, relevance gating, latency
  bottlenecks, dedup behavior, and a full Mermaid event-path diagram with per-hop failure
  modes.
- `config/reply_actions.schema.json` — machine-readable action catalog (6 actions: card,
  research, prototype, save, mute, open-thread), per-action safety flags, expiry defaults,
  confirmation requirements, hard denylist, and outbound template format.
- `ops/verification/20260423-reply-actions-design-verification.md` — lists files read,
  greps run, assumptions made, open questions, and a 6-phase implementation plan
  (Phase 0 = this audit → Phase 6 = production rollout).

Key findings:
- [FOLLOWUP] Dominant latency bottleneck: synchronous Ollama qwen3:8b (4–12 s). Parallelizing
  fetch + analysis or streaming early partial cards would cut perceived lag significantly.
- [FOLLOWUP] No reply-action parsing exists today — inbound iMessage replies are published to
  Redis but nothing consumes them for action routing. Phase 3–4 of the plan closes this.
- [FOLLOWUP] No cross-source dedup in Cortex — same tweet can be stored multiple times from
  different sources (iMessage + x-alpha-collector). A UNIQUE constraint or upsert is needed.
- [FOLLOWUP] No embeddings in Cortex memory — search is keyword-only LIKE queries. Semantic
  retrieval is a Phase 5+ improvement.
- Reply 3 ("spin test container") routes to a fully isolated testbed compose stack; spec is in
  `config/reply_actions.schema.json` under `testbed_integration`. Teardown: single command.

---

## Self-improvement loop — stream-driven intake (2026-04-22, direct Claude Code)

The self-improvement loop is now **source-driven from existing intake
streams** (x_intake + BlueBubbles/iMessage) rather than primarily
manual `add-url` captures. The always-on discovery → fetch/normalize →
summarize → classify → score → card → propose-prompt pipeline is
documented end-to-end in `docs/self-improvement-loop.md`.

New / changed:

- `scripts/self-improvement-collect.sh` — read-only, bounded collector
  with modes `scan`, `scan-x`, `scan-bluebubbles`, `sources`,
  `daemon-once`. Reads `x_intake/queue.db` and (on Bob) the local
  iMessage SQLite via `IMESSAGE_DB_PATH`. Never opens a network
  connection, never reads secrets, dedupes via content hash.
- `scripts/self-improve.sh` — `process` now runs the collector first.
  Added `scan`, `scan-x`, `scan-bluebubbles`, `sources`, `daemon-once`.
  Manual `add-url` / `add-note` kept as fallbacks.
- `.cursor/prompts/self-improvement/process-inbox.md` — cards now
  include source stream, original URL/excerpt, automation hypothesis,
  efficiency lever, affected subsystem, safe next prompt, and an
  explicit can-this-auto-run flag; output is prioritized by auto-run-
  eligible → Impact/Effort ratio, biased toward operational efficiency.
- `setup/launchd/com.symphony.self-improvement.plist` + `setup/install_self_improvement_watcher.sh`
  — launchd template (30-min cadence) and **dry-run-default** installer.
  The watcher is **not** loaded by this change. Recurring local jobs
  consume local compute and API budget; Matt enables on Bob manually
  after review.
- `docs/self-improvement-loop.md`, `docs/away-workflow.md`,
  `docs/autonomous-llm-orchestration.md` — updated to describe
  stream-driven ingest and the optional local watcher.

Safety constraints preserved: no blind execution of captured content,
no web browse by default, no secrets touched, no outbound
communications, no auto-enable of recurring jobs.

- [FOLLOWUP] After enabling the watcher on Bob, tighten `StartInterval`
  in the plist if 30 minutes proves too frequent given observed API
  spend in `ops/verification/dispatch-*` logs.

---

## Priority 1 Run — 2026-04-21T19:31 MDT (direct Claude Code, Sonnet 4.6 [1M])

**Run complete.** Commits: d0c0a27 (S1), dda86bd (S2), 6fa5188 (S3), bd10d07 (S4).

Stage results (final):

| Stage | Status | Artifact |
|---|---|---|
| 1 — Approval Drainer LaunchAgent | ✅ PASS | ops/verification/20260421-193143-approval-drainer-launchagent.md |
| 2 — BlueBubbles Webhook | ✅ PASS (partial) | ops/verification/20260421-193143-bluebubbles-webhook.md |
| 3 — Direct Claude Code 1M Docs | ✅ PASS | ops/verification/20260421-193143-direct-claude-1m-docs.md |
| 4 — Polymarket Funding Blocker | ❌ FAIL | ops/verification/20260421-193143-polymarket-funding-blocker.md |

### Stage 1 detail (2026-04-21 19:31 MDT)
LaunchAgent `com.symphony.approval-drainer` confirmed loaded. Plist at
`~/Library/LaunchAgents/com.symphony.approval-drainer.plist`. Script
`/app/approval_drain.py` exists in openclaw container (11677 bytes). No log
yet — first run at 02:00 MT Apr 22. Checks: loaded ✅, plist ✅, script ✅,
log N/A (pre-first-run).

### Stage 2 detail (2026-04-21 19:31 MDT)
BlueBubbles: server healthy (v1.9.9), Cortex aggregate healthy. Webhook endpoint
`/hooks/bluebubbles`. `inbound_count=0` — no messages since fresh install. Safe
synthetic ping not available without iMessage side-effect; manual test doc created
at `docs/bluebubbles/MANUAL_WEBHOOK_TEST.md`.

### Stage 3 detail (2026-04-21 19:31 MDT)
`docs/priority1-direct-runner.md` and `scripts/run-priority1-1m.sh` both exist.
Source prompt `.cursor/prompts/direct/priority1-stage-gate.md` exists. Added
Priority 1 runner discovery note to top of `AGENTS.md`.

### Stage 4 detail (2026-04-21 19:31 MDT)
3 active blockers — see artifact for full detail:
1. **DNS failure from VPN container (CRITICAL)**: polymarket-bot can't resolve external
   hostnames (`api.polymarket.com`, `api.kraken.com`, Polygon RPC). Blocks all strategy
   execution and on-chain reads. Fix: investigate WireGuard DNS config.
2. **MATIC gas = 0**: redeemer fires but can't submit on-chain txns.
3. **Wallet USDC unverified**: internal tracker shows 500.0 USDC but can't read on-chain
   due to DNS failure. Prior check (2026-04-17) showed $1.94 actual. Funding may still be
   needed.
- [NEEDS_MATT] Fund wallet `0xa791E3090312981A1E18ed93238e480a03E7C0d2` with USDC once DNS fixed.
- [NEEDS_MATT] Send ~0.5 MATIC/POL to same wallet for gas.
- [FOLLOWUP] Fix VPN DNS — check WireGuard DNS config in docker-compose.yml vpn service.

---

## Autonomous LLM orchestration layer (2026-04-22, direct Claude Code)

Added a repo-owned autonomous execution layer so the system can run without
Perplexity / Cline handholding and can route across Claude Code 1M, Cline
(200k, small tasks only), and local LLMs (summarization / planning / draft
prompts only — not authoritative for commits).

New files:

- `docs/autonomous-llm-orchestration.md` — routing rules + source-of-truth
  model (GitHub `origin/main` + `STATUS_REPORT.md` + `ops/verification/`).
- `docs/away-workflow.md` — practical SSH/Tailscale/VPN runbook for Matt.
- `scripts/ai-dispatch.sh` — single stable entry point. Modes: `status`,
  `models`, `run-priority1`, `run-prompt <file>`, `local-prompt <file>`.
  Prefers `claude-sonnet-4-6[1m]`, falls back to `claude-sonnet-4-20250514`,
  detects ollama / llama.cpp without requiring them. Logs to
  `ops/verification/dispatch-<ts>-<mode>.txt`. Never prints secrets.

Usage from Bob (or SSHed into Bob):

```bash
cd ~/AI-Server
bash scripts/ai-dispatch.sh status
bash scripts/ai-dispatch.sh run-priority1
```

- [FOLLOWUP] Optional: wire future connector lanes (Linear, Twilio, Zoho) as
  additional dispatcher modes rather than new entry points.

---

## Full system sweep (2026-04-21 14:35 MDT, Cline)

End-to-end pass against the new `.cursor/prompts/full-system-sweep-and-audit.md`
(this prompt was missing at run time — drafted this pass from `cline-prompt-Q-full-audit.md`
+ the 10-category campaign template). Full evidence:
`ops/verification/20260421-143522-full-system-sweep-and-audit.txt`.

### Headline

| Pillar            | State | Evidence                                                                    |
|-------------------|-------|-----------------------------------------------------------------------------|
| Containers        | 🟢    | 19/19 healthy (`docker compose ps`); all host-exposed ports 200 on /health |
| Data pipeline     | 🟢    | cortex 45 743 memories, jobs 41, emails 593, brain.db 148 MB, x_intake 35  |
| Autonomy          | 🟡    | preflight clean; verify-dump loop firing ~6/min (R4 below)                  |
| Messaging         | 🟡    | iMessage + BlueBubbles live (last BB inbound 2026-04-21T19:07Z); openclaw  |
|                   |       | `_get_redis` attribute warn every 10 s (R2 below)                          |
| Trading           | 🟡    | polymarket-bot container up; :8430 via VPN empty-reply; Kraken + funding   |
|                   |       | blockers unchanged from Reference: Trading State                           |

### Regressions table (see verification artifact for full evidence)

| R# | Regression                                  | Status    | Current value / location                                     |
|----|---------------------------------------------|-----------|--------------------------------------------------------------|
| R1 | `_host_redis_url` helper in imessage bridge | 🟢 GREEN  | `scripts/imessage-server.py:114` — helper + wrap call intact |
| R2 | openclaw `_get_redis` attribute missing     | 🟢 GREEN  | `_get_redis` async helper added to `Orchestrator` 2026-04-21 (close-yellow-gaps); warn spam gone |
| R3 | `verify-deploy.sh` Redis PING missing `-a`  | 🟢 GREEN  | `scripts/verify-deploy.sh` now loads `REDIS_PASSWORD` and passes `-a` on PING + LRANGE; `bash scripts/verify-deploy.sh` → `OK` |
| R4 | verify-dump watchdog-install hot loop       | 🟢 GREEN  | Stuck `ops/work_queue/pending/20260417-170500-install-watchdog.json` moved to `completed/`; 0 new `*-watchdog-install.txt` artifacts in last 2 min |
| R5 | `.env` unquoted ACH_BANK_NAME              | 🟢 GREEN  | `.env:348` now `ACH_BANK_NAME="First Bank of Colorado"`; `bash -c 'set -a; source .env'` returns the full value with no `Bank: command not found` |
| R6 | `pending_approvals` backlog re-accumulated  | 🟡 YELLOW | Drain fired 2026-04-21 15:01: 346 expired (>7d cutoff) / 237 still pending. Governed by new `setup/launchd/com.symphony.approval-drainer.plist` (02:00 MT daily, drained-only) |
| R7 | `follow_up_log` auto-send never fires       | 🟢 GREEN  | Canonical DB is `data/openclaw/follow_ups.db` (not `data/email-monitor/…`). Engine write-path verified with synthetic row via `scripts/verify_follow_up_log.py`; `_record_sent` promoted from DEBUG to INFO logging so future 0-row regressions are visible |
| R8 | Dropbox `/preview/` links anywhere          | 🟢 GREEN  | `scripts/dropbox-link-validate.sh` → OK across root + knowledge/ |

### New follow-ups

- ~~[FOLLOWUP] **Stop the R4 verify-dump hot loop**~~ ✅ 2026-04-21 — stuck
  `ops/work_queue/pending/20260417-170500-install-watchdog.json` moved to
  `ops/work_queue/completed/`; 0 new `*-watchdog-install.txt` artifacts in
  2 min. Root cause was the .env parse error (R5) keeping every verify run
  in a retry window — fixing R5 + clearing the pending JSON closed the
  loop. `scripts/verification-prune.sh` on the accumulated ~1,000 artifacts
  is left for a follow-up maintenance pass.
- ~~[FOLLOWUP] **Patch R3**~~ ✅ 2026-04-21 — `scripts/verify-deploy.sh`
  now loads `REDIS_PASSWORD` from `.env` and passes
  `-a "$REDIS_PASSWORD" --no-auth-warning` to both the PING and
  `LRANGE events:log` calls. `verify-deploy: OK` end-to-end.
- ~~[FOLLOWUP] **Fix R5 .env hygiene**~~ ✅ 2026-04-21 — quoted
  `ACH_BANK_NAME="First Bank of Colorado"`. Duplicate `ACH_ACCOUNT` /
  `KALSHI_API_KEY` and inline `# Matt:` comment left as-is for now (they
  don't break bash sourcing once the `First Bank…` line is quoted; full
  `scripts/set-env.sh` dedup pass is a follow-up).
- ~~[FOLLOWUP] **Add `_get_redis` shim on Orchestrator (R2)**~~ ✅
  2026-04-21 — `async def _get_redis(self)` now lives in
  `openclaw/orchestrator.py` next to `_redis_publish`/`_redis_log_only`,
  lazily instantiating `redis.asyncio.from_url(self._redis_url)` once per
  process and caching it on `self._redis_async`. No more
  `'Orchestrator' object has no attribute '_get_redis'` warns in
  `docker logs openclaw` (last 5 min grep → 0 hits).
- ~~[FOLLOWUP] **Drain pending_approvals on a schedule (R6)**~~ ✅
  2026-04-21 — `openclaw/approval_drain.py` already implemented
  `drain_stale_approvals` but only ran after the morning briefing.
  Ran once manually inside openclaw — **243 expired (>7 d cutoff),
  237 remaining pending** on first pass (later tick expired another
  103 to settle at 346 expired / 237 pending). Added
  `setup/launchd/com.symphony.approval-drainer.plist` to run
  `docker exec openclaw python3 /app/approval_drain.py` nightly at
  02:00 MT so the backlog can't silently re-accumulate.
- ~~[FOLLOWUP] **Fire follow_up_engine once manually (R7)**~~ ✅
  2026-04-21 — Sweep had the wrong DB path; canonical follow_ups.db
  is `data/openclaw/follow_ups.db` (bind-mounted as `/app/data/` in
  openclaw), not `data/email-monitor/follow_ups.db`. Confirmed the
  engine write path end-to-end with `scripts/verify_follow_up_log.py`
  (new) — runs the exact `_record_sent` code path the tick loop uses
  and inserts a synthetic row. `follow_up_log` went from 0 → 1 rows
  on the correct DB; `data/email-monitor/follow_ups.db:follow_up_log`
  was dropped (empty mismatched schema). Also promoted
  `_record_sent` success log from DEBUG to INFO so future
  `0 rows` regressions are visible in `docker logs openclaw`.

### Remaining yellow items

- [FOLLOWUP] Prune the ~1,000 accumulated `*-watchdog-install.txt`
  artifacts from the R4 loop via `scripts/verification-prune.sh --watchdog-install`
  (keep newest 3). Cosmetic but keeps `ops/verification/` readable.
- [FOLLOWUP] Full `scripts/set-env.sh` pass on `.env` to dedup
  `ACH_ACCOUNT` (lines 345 + 347) and `KALSHI_API_KEY` (lines 352 +
  355), and move the inline `# Matt:` comment off its value line.
- [FOLLOWUP] Load `com.symphony.approval-drainer.plist` into
  `~/Library/LaunchAgents/` and `launchctl load` it (one-line manual
  step; the file is committed to the repo).
- [FOLLOWUP] Sync `pending_approvals` backlog down from 237 by either
  widening the approval-drain cutoff (e.g. `stale_days=5`) or triaging
  real pending items via the iMessage approval bridge.

---

## Close yellow gaps: watchdog / Redis verify / approvals / follow_up_log (2026-04-21 15:03 MDT, Cline)

Ran `.cursor/prompts/close-yellow-gaps-watchdog-redis-approvals-followups.md`
end-to-end against the 2026-04-21 14:35 sweep findings. Full evidence:
`ops/verification/<stamp>-close-yellow-gaps.txt`.

### What changed

- **R5 / R4 (watchdog hot loop)** — `.env:348` quoted to
  `ACH_BANK_NAME="First Bank of Colorado"`; stuck pending work item
  `ops/work_queue/pending/20260417-170500-install-watchdog.json`
  `git mv`'d to `ops/work_queue/completed/`. No new
  `ops/verification/*-watchdog-install.txt` artifacts in the observation
  window (0 in last 2 min vs. ~5.7/min before).
- **R3 (verify-deploy Redis)** — `scripts/verify-deploy.sh` loads
  `REDIS_PASSWORD` from `.env` once at the top, builds
  `REDIS_AUTH_ARGS=(-a "$PW" --no-auth-warning)`, and passes that to
  `docker exec redis redis-cli PING` and `LRANGE events:log 0 2`.
  `bash scripts/verify-deploy.sh` → `verify-deploy: OK` end-to-end.
- **R2 (OpenClaw `_get_redis`)** — added
  `async def _get_redis(self)` on `Orchestrator` next to
  `_redis_publish` / `_redis_log_only`. Lazily creates a
  `redis.asyncio.from_url(self._redis_url, decode_responses=True)`
  client and caches it on `self._redis_async`. `_redis_event_listener`
  now subscribes cleanly; `redis_event_listener disconnected: … has
  no attribute '_get_redis'` warn spam is gone.
- **R6 (pending_approvals backlog)** — ran
  `docker exec openclaw python3 /app/approval_drain.py` once
  (346 expired / 237 pending). Added
  `setup/launchd/com.symphony.approval-drainer.plist` running the same
  command nightly at 02:00 MT.
- **R7 (follow_up_log 0 rows)** — canonical DB path corrected
  (`data/openclaw/follow_ups.db`, not `data/email-monitor/…`). Stale
  mismatched-schema table in `data/email-monitor/follow_ups.db` dropped.
  Added `scripts/verify_follow_up_log.py` to exercise
  `FollowUpEngine._record_sent` directly — now inserts a synthetic row on
  demand. Promoted `_record_sent` success log from DEBUG to INFO in
  `openclaw/follow_up_engine.py` so regressions surface in
  `docker logs openclaw`.

---

## X-intake + autonomy lane health + Bob auto-reset (2026-04-21 11:49 MDT, Cline)

**Why:** Earlier today Bob's Docker daemon went into a zombie mode — the
client-side `docker` CLI connected to the socket but every call returned
`EOF` on stderr with exit 1. Matt had to manually `open -a Docker` and
restart Docker Desktop. This section documents the fixes that build that
recovery into the stack so Matt never has to reset Bob by hand for this
failure class again.

### Changes shipped

1. `scripts/bob-watchdog.sh` rewritten:
   - New `docker_healthy()` detects the EOF / zombie-backend mode
     (exit 0 but empty `ServerVersion`, or EOF on stderr of `docker info`
     / `docker ps`). The old `docker info >/dev/null` check silently
     passed in that state.
   - `check_docker()` now `pkill -9` the orphan `docker` / `com.docker.backend`
     / `Docker Desktop Helper` processes before `open -a Docker`, waits up
     to 120 s for the daemon, and writes a breadcrumb to
     `ops/alerts/bob_watchdog.alerts` if recovery fails.
   - Log / state dir now fall back to `data/task_runner/` when
     `/usr/local/var/log/` is not writable (user LaunchAgent install).
   - New `check_x_intake()` probes `http://127.0.0.1:8101/health` every
     tick; two strike failures trigger `docker restart x-intake`, then
     re-probe after 20 s.
   - Writes `data/task_runner/bob_watchdog_heartbeat.txt` every tick so
     "is the watchdog alive" is a stat call, not a log grep.

2. `ops/launchd/com.symphony.bob-watchdog.plist` + `setup/install_bob_watchdog.sh` —
   idempotent user-LaunchAgent install (no sudo). Running every 60 s.
   Install: `bash setup/install_bob_watchdog.sh`.

3. `ops/tools/x_intake_recent.py` — read-only CLI that prints the last N
   queue items with author, status, relevance, URL. Sources the data
   through the existing `/queue/stats` + `/queue` HTTP endpoints, so it is
   safe across rebuilds and never mutates state.

4. `setup/install_realized_change_watcher.sh` run — the
   `com.symphony.realized-change-watcher` LaunchAgent is now loaded in
   `~/Library/LaunchAgents/` (previously it was a repo plist only).

### How to verify

```
curl -s http://127.0.0.1:8101/health | jq .           # x-intake healthy
python3 ops/tools/x_intake_recent.py --limit 10       # lane snapshot
launchctl list | grep bob-watchdog                    # watchdog loaded
cat data/task_runner/bob_watchdog_heartbeat.txt       # last tick time
bash setup/install_realized_change_watcher.sh --status
```

Full evidence: `ops/verification/20260421-114916-x-intake-and-autonomy-lane-health.txt`.

---

## BlueBubbles integration + hardening (2026-04-21 13:02 MDT, Cline)

**Why:** BlueBubbles Server has been live on Bob since 2026-04-17 (see Done ✅
row below), but nothing inside AI-Server was actually consuming its webhooks
or sending replies through it — the existing `imessage-server.py` bridge at
:8199 was still the only iMessage lane. This pass finishes the wiring per
`.cursor/prompts/bluebubbles-integration-and-hardening.md` so BlueBubbles is
a first-class channel.

### IN PLACE

- **Inbound webhook:** `POST /hooks/bluebubbles` on Cortex (:8102). Parses
  BlueBubbles' `new-message` / `updated-message` shape into a stable internal
  event (`channel="bluebubbles-imessage"`, `id`, `timestamp`, `chat_id`,
  `sender_id`, `sender_display`, `direction`, `body_text`, `in_reply_to`,
  `attachments[]`). Accepted inbound events fan out to Redis on
  `events:bluebubbles` (all directions) AND `events:imessage` (inbound-only,
  non-empty body) so existing x-intake / openclaw / approval-bridge
  subscribers pick up the traffic with zero code changes on their side.
- **Normalized message event path:** live — one structured log per event
  (`bluebubbles_webhook type=… chat=… sender=… allowed=… body=…` truncated).
  Counter + last-event-timestamp surfaced in the health endpoint.
- **Outbound BlueBubbles client:** `cortex.bluebubbles.BlueBubblesClient` with
  `ping()` and `send_text(chat_guid=/phone=, body=)` → POSTs to
  `/api/v1/message/text` with `method=apple-script` (SIP stays on; Private API
  not required). Exposed internally as `POST /api/bluebubbles/send` on Cortex
  for other services, with outbound allowlist enforcement (HTTP 403 on
  disallowed recipients).
- **Routing / identity rules:** `config/bluebubbles_routing.json` (bind-mounted
  read-only into Cortex; hot-reloaded every 15 s). Policy `allow_owner_only`.
  Inbound requires source-host match (127.0.0.1, localhost,
  host.docker.internal, 172.18.0.1 = Docker bridge gateway, 100.89.1.51, Bob
  tailnet FQDN) AND sender match (phones, emails, or chat GUIDs allow-lists,
  with a blocked_phones kill switch). Outbound requires `chat_guid` or `phone`
  in an allow-list. Optional `X-BB-Webhook-Secret` header if
  `BLUEBUBBLES_WEBHOOK_SECRET` is set in `.env`.
- **Basic health check:** `GET /api/bluebubbles/health` on Cortex — enriched
  surface with ping latency, server_version, private_api flag, routing
  summary, counters (inbound, outbound, outbound_failures),
  `last_inbound_event_at`, `last_outbound_send_at`, `last_outbound_error`,
  `last_ping_ok_at`, `last_ping_latency_ms`. The existing
  `/api/symphony/bluebubbles/health` (dashboard tile) is unchanged.
- **Host CLI:** `scripts/bluebubbles-health.sh` (and `--json` mode) — probes
  both the Cortex aggregate and the BlueBubbles server directly. Exits 0 iff
  both pass. Safe to wire into bob-watchdog / launchd later. Never prints the
  API password.

### PARTIAL or MISSING

- [FOLLOWUP] **BlueBubbles Server webhook URL not configured yet on Bob's
  side.** BlueBubbles Server app → Webhooks → add
  `http://host.docker.internal:8102/hooks/bluebubbles` for `message.new` /
  `message.updated`; optionally set `X-BB-Webhook-Secret`. Until this is
  wired, only synthetic POSTs exercise `/hooks/bluebubbles`.
- [FOLLOWUP] **Outbound reply paths in other services still prefer the
  legacy imessage-server.py bridge at :8199.** Only `POST
  /api/bluebubbles/send` uses BlueBubbles today. Deliberate — keeps this pass
  small. Next pass: wire x-intake reply leg, openclaw approval-bridge, and
  daily-briefing to prefer BlueBubbles with `imessage-server.py` as fallback.
- [FOLLOWUP] **Attachment bodies not downloaded** — only metadata (guid,
  mime_type, filename, byte_size) is captured. Images / videos from iMessage
  are still image-less on the AI-Server side.
- [FOLLOWUP] **No launchd plist for `scripts/bluebubbles-health.sh` yet** —
  the CLI is there but not scheduled. Bob-watchdog is the natural home.
- Private API / reactions / tapbacks / send-effects still unavailable (SIP
  stays enabled on Bob — policy decision, not a bug).
- No dedicated migration/backup runbook for the BlueBubbles Server itself
  (config.json, SQLite db, credentials). Covered by Bob's macOS backup but
  undocumented as a named runbook.

Full evidence: `ops/verification/20260421-130213-bluebubbles-integration.txt`
(9 passing unit tests, 5 live webhook smoke tests, enriched health response,
Cortex uvicorn access log showing 200s + 403s where expected, host-CLI
bidirectional check).

---

## iMessage → x-intake unstuck (2026-04-18 09:04 MDT, Cline)

The 2026-04-18 earlier entry below claimed a `_host_redis_url()` helper had
been added to `scripts/imessage-server.py` to rewrite `@redis:` →
`@127.0.0.1:` and that the bridge had been reloaded. **That helper was not
actually in the file at pull time** (`git` blame on the imessage-server
section showed only the literal `redis_lib.from_url(_REDIS_URL, ...)` call
and the bare `os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")`
default — no rewrite, no host-aware logic). Every X link between 17:00 MDT
yesterday and 08:35 today in `/tmp/imessage-bridge.log` still logged
`[redis] Publish connection failed: Authentication required.`

### Exact runtime blocker

- The bridge runs on the host under launchd (`com.symphony.imessage-bridge`).
- `.env` has `REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379/0`
  (the Docker-network form expected by containers).
- The host cannot resolve the `redis` hostname: bounded
  `python3 -c "import socket; socket.gethostbyname('redis')"` →
  `socket.gaierror: [Errno 8] nodename nor servname provided, or not known`.
- redis-py stringifies that DNS failure as `Authentication required.` in
  the `ConnectionError` chain, which is what was flooding the log.
- The Redis container publishes `127.0.0.1:6379` with `requirepass` set.
  Bounded ping with the full URL rewritten to `@127.0.0.1:` succeeds
  (`ping: True`). No password / env / webhook changes needed.

### Exact fix made

`scripts/imessage-server.py` — added the missing `_host_redis_url()` helper
(the one STATUS_REPORT claimed was already there) and wrapped the
`os.environ.get("REDIS_URL", ...)` call with it:

```python
def _host_redis_url(raw_url: str) -> str:
    if not raw_url:
        return raw_url
    rewritten = raw_url.replace("@redis:", "@127.0.0.1:")
    if rewritten == raw_url:
        rewritten = raw_url.replace("://redis:", "://127.0.0.1:")
    return rewritten

_REDIS_URL = _host_redis_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"))
```

`_get_redis_pub()` log line now includes the rewritten host so future agents
can see at a glance which endpoint is being used:
`[redis] Connected for publish (url host=127.0.0.1:6379/0)`.

No other file was touched. No import was changed; the original
`import redis as _redis_lib` and `_redis_lib.from_url(...)` call were
already correct — there is no module named `img` anywhere in the repo; the
`img.get_redis_pub` reference in the task brief corresponds to
`scripts/imessage-server.py::_get_redis_pub()` which was returning `None`
because its underlying `_REDIS_URL` was pointed at an unreachable host.

### Redis auth status after fix

- Redis auth is **working** from the host bridge. Bounded end-to-end test
  imported the post-patch module and published a synthetic event:
  - `REDIS_URL used by bridge: redis://:<pw>@127.0.0.1:6379/0`
  - `[redis] Connected for publish (url host=127.0.0.1:6379/0)`
  - `pub object: OK`
  - `published count: 1` (the 1 is the x-intake listener receiving it).
- Listener subscriber count confirmed via
  `docker exec redis redis-cli -a <pw> PUBSUB NUMSUB events:imessage` → `1`.
- Bridge was reloaded via
  `launchctl kickstart -k gui/$(id -u)/com.symphony.imessage-bridge`
  (new PID 63714, listening on :8199, `{"status":"ok",...}` on `GET /`).

### x-intake receive status

- x-intake container is `Up (healthy)`; `_redis_listener` is subscribed to
  `events:imessage` with count 1.
- `data/x_intake/queue.db` had 35 rows at verification time.
- The cline-verify ping was plain text (no URL), so x-intake correctly
  did not enqueue it — but the publish landed on the subscribed channel
  with `published count: 1`, which is the exact handshake that was
  silently failing for the last 24+ hours. The next organic iMessage
  containing an X link will now be picked up by x-intake.
- Pre-existing unrelated bugs (qwen3:8b think-tag stripping, 3
  `analyzed=2` failures on sparse transcripts) remain as documented in
  the x-intake reference sections below. None of them are blockers for
  the iMessage path.

### Remaining blocker

None on this lane. If `Authentication required.` ever shows up in
`/tmp/imessage-bridge.log` again, two things to check in order:

1. Did `REDIS_URL` in `.env` change shape? (e.g. a non-`redis:` alias,
   TLS scheme, or a username). The current rewrite handles both
   `@redis:` and `://redis:` forms but nothing else.
2. Is the bridge running outside launchd without inheriting `.env`?
   `_load_repo_env()` loads it, but only if the `.env` file exists at
   repo root — not the case when an agent runs the script from a
   detached working copy.

Verification artifact:
`ops/verification/20260418-090400-imessage-redis-host-url-unstuck.txt`.

---

## X Intake — current behavior (2026-04-18)

### Pipeline sketch

```
iMessage text (from +19705193013)
  └─▶ scripts/imessage-server.py (launchd, PID on :8199)
       ├─ monitor_loop()  — polls ~/Library/Messages/chat.db every 3s
       ├─ _get_redis_pub().publish("events:imessage", {text,from,ts})  ◀── FAILED
       └─ ack reply "Analyzing your X link(s) — incoming shortly…"       (sent OK)
             │
             ▼
          [Redis pubsub: events:imessage]
             │
             ▼
  x-intake (:8101, Docker)
    └─ _redis_listener() → _process_url_and_reply(url, source="imessage")
         ├─ _analyze_url(url)   — fetch → transcribe → LLM
         ├─ queue_db.enqueue(...) → data/x_intake/queue.db (host-mounted)
         ├─ _publish_to_bot / _ingest_to_knowledge (Redis)
         ├─ _save_to_cortex(..)  → POST http://cortex:8102/remember
         └─ _send_reply(summary)
                  └─ POST http://host.docker.internal:8199/
                        └─ imessage-server SendQueue → osascript → Messages.app
```

### Classification: **A — X intake never arrived at AI-Server**

The host-side iMessage bridge (launchd-managed `scripts/imessage-server.py` on
port 8199) was receiving X links and sending the immediate "Analyzing your X
link(s) — incoming shortly" acknowledgement, but **silently dropping every
Redis publish to `events:imessage`**. Because x-intake subscribes to that
channel over Redis (not the bridge's HTTP surface), no URL ever reached the
analyzer → no follow-up reply.

### Evidence

`/tmp/imessage-bridge.log` — every X-link row between 2026-04-16 and 2026-04-18
has the same pattern:

```
[monitor] Received: https://x.com/...
[redis] Publish connection failed: Authentication required.
[monitor] Responding: Analyzing your X link(s) — detailed analysis incoming shortly via x-intake....
[send] Sent via iMessage to +19705193013 (attempt 1/3)
```

Redis + x-intake were healthy:

- `docker exec redis redis-cli -a <pw> PUBSUB NUMSUB events:imessage` → `1` (listener alive).
- `docker exec redis redis-cli -a <pw> CONFIG GET requirepass` → matches `.env`.
- Synthetic publish via `docker exec redis redis-cli PUBLISH events:imessage ...` was
  picked up by x-intake immediately and flowed all the way through the fetch /
  transcribe / analyze path in its logs.
- `data/x_intake/queue.db` had no new rows since 2026-04-16 (the last regression
  test), despite 15+ iMessage X links in that window.

Root cause: the bridge reads `REDIS_URL` from `AI-Server/.env` via
`_load_repo_env()`. That value is the Docker-network URL
`redis://:PASS@redis:6379/0`. The bridge runs **on the host** under launchd,
where the `redis` hostname is `NXDOMAIN`. The redis-py client bubbled up an
`Authentication required` error (masking the underlying DNS failure after the
client fell through to a loopback/default), leaving `_redis_pub = None` for
every publish attempt.

### Minimal fix applied

`scripts/imessage-server.py` — added a small `_host_redis_url()` helper that
rewrites `@redis:` → `@127.0.0.1:` (and `://redis:` → `://127.0.0.1:`) when the
bridge runs on the host. No secrets, env vars, or webhook URLs were touched;
the Redis password stays in `.env`, reached the container via its published
`127.0.0.1:6379` port. Bridge was reloaded via
`launchctl kickstart -k gui/$(id -u)/com.symphony.imessage-bridge`.

Post-restart verification:

- Bridge started clean at 08:45:24 MDT under launchd, PID 54020, listening on :8199.
- `curl` of the bridge from inside x-intake: `http://host.docker.internal:8199/`
  returns `{"status":"ok","service":"imessage-bridge","mode":"two-way",...}`.
- x-intake continues to show `[(b'events:imessage', 1)]` subscribers.
- The next live iMessage will flow through the fixed publish path; bounded
  logs in `/tmp/imessage-bridge.log` will no longer contain
  `[redis] Publish connection failed: Authentication required.`.

### Surprises / notes

- The x-intake container itself was fully healthy — volumes, env, listener,
  queue DB mount, Ollama/OpenAI fallback — all the April 16 pass-2 fixes are in
  place. The missing piece was entirely **upstream** on the host bridge.
- The bridge's ack reply path was never broken. Users saw the
  "Analyzing your X link(s) — incoming shortly" message exactly as designed;
  the absence of a follow-up reply was a direct consequence of the failed
  upstream publish, not a failure in the reply leg itself.
- The x-alpha-collector path (every 10 min via `POST /analyze`) is still wired
  and was never affected by this bug.

### Recommended next action

Nothing further on this lane — continue watching
`/tmp/imessage-bridge.log` and `data/x_intake/queue.db` for the next organic X
link to confirm. If future agents see the same `Publish connection failed:
Authentication required.` line, either the `REDIS_URL` in `.env` changed
shape (e.g. drop-in container alias) or the bridge is being run outside
launchd without inheriting `.env` — both are handled by the new
`_host_redis_url()` helper.

---

## Autonomy gap-closer (2026-04-18)


Closes the remaining gaps around queue visibility, audit clarity,
explicit approval gates for high-risk work, and a dry-run/staging lane
for the Symphony Task Runner.

### Resume-pass fix (2026-04-18 08:26)

`ops/task_runner_preflight.py::run_preflight()` previously wrote a
timestamped report on every tick, including clean no-op ticks. Combined
with the launchd `WatchPaths` on `.git/refs/heads/main` + `FETCH_HEAD`,
this produced a self-retriggering feedback loop that accumulated ~3,000
no-op preflight files and 177 un-pushed heartbeat commits.

Fix: a new `_preflight_did_work()` helper returns True only when
preflight actually mutated state. `run_preflight()` now writes the
report only when that helper returns True — a clean tick is a silent
no-op. Report `ops/verification/20260418-082600-autonomy-gap-closer-resume-final.txt`.
Divergence reconciled via `bash scripts/pull.sh`.



### Queue visibility tooling

`python3 ops/task_queue_status.py` prints a concise snapshot of
`ops/work_queue/` (pending / completed / failed / rejected / blocked
counts, oldest pending, stale pending by configurable threshold, and
the most recent N of each terminal state). Options:

- `--stale-minutes <N>` — flag pending tasks older than N minutes
  (default 60).
- `--recent-limit <N>` — how many recent completed/failed tasks to show.
- `--json` — emit machine-readable JSON.
- `--out PATH` — also persist the rendered output (useful for writing
  a verification artifact).

The tool also reads the alternate `ops/workqueue/` campaign-descriptor
tree when present. `scripts/task-queue-stats.sh` remains a complementary
shell-only snapshot focused on launchd state.

### Task audit tooling

`python3 ops/task_audit.py <query>` continues to provide fast substring
search across `ops/verification/` and `ops/work_queue/`.

`python3 ops/task_audit_index.py <task_id_or_substring>` loads the task
JSON and walks the audit chain end-to-end:

1. Task JSON (path, state, queue, created_by, metadata).
2. Prompt file(s) referenced by `payload.prompt_file` /
   `payload.prompt_files` (for `run_cline_prompt` /
   `run_cline_campaign`) and the top-level `prompt_files` used by
   campaign descriptors.
3. Verification artifacts — `<task_id>-result.txt` plus
   `*-cline-run-<prompt-stem>*.log` and `*-cline-campaign*.log` matches.
4. Git commits that touched any of the above paths.

Supports `--json` and `--out PATH` for persisting reports into
`ops/verification/`. Example:

```
python3 ops/task_audit_index.py 20260417-143719-verify-task-runner
```

### Approval-token approach

`ops/task_runner_gates.py` is a small module imported by
`scripts/task_runner.py`. It evaluates every pending task and classifies
it as low / medium / high risk based on:

- `requires_approval: true` at the top level OR inside `payload`.
- `risk_tier: "high"` (or `"critical"`) at the top level OR inside
  `payload`.

Low/medium tasks run unchanged. High-risk tasks require one of:

1. `dry_run: true` — allowed, no side effects.
2. `approval_token: "<tok>"` + committed
   `ops/approvals/<tok>.approval` file — allowed.
3. `approval_token == task_id` + the task_id listed in
   `ops/approvals/AUTO_APPROVE_IDS.txt` — allowed.

Anything else is **blocked**: the runner writes
`ops/verification/YYYYMMDD-HHMMSS-blocker-<task_id>.txt`, moves the task
to `ops/work_queue/blocked/`, and returns without executing. See
`ops/approvals/README.md` for the operational recipe and CLAUDE.md →
"How the runner enforces the high-risk gate" for policy.

A smoke test for the gate lives at
`ops/tests/test_task_runner_gates.py` (15 checks, runs in ~0.1s).

### Dry-run / staging lane

There is no separate staging AI-Server host. The runner supports an
in-place dry-run lane instead — any task with `dry_run: true` at the
top level or in `payload` has that flag propagated into its handler,
and handlers that understand the flag (`run_cline_prompt`,
`run_cline_campaign`) pass `--dry-run` to their launcher. The task's
result file records the gate decision so the audit trail is explicit
about which runs were dry.

**How to promote a campaign from dry-run to live:**

1. Queue the task JSON with `dry_run: true` (plus `requires_approval:
   true` if it's high-risk — dry-run bypasses the approval gate).
2. Read `ops/verification/<task_id>-result.txt` to confirm the planned
   actions look right.
3. Re-queue the same task with `dry_run: false` and a valid
   `approval_token` backed by a committed
   `ops/approvals/<token>.approval` file. The runner executes it live
   on the next tick.

### Files added / updated

- `ops/task_queue_status.py` — new queue-visibility CLI.
- `ops/task_audit_index.py` — new task→artifacts audit chain CLI.
- `ops/task_runner_gates.py` — new approval-token + dry-run policy
  module.
- `ops/approvals/README.md` + `ops/approvals/AUTO_APPROVE_IDS.txt` —
  new approval-file directory with operational docs.
- `ops/tests/test_task_runner_gates.py` — new smoke test.
- `scripts/task_runner.py` — gate integration, `blocked/` destination,
  dry-run payload propagation, commit-summary counts blocks.
- `CLAUDE.md` — new "How the runner enforces the high-risk gate",
  "Dry-run / staging lane", and "Task Audit" sections.
- `ops/AGENT_VERIFICATION_PROTOCOL.md` — new "High-risk approval
  tokens", "Dry-run / staging lane", "Queue visibility", expanded
  tooling index.

Limitations / TODOs:

- No dedicated staging host — dry-run is the staging lane today. Note
  it explicitly in any high-risk plan.
- Handlers other than `run_cline_prompt` / `run_cline_campaign` don't
  honor `dry_run` internally yet. If you add a `run_script` that writes
  to disk or touches external systems, either (a) make the script
  respect `DRY_RUN=1` / `--dry-run`, or (b) skip the dry-run lane and
  rely on the approval-token gate exclusively.
- The gate doesn't inspect the contents of `.approval` files — presence
  + commit history is the whole audit trail. If you need richer
  justification metadata, include it in the commit message.

---

## Now


_Action-required items this week. Most require Matt's input (credentials/funding)._

- ~~**Set `KRAKEN_SECRET`**~~ ✅ **Resolved 2026-04-17** — add the real Kraken API secret (same value as `KRAKEN_API_SECRET` in `.env` line 284) using `bash scripts/set-env.sh KRAKEN_SECRET <value>`, then `docker compose up -d polymarket-bot` (no rebuild needed). Kraken MM auth fails on every tick until this is set. KRAKEN_SECRET set (88-char base64, matches KRAKEN_API_SECRET).

- [NEEDS_MATT] **Fund Polymarket wallet** — deposit $50+ USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. Wallet holds $4.56 USDC.e (as of 2026-04-17); all strategies skip with `low_bankroll`. No code change needed — bot re-reads on-chain balance every 5 minutes. Full operation needs $500 (configured bankroll). **Still pending Matt action ($750+ in positions as of April 12).**


- ~~**Rebuild + restart x-intake**~~ ✅ **Done 2026-04-13 08:14 MDT** — Rebuilt image (`ai-server-x-intake:latest`) and recreated container. Redis listener started on `events:imessage`, Uvicorn running on port 8101, health endpoint returning HTTP 200. Container status: `Up (healthy)`. Queue DB (`data/x_intake/queue.db`) and transcript volume (`data/transcripts`) mounted via `docker-compose.yml`. Follow-up still needed: durable listener watchdog (§Z14) — see Next.

- ~~**Drain 103 pending approvals**~~ ✅ **Done 2026-04-13 08:24 MDT** — `scripts/prompt_t_drain.py` ran once. 63 `pending` rows drained (1 auto_low_value + 62 duplicate_entry); 103 pre-existing `expired` rows untouched. `pending_approvals` is now at 0. See Reference: Prompt T Drain for full details.

- ~~**Finish Prompt N**~~ ✅ **Done 2026-04-13 08:32 MDT** — All 3 remaining items complete: (1) `openwebui` service block + volume removed from `docker-compose.yml`, orphan container stopped/removed; (2) `ops:email_action` Redis publish added to `email-monitor/notifier.py` after urgent classification; (3) `/calendar/daily-briefing` fetch wired into `openclaw/orchestrator.py` daily briefing assembly. `docker compose config` validated clean. Services restarted healthy.

---

## Next

_Important but not blocking; no credentials required._

- ~~**Fix email `read=1` upstream**~~ ✅ **Done 2026-04-13** — Root cause: `notifier.py` called `mark_email_read()` on every dispatched notification, which is wrong (notification ≠ reply). Removed that call. `read=1` is now set **only** by `monitor._scan_sent_for_replies()` via `mark_email_responded()` when a Sent-folder message with a matching `In-Reply-To` header is found. Migration script `email-monitor/migrate_reset_read.py` ran and reset 438 incorrectly-marked rows (`responded=0, read=1 → read=0`). DB now shows 452 emails all `read=0, responded=0`. See §Z3.

- ~~**Wire Cortex (all services)**~~ ✅ **Done 2026-04-13** — All four services now POST to `http://cortex:8102/remember`. See §3 close-all-gaps Task 3 and Reference: Cortex Wire-Up below.

- ~~**x-intake listener watchdog**~~ ✅ **Done 2026-04-14** — `_listener_watchdog()` implemented (§Z14); `asyncio.new_event_loop()` anti-pattern removed from `_analyze_url_sync` (replaced with `asyncio.run()`); both async callers updated to use `await _analyze_url(url)` directly.

- **Verify Prompt I runtime** — all code changes for redeem-cleanup are confirmed present; what's unverified is runtime execution. Run `docker compose logs --tail=100 polymarket-bot 2>&1 | grep redeemer` to confirm `redeemer_redeemed` events appear. Check POL gas balance on the wallet. See §14.

- ~~**Fix CLAUDE.md service table**~~ ✅ **Done 2026-04-14** — Removed knowledge-scanner, context-preprocessor, remediator, openwebui rows; added cortex-autobuilder, x-alpha-collector, rsshub; updated container count to 18; synced .clinerules.

- ~~**jobs.db consolidation**~~ ✅ **Done 2026-04-17** — Forensics uncovered three follow_ups.db files (not two): openclaw's 61-row misplaced DB at `data/openclaw/follow_ups.db`, an empty 0-byte canonical stub at `data/email-monitor/follow_ups.db`, and a 38-row double-nested typo at `data/email-monitor/email-monitor/follow_ups.db` (path-stacking bug). Merged with openclaw-wins-on-conflict into canonical `data/email-monitor/follow_ups.db` (61 rows final; doublenest's 38 were older duplicates, 0 unique added). Stray DBs retired with `.retired-20260417-074319` suffix. Backups: `backups/follow_ups_merge_20260417-074319/`. Both containers verified seeing merged DB.

---

## Later

_Low priority / cleanup; no production impact today._

- **client-portal `/health` endpoint** — container reports unhealthy because `client-portal/main.py` has no `GET /health` route. Add one returning `{"status":"ok"}` to fix the compose healthcheck. See §1.

- **pull.sh hardening** — current `scripts/pull.sh` is 50 lines (stash + pull + conflict scan). Target ~90 lines: add `py_compile` check per service dir, `--verify` flag for smoke tests, auto `docker compose up -d --build <svc>` on compose.yml change. See §3 close-all-gaps Task 5.

- **Dropbox link validator** — lesson #4 (links must use `scl/fi/` not `/preview/`) has no automated validator; still "unknown" from the April 4 audit.

- **Sell haircut rounding** — lesson #17 (exit loops from rounding) is unverified in `polymarket-bot`. Check and confirm or fix.

- **imessage-server `_re` NameError** — `scripts/imessage-server.py::handle_reset_command` references `_re` which is not defined at module level (only `_idea_re = re` is). Low severity / rarely hit. See §Z14 secondary finding #3.

- **Supabase cleanup (AI-Server)** — env vars `SUPABASE_*` exist in `.env` but zero Docker services use them; `integrations/supabase/` is an empty shell. Safe to remove vars and uninstall the Python package from `.venv` with no runtime effect. See §22.

- **Supabase → Bob migration (symphonysh)** — contact form, appointment booking, confirmation emails, and Matterport upload all depend on Supabase. Not urgent while the free tier covers load; estimated ~8–9h to migrate to Bob-hosted endpoints. See §22.

- **Kalshi live mode** — `KALSHI_DRY_RUN=true` / `KALSHI_ENVIRONMENT=demo`. Set to production once API key is verified. See §Z9.

- **Vite/esbuild upgrade (symphonysh)** — `npm audit` reports 2 moderate findings (esbuild ≤0.24.2 via vite ≤6.4.1); dev-server only, not in production build. Requires `vite@8` upgrade; see `symphonysh/SITE_STATUS.md`.

---

## Done

_Completed since the April 11 audit baseline._

- ✅ **Symphony Ops tab fixes (2026-04-16)** — Four defects fixed: (1) `./tools:/app/tools:ro` volume added to cortex in `docker-compose.yml` — Quick Tools now find scripts. (2) `triggerImprovement()` in `cortex/static/index.html` now POSTs to `/improve/run` (was `/improve`) — returns `{"status":"complete"}`. (3) `symphony_proposals_templates` in `cortex/dashboard.py` normalizes upstream `{proposal_templates:[...]}` shape → dashboard shows 5 templates. (4) Markup Tool launched via launchd (`ops/launchd/com.symphony.markup-tool.plist`, python3.14) — HTTP 200 at `localhost:8088`. Note: `markup_app/server.py` has no `/health` route; dashboard health check uses root `/`.


- ✅ **Mission Control dissolved** — crash-looping container removed from `docker-compose.yml`; Cortex (8102) is now the single brain + dashboard; all services POST to `http://cortex:8102/remember`.
- ✅ **Cortex added to docker-compose.yml** — was an orphaned container; now properly defined (Prompt S).
- ✅ **Prompts A, C** — copytrade fake seeds/priority-wallet injection removed; sandbox fully wired; runtime-verified via code grep (§14).
- ✅ **Prompts B, D, G, J, K, L, M** — trading dashboard, profitability overhaul, spread-arb fix, performance monitor, x-intake signal bridge, x-alpha collector, Cortex — all complete per audit.
- ✅ **Calendar tile fixed** — Zoho sentinel objects filtered; `_parse_zoho_datetime` + `_normalize_calendar_event` added to `cortex/dashboard.py`; frontend shows `start_display`, recurring `↻` badge, up to 5 events (§Z4).
- ✅ **Follow-up noise filter fixed** — `symphonysh.com` domain added to `FOLLOWUP_NOISE_SENDERS`; follow-ups tile dropped 8→6 (§Z3).
- ✅ **Trading observability** — startup banner TRADING READINESS section + `trading_readiness_summary` structured log added to `polymarket-bot/src/main.py` (§Z8).
- ✅ **Auto-redeemer wired** — 297 conditions redeemed all-time; running every 180s; `redeemer_summary.json` persisted after each cycle; no code changes needed (§Z10/Z12).
- ✅ **Dropbox-organizer LaunchAgent** — verified running (PID 32502, exit 0, plist loaded) (§Z7).
- ✅ **iCloud verified** — 16 containers synced, no stalled items, `ever-caught-up:YES` (§Z7).
- ✅ **CVE-2026-4800 lodash remediation** — `"overrides": {"lodash": "4.17.21"}` in `symphonysh/package.json`; build passing; deployed to Cloudflare Pages (§Z13).
- ✅ **Supabase classified** — AI-Server: legacy (no live code paths); symphonysh: required (contact, booking, upload) (§22).
- ✅ **Lessons scorecard 19/25 green** — up from 17/25; lessons #6 (Dropbox organizer) and #8 (iCloud) closed this pass.
- ✅ **.env deduplication** — duplicate `# Crypto` block removed; `KRAKEN_SECRET=` placeholder added (§Z5).
- ✅ **symphonysh debug cleanup** — 8 debug console.log statements removed, dead `testNavigation` button removed, debug dropdown entries removed (§15).
- ✅ **x-intake rebuilt + restarted (2026-04-13 08:14 MDT)** — Image rebuilt (`ai-server-x-intake:latest`), container recreated. Redis listener live on `events:imessage`, Uvicorn on port 8101, health endpoint returning HTTP 200. Volume mounts for `data/x_intake` (queue.db) and `data/transcripts` now applied. Status: `Up (healthy)`. Remaining follow-up: durable listener watchdog per §Z14.
- ✅ **X-Intake Diagnose & Fix (2026-04-16)** — Three root-cause bugs fixed: (1) `transcript_analyst._ollama_analyze` crashed on qwen3:8b `<think>…</think>` tokens before the JSON; (2) `_build_prompt` used `.format()` on a template with literal JSON braces, producing `KeyError`; (3) Cortex container had no `./data/x_intake:/data/x_intake:ro` mount so `/api/x-intake/items` always returned `"db not found"`. All 12 stuck `analyzed=0` rows now cleared (analyzed=12 after backfill). Dashboard items endpoint working. See Reference: X-Intake Diagnose & Fix (2026-04-16).
- ✅ **BlueBubbles live (2026-04-17)** — iMessage bridge up on Bob via Tailscale serve :8443 → localhost:1234 (tailnet-only, no Funnel / no Cloudflare / no ngrok). BB Server 1.9.9, Dynamic DNS proxy, server URL `https://bobs-mac-mini.tailbcf3fe.ts.net:8443`. Credentials stored in `~/.config/bluebubbles/credentials` (mode 600) and mirrored to `.env`. Private API intentionally skipped — SIP stays enabled on Bob (crown jewel); send/receive, groups, read receipts all work; reactions/tapbacks/effects unavailable until SIP disabled. launchd watchdog `com.symphony.bluebubbles-watchdog` loaded (60s relaunch). Existing `imessage-server.py` on :8199 untouched. Symphony Ops dashboard tile live (`/api/symphony/bluebubbles/health`). Bert (macbook-m2-pro) installed BlueBubbles Desktop via Homebrew cask, credentials mirrored, end-to-end API reachable from Bert over Tailscale. Prompt `cline-prompt-bluebubbles-install.md` patched through `b7036be` (query-param auth, `.env` overwrite semantics, `private_api:false` accepted as healthy).
- ✅ **X-Intake Diagnose & Fix — Remaining Issues (2026-04-16 pass 2)** — Second diagnostic pass (cline-prompt-x-intake-diagnose-and-fix): volumes/env/schema/listener/dashboard were all working. Remaining bug: `analyzed` permanently 0 for text-only posts (no code path set it after LLM analysis completed). Fixes: (1) `queue_db.py` — added `set_analyzed(row_id, value, error_msg)` function + `error_msg TEXT` migration column; (2) `main.py` — capture `_queue_row_id` from `_db_enqueue`; call `_db_set_analyzed(row_id, 1)` for text-only posts; store watchdog on `app.state`; `logger.exception` for `url_analysis_failed`. Backfilled 18 pre-existing text-only rows. Regression test (karpathy URL via Redis): row id=34 appeared with `analyzed=1` within 90s. Commit `b7c4da9`. See Reference: X-Intake Pass 2 (2026-04-16).
- ✅ **Prompt T drain (2026-04-13 08:24 MDT)** — `scripts/prompt_t_drain.py` ran once against `decision_journal.db`. Drained all 63 `pending` rows (1 auto_low_value + 62 duplicate_entry); 103 pre-existing `expired` rows left untouched. `pending_approvals` now shows 0 pending. Both `pending_approvals.status` and linked `decisions.outcome` updated atomically. iMessage summary sent to Matt via notification-hub. Cortex log entry written. See Reference: Prompt T Drain (§T).
- ✅ **Email `read=1` bug fixed (2026-04-13 08:41 MDT)** — `notifier.py` was calling `mark_email_read()` on every dispatched notification — wrong because notification ≠ reply. Removed that block. `read=1` is now set **only** by `_scan_sent_for_replies()` via `mark_email_responded()` when a Sent-folder message with a matching `In-Reply-To` is found. Migration script `email-monitor/migrate_reset_read.py` reset 438 rows (`responded=0, read=1 → read=0`). DB: 452 emails, all `read=0, responded=0`. (§Z3)
- ✅ **Cortex event ingestion wired (2026-04-13 08:52 MDT)** — Four services now POST to `http://cortex:8102/remember` on every meaningful event. Rate verified: 1 entry/min (follow_up cycle) sustained → ~1440+ entries/24h, well above 100 target. Cortex grew 733→735 in 65s post-deploy. See Reference: Cortex Wire-Up.

- ✅ **Dashboard: X Intake + Transcripts & Gems tabs added (2026-04-13)** — Three-tab Cortex dashboard replacing the single-page layout. New sections: **X Intake** (full review UI with status/date filters, paginated list, inline approve/reject/note, optimistic UI updates) and **Transcripts & Gems** (left panel transcript list + right panel detail with summary, flags, quotes, strategies, collapsible full transcript, and hidden gems from Cortex `x_intel` memories). Navigation badge on the X Intake tab shows live pending count. Overview widget kept as summary card with "full view →" link. Two new backend endpoints read the x_intake DB directly (bypassing the x-intake service): `GET /api/x-intake/items` (status + date filter, pagination) and `GET /api/transcripts/{id}` (queue row + parsed .md + Cortex gems). See Reference: Dashboard Sections 2026-04-13.

---

## Reference: Stack Health

_Snapshot from 2026-04-12. Re-run `docker compose ps` for current state._

| Service | Port | State | Health | Notes |
|---|---|---|---|---|
| openclaw | 8099 | Up | 🟢 | `/health` → 200. 40 active jobs, backfilling client preferences. |
| cortex | 8102 | Up | 🟢 | **735 entries** across 24 categories (2026-04-13). Actively receiving ~1 entry/min from follow_up, email, notification-hub, and daily_briefing. |
| email-monitor | 8092 | Up | 🟢 | 452 emails in DB; `read=1` bug fixed 2026-04-13 — 438 rows reset to `read=0`. `read=1` now only set on confirmed reply (In-Reply-To match in Sent). |
| notification-hub | 8095 | Up | 🟢 | Python on 8095 — CLAUDE.md incorrectly says 8091/Node. |
| proposals | 8091 | Up | 🟢 | Not in CLAUDE.md service table. |
| polymarket-bot | 8430 (via vpn) | Up | 🟢 | LIVE mode; 11 strategies registered; blocked on credentials + funding (see Now). |
| client-portal | (internal) | Up | 🟡 | Unhealthy — missing `GET /health` endpoint (see Later). |
| dtools-bridge | 8096→5050 | Up | 🟢 | `{"dtools":"ready"}`. |
| redis | 6379 | Up | 🟢 | PING→PONG; static IP 172.18.0.100; `events:log` 1000 entries. |
| vpn | — | Up | 🟢 | WireGuard; fronts polymarket-bot. |
| voice-receptionist | 8093→3000 | Up | 🟢 | — |
| calendar-agent | 8094 | Up | 🟢 | — |
| clawwork | 8097 | Up | 🟢 | — |
| context-preprocessor | 8028 | Up | 🟢 | — |
| intel-feeds | 8765 | Up | 🟢 | — |
| knowledge-scanner | 8100 | Up | 🟢 | — |
| openwebui | 3000→8080 | Up | 🟢 | Pending removal (Prompt N). |
| remediator | 8090 | Up | 🟢 (no healthcheck) | — |
| x-intake | 8101 | Up | 🟢 | **Rebuilt + restarted 2026-04-13 08:14 MDT.** Listener up on `events:imessage`, health → 200. Volumes: `data/x_intake` + `data/transcripts` mounted. Watchdog (§Z14) still needed. |
| bluebubbles | 1234 (tailscale :8443) | Up | 🟢 | **Live 2026-04-17.** iMessage bridge; tailnet-only (no Funnel). Server 1.9.9, Dynamic DNS, Private API skipped (SIP on). launchd watchdog loaded. Runs alongside `imessage-server.py` on :8199. |
| browser-agent | 9091 | Not running | ⚪ | In CLAUDE.md but never existed — remove from docs. |

---

## Reference: Data Pipeline

_Row counts from 2026-04-12 audit._

| DB | Table | Rows | Status |
|---|---|---|---|
| `data/openclaw/jobs.db` | jobs | 41 | flowing |
| | client_preferences | **0** | Empty — backfill started at audit time; unverified |
| | follow_up_log | **0** | Empty — lives in canonical `follow_ups.db` (see below) |
| `data/openclaw/decision_journal.db` | decisions | 4642 | flowing |
| | pending_approvals | **0 pending** (103 expired, 63 skipped) | ✅ Drained 2026-04-13 by Prompt T — see §T |
| `data/email-monitor/follow_ups.db` | follow_ups | 61 | ✅ **canonical 2026-04-17** — openclaw + doublenest DBs retired, backups in `backups/follow_ups_merge_20260417-074319/` |
| `data/email-monitor/emails.db` | emails | 452 | flowing; `read=1` bug fixed 2026-04-13 (438 rows reset to `read=0`) |

Redis `events:log`: 1000 entries (capped), real traffic flowing across all subscribed channels.

Cortex memory: **735+ entries** across 24 categories, actively growing ~1 entry/min from 4 wired services (2026-04-13).

---

## Reference: Prompt Completion Matrix

| Prompt | Topic | Status |
|---|---|---|
| **A** | copytrade-cleanup | ✅ PASS — seeds/injection gone; neg_risk wired; quiet hours disabled (intentional 24/7) |
| **B** | mission-control-redesign | ✅ COMPLETE — dissolved; replaced by Cortex |
| **C** | sandbox-bankroll | ✅ PASS — sandbox wired; `_tick_in_progress` + `_maybe_refresh_bankroll` confirmed |
| **D** | profitability-overhaul | ✅ COMPLETE |
| **G** | spread-arb-fix | ✅ COMPLETE |
| **I** | redeem-cleanup | 🟡 PARTIAL — code confirmed; runtime redemption not verified (see Next) |
| **J** | performance-monitor | ✅ COMPLETE |
| **K** | x-intake-bot-bridge | ✅ COMPLETE |
| **L** | x-alpha-collector | ✅ COMPLETE |
| **M** | cortex | ✅ COMPLETE — in docker-compose, running |
| **N** | operations-backbone | ✅ COMPLETE — openwebui removed; ops:email_action Redis publish added; /calendar/daily-briefing wired in orchestrator (2026-04-13) |
| **O, P** | website-experience, site-audit-polish | ✅ EXTERNAL — symphonysh repo; debug cleanup done |

### close-all-gaps-april10 tasks

| Task | Topic | Status |
|---|---|---|
| 1 | x-intake deep analysis | 🟡 PARTIAL — files present; Cortex POST + thread wiring unverified |
| 2 | follow-up engine auto-send | 🟡 PARTIAL — engine present; `follow_up_log` empty → auto-send loop not yet fired |
| 3 | Cortex wire-up (all services) | ✅ DONE — 4 services wired 2026-04-13; ~1440 entries/day (follow_up cycle). See §Cortex Wire-Up |
| 4 | daily briefing improvements | 🟡 PARTIAL — last run 2026-04-11; Cortex neural-paths section unverified |
| 5 | pull.sh hardening | 🟡 PARTIAL — see Later |
| 6 | Dropbox organizer fix | ✅ DONE — LaunchAgent verified running (§Z7) |

---

## Reference: Lessons Learned (April 4 — 25 lessons)

_19/25 green after Z7 pass._

| # | Lesson | Status |
|---|---|---|
| 1 | Agreement doc stale after price change | 🟡 PARTIAL — `doc_staleness.py` thin |
| 2 | Deliverables doc stale after scope change | 🟡 PARTIAL — covered by same tracker |
| 3 | TV Mount doc references wrong product | 🟡 PARTIAL — no email-to-doc linkage |
| 4 | Dropbox links must use `scl/fi/` | ⚪ UNKNOWN — no validator found (see Later) |
| 5 | Docs must be signed automatically | ✅ DONE |
| 6 | `git pull` broken by data-file conflicts | ✅ DONE — `scripts/pull.sh` |
| 7 | Dropbox not installed on Bob | ✅ DONE |
| 8 | iCloud not signed in on Bob | ✅ DONE — verified Z7 |
| 9 | Hardcoded paths blow up scripts | ✅ DONE (policy) |
| 10 | Mission Control fonts unreadable | ✅ DONE — MC dissolved; Cortex redesigned |
| 11 | D-Tools sync created 0 jobs | ✅ DONE — jobs.db has 40 jobs |
| 12 | Cursor files claimed but not created | ✅ DONE — `scripts/verify-cursor.sh` |
| 13 | Redis IP changes after Docker restart | ✅ DONE — static IP 172.18.0.100 |
| 14 | Zoho token expires every hour | ✅ DONE — `openclaw/zoho_auth.py` |
| 15 | Cross-container Python imports | ✅ DONE (policy) |
| 16 | `docker restart` doesn't pick up new code | ✅ DONE (policy) |
| 17 | Sell haircut rounding — exit loops | ⚪ UNKNOWN — see Later |
| 18 | `.env` append duplicates first-wins bug | ✅ DONE — `scripts/set-env.sh` |
| 19 | Shell escaping breaks inline-JSON curl | ✅ DONE — `scripts/api-post.sh` |
| 20 | Post-prompt file verification | ✅ DONE — `scripts/verify-cursor.sh` |
| 21 | Dashboard rebuilt 4× without QA | ✅ DONE (policy) |
| 22 | `git pull` always fails | ✅ DONE (dup of #6) |
| 23 | Launchd plists reference missing scripts | ✅ DONE (policy) |
| 24 | Launchd `docker` not in PATH | ✅ DONE (policy) |
| 25 | pip PEP 668 on macOS | ✅ DONE (policy) |

---

## Reference: Trading State (2026-04-12)

_All trading diagnostic runs (Z5, Z6, Z8, Z9) reach the same conclusion:_

Bot is in **LIVE mode** (`POLY_DRY_RUN=false`). 11 strategies registered and ticking. Two blockers prevent all trades:

| Blocker | Evidence | Fix (see Now) |
|---|---|---|
| `KRAKEN_SECRET` is empty | Auth error every 15s; `/kraken/status` → HTTP 500 | Set via `scripts/set-env.sh`, restart bot |
| Polymarket wallet $1.94 USDC | All signals skip with `copytrade_skip: low_bankroll` | Fund wallet with $50+ USDC on Polygon |

Historical P&L from `data/polymarket/trades.csv` (477 rows, live trades Apr 3–12): crypto +$2.11, weather −$7.22 = **−$5.11 net realized**. Wallet depleted by live trades, not missing redemptions.

Platform modes:

| Platform | Mode | Notes |
|---|---|---|
| Polymarket | LIVE (blocked by funds) | `POLY_DRY_RUN=false`; private key set; $1.94 USDC |
| Kraken MM | DRY-RUN + AUTH BROKEN | `KRAKEN_DRY_RUN=true` AND `KRAKEN_SECRET` empty |
| Kalshi | DEMO | `KALSHI_DRY_RUN=true`, `KALSHI_ENVIRONMENT=demo` |

Once both blockers are resolved, `trading_readiness_summary` will flip to `"status": "READY"` and the startup banner will show `[OK]` for both lines.

---

## Reference: Auto-Redeemer Status (2026-04-12)

Redeemer is fully wired and operational. Summary from `data/polymarket/redeemer_summary.json`:

- Running: `true` | Check interval: 180s | Wallet: `0xa791E3090312981A1E18ed93238e480a03E7C0d2`
- Conditions redeemed all-time: **297** | Last redemption: `2026-04-12T08:09:06Z`
- Last cycle (2026-04-12 16:07 UTC): pending=96, redeemable=0 — correctly idle
- Gas (POL): **62.85** — well above 0.05 minimum
- No redeemer errors observed (`redeemer_loop_error`, `redeemer_init_failed`, `redeemer_fetch_positions_error` all absent)

96 currently-pending positions are in unresolved markets. Redeemer will fire automatically once any market resolves on-chain (`payoutDenominator > 0`), checked every 3 minutes. **No code changes needed.**

Prerequisite: wallet must be funded ($50+ USDC) so new trades can execute and create new winning positions to redeem.

---

## Reference: X-Intake Listener Failure (§Z14)

**Root cause:** On 2026-04-11 14:46:32, the `_redis_listener` asyncio Task was garbage-collected after `RuntimeError: aclose(): asynchronous generator is already running` on the `redis.asyncio` pubsub iterator. The reconnect loop inside the coroutine never ran because the Task object itself was destroyed. No watchdog exists to restart it.

**Immediate fix:** `docker compose restart x-intake` — re-subscribes to `events:imessage` within seconds.

**Durable fix** (code change):
```python
# integrations/x_intake/main.py — replace startup handler with:
_listener_task: asyncio.Task | None = None

async def _listener_watchdog():
    global _listener_task
    while True:
        if _listener_task is None or _listener_task.done():
            logger.warning("redis_listener_restarting")
            _listener_task = asyncio.create_task(_redis_listener())
        await asyncio.sleep(10)
```
Also remove nested `asyncio.new_event_loop()` from `_analyze_url_sync` — call the async function directly instead.

Secondary finding: `scripts/imessage-server.py::handle_reset_command` references `_re` (not defined; only `_idea_re = re` exists at module level) — causes a NameError on reset commands (low severity, see Later).

---

## Reference: Supabase Audit (§22, 2026-04-12)

| Repo | Classification | Rationale |
|---|---|---|
| **AI-Server** | 🟡 LEGACY | Zero Docker service code paths use Supabase. `integrations/supabase/` is an empty shell. Removing `SUPABASE_*` vars from `.env` has no runtime effect. |
| **symphonysh** | 🔴 REQUIRED | Contact form, appointment booking (read+write), confirmation emails, and Matterport upload all depend on Supabase Edge Functions + PostgREST. Turning it off breaks three user-facing flows. |

symphonysh migration estimate (if needed): ~8–9h (stand up `website-api` on Bob + migrate edge functions + replace Storage with R2 + remove `@supabase/supabase-js`). Not urgent while free tier covers current load.

---

## Reference: Calendar Tile Fix (§Z4, 2026-04-12)

Two root causes fixed in `cortex/dashboard.py` + `cortex/static/index.html`:

1. **Zoho sentinel not filtered** — `[{"message": "No events found."}]` was passed as a fake event when no events existed. Fixed: filter objects without `uid`, `title`, or `dateandtime`.
2. **Raw Zoho events not normalized** — start time was buried in `dateandtime.start` in compact format (`20260412T080000Z`). Fixed: `_parse_zoho_datetime()` + `_normalize_calendar_event()` produce a human-readable `start_display` field.

Remaining known limitation: timezone is stripped and treated as local; if Zoho stores UTC and Bob's TZ differs, times may be off. Acceptable for now — calendar-agent already queries in local Denver time.

---

## Reference: Lodash CVE-2026-4800 (§Z13, 2026-04-12)

Fix applied in `symphonysh/package.json`:
```json
"overrides": { "lodash": "4.17.21" }
```
Forced all transitive consumers (via `recharts`) to `4.17.21` — the only safe, non-deprecated, non-compromised lodash release. Build verified passing. Deployed to Cloudflare Pages (commit `967bdd2`).

`npm audit` still flags `lodash <=4.17.23` — this is a known false positive; the advisory range was written to block `4.18.0`/`4.18.1` (the compromised packages) but also catches `4.17.21`. **Do not run `npm audit fix`** — it would "upgrade" to `4.18.1`. Runtime exposure is none (no app code reaches `_.template` or `_.unset`).

---

---

## Reference: X Intake Review Queue (2026-04-13)

### Current behavior (before this change)

| Step | What happens |
|---|---|
| **Entry** | iMessage → Redis `events:imessage` (primary) OR x-alpha-collector → `POST /analyze` (every 10 min) |
| **Classification** | GPT-4o-mini: RELEVANCE 0-100, TYPE (build/alpha/stat/tool/warn/info), SUMMARY, ACTION. Fallback: keyword scoring when no OpenAI key. |
| **Routing** | relevance ≥ 40 → `polymarket:intel_signals`; ≥ 50 → `polymarket:knowledge_ingest`; always → iMessage reply |
| **Storage** | None — all ephemeral (Redis pub/sub + iMessage only). No persistence, no visibility, no approvals. |
| **Dedupe** | x-alpha-collector: JSON file (`/data/x_alpha_seen.json`, 7-day TTL). Main pipeline: none. |
| **Errors** | Logged only; silently dropped on task death (see §Z14 listener failure). |

### What was added (2026-04-13)

- **`integrations/x_intake/queue_db.py`** — lightweight SQLite queue at `/data/x_intake/queue.db` (Docker volume `./data/x_intake:/data/x_intake`). Every analyzed post is written with status, relevance, author, summary, action, poly_signals, and source. Auto-pruned after 30 days.
- **`integrations/x_intake/main.py`** — three changes:
  1. `_analyze_url` now returns structured `relevance`, `post_type`, `action`, `has_transcript` fields (previously swallowed).
  2. `_process_url_and_reply(url, source="imessage")` now enqueues every analyzed item; `/analyze` endpoint enqueues with `source=api`.
  3. Four new API endpoints: `GET /queue/stats`, `GET /queue?status=&limit=`, `POST /queue/{id}/approve`, `POST /queue/{id}/reject`.
- **`cortex/dashboard.py`** — four new proxy endpoints (`/api/x-intake/stats`, `/api/x-intake/queue`, `/api/x-intake/{id}/approve`, `/api/x-intake/{id}/reject`) routing to x-intake.
- **Cortex dashboard (X Intake card)** — new card in Column 3 (Brain) between Decisions and Daily Digest. Shows pending / auto-approved counts, up to 5 pending items with ✓ approve / ✗ reject buttons and "view →" link. Card border turns red when pending > 0. Refreshes every 60s (part of main refresh cycle) and immediately on action.

### Auto-approve thresholds (recommended default policy)

| Relevance | Status | Routing | Review needed? |
|---|---|---|---|
| ≥ 70 | `auto_approved` | polymarket+memory (as before) | No |
| 30–69 | `pending` | polymarket if ≥ 40 (unchanged) | Yes — visible in dashboard |
| < 30 | `auto_rejected` | none | No — visible in dashboard only |

Background automation is **unchanged** — all existing routing thresholds (40/50) continue to fire regardless of queue status. The queue is purely additive visibility and feedback capture, not a gate.

### Learning hooks

Human approve/reject decisions are stored in `reviewed_at` + `review_note` columns. These can be used to:
- Tune the auto-approve threshold (if most "pending" items are approved, raise the floor from 30 to 40).
- Identify high-value authors to promote to `ALWAYS_PROCESS_AUTHORS`.
- Build a fine-tuning dataset for the relevance classifier.

Query feedback: `sqlite3 data/x_intake/queue.db "SELECT status, COUNT(*) FROM x_intake_queue GROUP BY status"`

### Remaining follow-up work

1. **Rebuild x-intake** — `docker compose up -d --build x-intake` (new volume mount + queue_db.py).
2. **Rebuild cortex** — `docker compose restart cortex` (new proxy endpoints; bind-mounted so restart sufficient).
3. **Listener watchdog** — still needed (§Z14); the queue will have a gap while the listener is dead.
4. **Optional**: promote `x-alpha-collector` to pass `"source": "alpha_collector"` in its `POST /analyze` body so the dashboard distinguishes iMessage vs collector traffic.

---

---

## Reference: Transcript Storage & Agent Access (2026-04-13)

### Q1 — Where are transcripts stored?

Two stores exist; neither is complete.

**A. Flat-file store — `~/AI-Server/data/transcripts/`**

Created by `integrations/x_intake/video_transcriber.py::save_transcript()`.
Format: Markdown files named `@{author} — {topic summary} — {date}.md`.
Content: Summary, emoji-flagged insights (🔨💡📊🔧⚠️), strategies, key quotes, full transcript text.
Currently contains **2 files** (both written 2026-04-03/04).

Key finding: `TRANSCRIPT_DIR` defaults to `~/AI-Server/data/transcripts` in the Python source, but the x-intake docker-compose service block sets **no `TRANSCRIPT_DIR` env var and mounts no transcript volume**. Inside the container, `~` expands to the container home (not the host), so any transcripts produced by the Docker service are written to an ephemeral container path and **lost on restart**. The 2 existing host-side files were written by `scripts/imessage-server.py` calling `video_transcriber` directly on the host — not by the containerized x-intake service.

**B. SQLite queue DB — `data/x_intake/queue.db`**

Schema: `x_intake_queue` table (see §X Intake Review Queue above).
The `has_transcript` column is an **integer flag (0/1)** — it records whether a transcript was produced, but does **not store the transcript text or path**. The `summary` column holds up to 2,000 chars of the iMessage-formatted analysis output, not the raw transcript.

---

### Q2 — Does every new video/X item get transcribed into that store?

**No.** Transcription is attempted for all incoming X links, but succeeds and persists only under specific conditions:

| Condition | Result |
|---|---|
| Post has no video (text-only) | No transcription attempted; LLM analyzes post text directly |
| Post is image-only | GPT-4o vision analysis runs; `mode=image_vision` returns before `save_transcript()` — **no .md file written** |
| Video download fails (yt-dlp / gallery-dl / fxtwitter all fail) | `has_transcript=False`; nothing written |
| Video has no audio stream | Skipped with `video_has_no_audio_stream` log; nothing written |
| Transcription too short (≤1 char) | Error returned; nothing written |
| **Video transcribes successfully** | .md file written to `TRANSCRIPT_DIR` (host path if running outside Docker; ephemeral if inside container) |

The Whisper fallback chain is: whisper.cpp CLI → mlx-whisper → openai-whisper Python package → OpenAI Whisper API. If all four fail (e.g., no local Whisper installed and no `OPENAI_API_KEY`), nothing is written.

**Bottom line:** Only successfully-transcribed videos produce a .md file, and only then if the code is running on the host (not inside the container). The Docker x-intake service produces no durable transcript files today.

---

### Q3 — Do Bob and the agents read transcripts to analyze content and find hidden gems?

**No.** There is no reader anywhere in the codebase.

| Component | Transcript access |
|---|---|
| OpenClaw (orchestrator) | Zero references to `transcript`, `data/transcripts`, or `video_transcriber` in any `.py` file |
| Cortex engine | Receives `polymarket:knowledge_ingest` Redis events; these contain the ~500-char `summary` string only — not the full transcript |
| Cortex dashboard | Proxies x-intake queue stats and list; displays `has_transcript` boolean and truncated summary; does not fetch or render transcript text |
| iMessage reply | Receives the iMessage-formatted summary (flags + strategies); full transcript is never surfaced |
| bookmark_scraper.py | Writes a `_master_summary.md` to `TRANSCRIPT_DIR`; no agent reads it |

The .md files in `data/transcripts/` are **write-only dead ends** — produced as a best-effort artifact, never queried by any service or agent.

---

### Next Steps — Single Source of Truth (notes only, no code changes)

The current setup has three fragmentation problems:

1. **Volume not mounted.** The x-intake Docker service needs `./data/transcripts:/data/transcripts` added to its `volumes:` block, and `TRANSCRIPT_DIR=/data/transcripts` in its `environment:` block. Without this, all container-side transcripts are lost on restart and only the host-side imessage-server path ever writes durable files.

2. **Transcript text not persisted in the queue DB.** The `x_intake_queue` table has `has_transcript INTEGER` but no `transcript_path TEXT` or `transcript_text TEXT` column. Adding `transcript_path` (the .md file path) would let any agent find and read the file by querying the DB, creating a proper index.

3. **No agent reads transcripts.** Even if storage were fixed, no agent currently opens a .md file and mines it. A single-source-of-truth pattern would be:
   - x-intake writes transcript to `data/transcripts/@{author}...md` (persistent volume)
   - `queue.db` stores the path in a new `transcript_path` column
   - A new Cortex endpoint (e.g. `GET /api/x-intake/transcripts`) reads the queue for rows where `has_transcript=1` and serves the file content
   - OpenClaw's orchestrator (or a dedicated digest step) queries that endpoint, summarizes high-relevance transcripts, and writes insights to Cortex memory via `POST /remember`

This would close the loop from "video watched → transcript filed → insights surfaced in brain."

---

_Audit run by Claude Code on 2026-04-11/12. Health checks, row counts, and compose diffs are from live commands at audit time._
_X Intake review queue section added 2026-04-13._
_Transcript storage audit added 2026-04-13._
_Transcript AI analysis pipeline added 2026-04-13._
_Transcript integration verification added 2026-04-13 (live audit)._

---

---

## Reference: In-Place vs Missing Systems Audit (2026-04-13)

_Evidence-based pass. All findings from live commands, file inspection, and container state at audit time._

---

### 1 — symphonysh Site Readiness

**Classification: PARTIAL**

| What exists | Evidence |
|---|---|
| Build clean, 0 errors | `npm run build` — 2680 modules, 3.21s, no warnings |
| 128/128 assets matched in dist/ | `diff public/ dist/` — zero differences |
| SPA routing correct | `public/_redirects` + `dist/_redirects` both present; all sampled routes return HTTP 200 |
| Live on Cloudflare Pages | `symphonysh.com` → HTTP 200 verified April 13 |
| Real project data (15 projects) | `src/data/projects.ts` populated; no placeholder images |
| SEO schema wired | `businessSchema.ts` — LocalBusiness, NAP, geo coords, opening hours |
| Booking flow | `/scheduling` — multi-step form, Zapier webhook, confirmation page |

| What is missing / needs business input | Note |
|---|---|
| All `testimonial` fields are `null` | `projects.ts` — needs real client quotes before a Testimonials section can go live |
| `BUSINESS_SAME_AS` is an empty array | No Google Business Profile URL confirmed yet — highest-ROI SEO action remaining |
| Business address confirmation | `45 Aspen Glen Ct` is in schema; Matt needs to confirm it as the public-facing address |
| No "Previous Work" page | `src/pages/` has no `PreviousWork.tsx` — portfolio lives in `Projects.tsx`; may be intentional |
| `gptengineer.js` still loaded | Lovable editor hook in `index.html`; adds a third-party script request per page load |

**What still needs to happen:**
- Matt: claim Google Business Profile, paste Share URL into `BUSINESS_SAME_AS`
- Matt: provide 2–3 real client testimonial quotes
- Matt: confirm business address is OK to publish
- Optional: remove `gptengineer.js` once Lovable is fully retired

---

### 2 — X Intake Workflow

**Classification: PARTIAL (pipeline functional, storage ephemeral)**

| What exists | Evidence |
|---|---|
| Full ingestion pipeline | Redis `events:imessage` → fetch → transcribe → analyze → Cortex POST |
| Listener watchdog | `_listener_watchdog()` running at startup — restarts dead listener every 10s |
| Queue DB + review API | `queue_db.py` + 4 new endpoints (`/queue/stats`, `/queue`, `/approve`, `/reject`) |
| Dashboard card | 17 references to x-intake in `cortex/static/index.html`; approve/reject buttons wired |
| Active transcription | Logs show 12-chunk video being transcribed via OpenAI Whisper API right now |
| Cortex POST working | 84 `x_intel` memories in `brain.db` — pipeline IS writing intelligence |

| What is missing | Evidence |
|---|---|
| Volume mounts NOT applied to running container | `docker ps` `Mounts:""` for x-intake; `data/x_intake/queue.db` is 0 bytes on host |
| All queue data is ephemeral | queue.db in-container has 1 pending item; host-side file is 0 bytes — lost on restart |
| All transcript .md files are ephemeral | Writes to container-internal `/data/transcripts`; not mounted to host |
| x-alpha-collector source not tagged | `POST /analyze` body sends no `source` field — dashboard can't distinguish iMessage vs collector traffic |

**Critical gap:** The container is running on a pre-rebuild image. `docker compose up -d --build x-intake` is required to apply the `./data/x_intake` and `./data/transcripts` volume mounts. All active transcript work (currently mid-transcription) will be lost on next restart until this is done.

---

### 3 — Transcript Pipeline

**Classification: PARTIAL (analysis running, persistence at risk)**

| What exists | Evidence |
|---|---|
| `transcript_analyst.py` | Full pipeline: parse .md → Ollama/GPT-4o-mini → Cortex POST |
| Hidden gem extraction | Structured JSON output: `hidden_gems`, `actionable_tasks`, `content_ideas`, `usefulness_score` |
| Cortex memory writing | 84 `x_intel` entries in `brain.db` (analysis IS running and persisting via HTTP) |
| Backfill endpoint | `POST /transcripts/backfill` — processes orphaned .md files not in queue DB |
| Stats endpoint | `GET /transcripts/stats` — files on disk, analyzed, pending, failed counts |
| 2 host-side .md files | `data/transcripts/@hrundel75...md` and `@moondevonyt...md` (written April 3–4) |

| What is missing | Evidence |
|---|---|
| Volume mount not applied | Same issue as §2 — transcripts written inside container are ephemeral |
| `transcript_path` not reliably stored | When container doesn't have the volume, transcript_path in queue rows is a container-internal path that won't be readable after rebuild |
| No cross-transcript synthesis | No agent reads multiple transcripts to find patterns across authors or themes |
| No retry queue for failed Cortex POSTs | If Cortex is down during analysis, result is logged but not retried |

**Note:** The 84 `x_intel` memories confirm the LLM analysis pipeline is functioning end-to-end. The weak link is storage durability (ephemeral container), not the analysis logic.

---

### 4 — Dashboard / Operational Visibility

**Classification: PARTIAL**

| What exists | Evidence |
|---|---|
| Cortex dashboard at `/dashboard` | Running at `localhost:8102/dashboard`; all service tiles loading |
| Service health matrix | 16 services polled; healthy/degraded/down per tile |
| X intake card | 17 refs in `index.html`; shows pending/auto-approved counts; approve/reject buttons |
| Events log | Redis `events:log` — 1000 capped entries, real traffic flowing |
| Trading tile | P&L, positions, redeemer status proxied from polymarket-bot |
| Follow-ups tile | Reads `follow_ups.db` directly; 30-day filter, overdue count |
| Decisions tile | Reads `decision_journal.db` and Cortex memory in parallel |
| Memory: 654 entries | `brain.db` has 654 memories across 21 categories |

| What is missing / blind spot | Evidence |
|---|---|
| `/api/memory/stats` returns 404 | No memory breakdown visible in dashboard by category |
| `/api/entries` returns 404 | No direct memory list API — must use `/memories` (unfiltered) |
| 163 pending_approvals with no drain UI | All `email_classification` kind; growing (103 → 163 since April 12); no dashboard tile |
| email-monitor events missing from feed | `notifier.py` has zero `cortex` or `redis.publish` calls — email actions are invisible |
| openwebui tile still present | Container still running (Prompt N item 1 not done) |

---

### 5 — Background Bob / Team Automation

**Classification: PARTIAL**

| What is truly running automatically | Evidence |
|---|---|
| OpenClaw orchestrator | 40 active jobs, runs every 5 min; `orchestrator.py` confirmed |
| Daily briefing at 6 AM | Line 1288 in `orchestrator.py` — `send_daily_briefing` confirmed; posts to Cortex |
| Follow-up tracker | `follow_up_tracker.py` posts to Cortex on follow-up events |
| Approval drain | `approval_drain.py` posts to Cortex — exists, but 163 rows unprocessed |
| Remediator | Running healthy (no healthcheck); auto-restart watchdog for containers |
| x-intake listener watchdog | Restarts dead Redis listener every 10s |
| Redeemer | Runs every 180s; 297 conditions redeemed; gas 62.85 POL |

| Where human review is still required | Note |
|---|---|
| 163 `pending_approvals` (email_classification) | No automated drain; no iMessage batch-approval script; growing backlog |
| Follow-up send approvals | `follow_up_log` has 0 rows — auto-send loop has not fired; needs approval to send |
| Trading credentials | KRAKEN_SECRET and Polymarket wallet funding are Matt's actions |
| Testimonials / GBP | symphonysh business content inputs |

| What is clearly missing | Evidence |
|---|---|
| `email-monitor/notifier.py` → Cortex or `ops:email_action` | Zero matches for `cortex`, `remember`, `ops:email` in notifier.py — Prompt N item 2 not done |
| `/calendar/daily-briefing` fetch in orchestrator | Zero matches for `calendar/daily-briefing` in `orchestrator.py` — Prompt N item 3 not done |
| openwebui removal from docker-compose.yml | Container still running — Prompt N item 1 not done |

---

### 6 — Trading / Polymarket

**Classification: PARTIAL (engineering complete, blocked on credentials + funding)**

| What exists | Evidence |
|---|---|
| Bot running LIVE mode | `POLY_DRY_RUN=false`; 11 strategies registered and ticking; `status: running` |
| Redeemer operational | 297 conditions redeemed all-time; last cycle idle (96 pending markets unresolved) |
| POL gas adequate | 62.85 POL — well above 0.05 minimum |
| Bot receives X intel | 84 `x_intel` Cortex memories; Redis `polymarket:intel_signals` channel active |
| Trading observability | Startup banner TRADING READINESS section present |

| What is blocked | Evidence |
|---|---|
| `KRAKEN_SECRET` empty | `/kraken/status` returns empty body (auth failure every tick) |
| Wallet: $1.94 USDC | All 11 strategies skip with `copytrade_skip: low_bankroll` |
| Kalshi in demo mode | `KALSHI_DRY_RUN=true`, `KALSHI_ENVIRONMENT=demo` |

**Next step is funding + credentials, not engineering.** All code is in place. No code changes needed to unblock trading — only Matt's actions (wallet deposit + KRAKEN_SECRET).

---

### 7 — Email / Calendar / Prompt Follow-Up

**Classification: PARTIAL**

| What is fixed | Evidence |
|---|---|
| Calendar tile fixed | Zoho sentinel filtering + compact datetime parsing confirmed in `dashboard.py` |
| Follow-up noise filter | `symphonysh.com` in `FOLLOWUP_NOISE_SENDERS`; tile shows accurate count |
| Daily briefing runs | `orchestrator.py` confirmed; posts to Cortex |
| approval_drain.py exists | Posts to Cortex on decisions |

| What is "good enough for now" | Note |
|---|---|
| ~~All 435 emails marked `read=1`~~ | ✅ Fixed 2026-04-13 — `notifier.py` no longer sets `read=1`; 438 rows reset via migration script; `read=1` now requires Sent-folder In-Reply-To match |
| ~~follow_ups.db canonical~~ | ✅ Resolved 2026-04-17 — 61 rows at `data/email-monitor/follow_ups.db` (canonical), strays retired |
| Calendar timezone | Stripped + treated as local Denver time; acceptable but technically imprecise |

| What needs another pass | Evidence |
|---|---|
| email-monitor NOT posting to Cortex or ops:email_action | `notifier.py` — zero references to `/remember` or `ops:email_action` |
| Calendar daily-briefing not fetched in orchestrator | `orchestrator.py` — no `calendar/daily-briefing` call found |
| 163 pending_approvals unprocessed | No batch-drain script exists yet |

---

### 8 — Monitoring / Governance

**Classification: PARTIAL**

| What exists | Evidence |
|---|---|
| Redis `events:log` | 1000 capped entries; real traffic from all Redis-publishing services |
| Remediator | Running; auto-restarts unhealthy containers |
| `scripts/verify-cursor.sh` | Post-edit verification — checks files exist and are non-empty |
| `scripts/verify-deploy.sh` | Post-deploy smoke test — Redis PING + health checks |
| `scripts/pull.sh` | Safe git pull with stash + conflict scan |
| Cortex `brain.db` audit trail | 654 memories across 21 categories; decisions, x_intel, strategy_idea all flowing |

| Blind spots / gaps | Evidence |
|---|---|
| email-monitor emits no Redis ops events | `notifier.py` confirmed — no `ops:email_action` publish |
| Dropbox link validator absent | No validator found for `scl/fi/` vs `/preview/` enforcement (Lesson #4) |
| Lesson #17 (sell haircut rounding) unverified | Not confirmed in `polymarket-bot` code |
| 163 `pending_approvals` growing unchecked | Was 103 on April 12; no threshold alert, no auto-drain |
| openwebui still running | Prompt N item 1 not done; consuming memory unnecessarily |
| Cortex memory stats endpoint missing | `/api/memory/stats` → 404; dashboard has no memory category breakdown |

---

### NEXT 5 ITEMS

_Ranked by leverage — highest-impact, lowest-friction actions first._

**1. Rebuild x-intake** (`docker compose up -d --build x-intake`)
A video is actively being transcribed right now in 12 chunks. Without this rebuild, the volume mounts from `docker-compose.yml` are not applied, `queue.db` is ephemeral, and every transcript will be lost on the next container restart. One command. Zero code changes needed.

**2. Complete Prompt N items 1, 2, 3 (3 bounded changes)**
- Item 1: Remove `openwebui:` block from `docker-compose.yml` + `docker compose up -d` — frees memory, eliminates dead service tile
- Item 2: Add `redis.publish("ops:email_action", ...)` to `email-monitor/notifier.py` after action-required classification — closes the single biggest event-flow blind spot
- Item 3: Add `GET /calendar/daily-briefing` fetch to `openclaw/orchestrator.py` daily briefing assembly — confirmed missing by code grep

**3. Drain pending_approvals backlog (163 rows, all email_classification)**
Growing from 103 → 163 since April 12, with no drain mechanism. Implement Prompt T: group by kind, send batch to Matt via iMessage with YES/NO, auto-expire entries >7 days to `skipped` state with a log entry. Until this runs, 163 stale decisions are clogging the journal.

**4. Fund Polymarket wallet + set KRAKEN_SECRET** _(Matt action)_
Bot is live, all 11 strategies are ticking, redeemer is operational — blocked only by two missing inputs. `$50+ USDC` on Polygon wallet `0xa791...` + `KRAKEN_SECRET` via `bash scripts/set-env.sh KRAKEN_SECRET <value>` + `docker compose up -d polymarket-bot`. No code change needed.

**5. Update STATUS_REPORT stack health snapshot**
The April 12 snapshot says "21 entries, 1 this week" for Cortex. The live count is **654 memories across 21 categories** (84 x_intel, 328 install_notes, 55 proposal_template, 37 strategy_performance, etc.). The report is significantly out of date and misleads future agents about system health.

---

_Note on business-input dependencies: items 3–5 in "symphonysh" (testimonials, GBP, address) are exclusively waiting on Matt's real-world input. No engineering work is blocking them._

_Audit run: 2026-04-13. Evidence: live `docker ps`, `sqlite3` row counts, `curl` endpoint probes, file `grep` for code paths, container log tail. Weak evidence called out inline._

---

## Reference: Transcript AI Analysis Pipeline (2026-04-13)

### What was built

Three fragmentation problems identified in the transcript storage audit were fixed:

| Problem | Fix |
|---|---|
| Transcripts lost on container restart (no volume) | Added `./data/transcripts:/data/transcripts` volume + `TRANSCRIPT_DIR=/data/transcripts` env to x-intake in `docker-compose.yml` |
| `transcript_path` not stored in queue DB | Added `transcript_path TEXT` and `analyzed INTEGER` columns to `x_intake_queue`; schema migrates automatically on first boot |
| No agent reads transcripts | Created `transcript_analyst.py` — full deep-analysis pipeline reading .md files and writing to Cortex |

### Where transcript analysis now happens

**Entry point:** `integrations/x_intake/main.py`

After every successful video transcription, `main.py` now:
1. Stores the `.md` file path in `queue.db` (`transcript_path` column)
2. Fires `_analyze_transcript_background(transcript_path)` as an asyncio background task

**Analysis module:** `integrations/x_intake/transcript_analyst.py`

`analyze_transcript_file(md_path)` runs:
1. Parses the .md file (Summary, Flags, Strategies, Key Quotes, Full Transcript sections)
2. Builds a deep-analysis prompt covering all of Matt's interest areas (not just trading)
3. Tries Ollama first (`qwen3:8b`) → GPT-4o-mini fallback
4. Writes results to Cortex via `POST http://cortex:8102/remember`
5. Marks queue row `analyzed=1` (success) or `analyzed=2` (failed)

### What structured outputs are produced

The LLM returns a JSON object with:

| Field | What it contains | Written to Cortex as |
|---|---|---|
| `summary` | 3-5 sentences on the TRUE message of the video | `x_intel` memory |
| `key_topics` | 3-8 specific topics/techniques covered | Included in `x_intel` content |
| `hidden_gems` | Surprising/counterintuitive insights most people miss + why they matter to Matt | Included in `x_intel` content |
| `actionable_tasks` | Specific things Matt could build/implement/investigate, with priority | High+medium priority → separate `strategy_idea` or `external_research` memories |
| `content_ideas` | Angles for X posts or client education | Included in `x_intel` content |
| `tags` | 3-8 topic tags | Memory tags |
| `usefulness_score` | 0-100 integer (Matt-specific relevance) | Cortex memory `importance` (scaled) |
| `confidence` | 0.0-1.0 (transcript quality) | Cortex memory `confidence` |

**Cortex memory categories used:**
- `x_intel` — main insight (summary + hidden gems + content ideas); `importance` scales with usefulness score; 30-day TTL
- `strategy_idea` — high/medium priority "build" or "implement" tasks; 60-day TTL
- `external_research` — high/medium priority "research" or "investigate" tasks; 60-day TTL

### How Bob/agents find hidden gems

Once transcripts are analyzed, agents query Cortex normally:
```bash
# Find all transcript-derived insights
curl http://localhost:8102/memories?category=x_intel

# Search by topic
curl -X POST http://localhost:8102/query -H "Content-Type: application/json" -d '{"question":"trading strategy edge"}'

# Find all transcript tasks
curl http://localhost:8102/memories?category=strategy_idea
```

Transcript-sourced memories are tagged with the author handle and `transcript_task`, making them filterable.

### Backfill of existing transcripts

Two existing `.md` files in `data/transcripts/` (written before the volume was mounted) will be picked up by backfill:

```bash
# Trigger via API (runs in background, returns immediately)
curl -X POST http://localhost:8101/transcripts/backfill

# Or via Cortex proxy
curl -X POST http://localhost:8102/api/x-intake/transcripts/backfill

# Check status
curl http://localhost:8101/transcripts/stats
curl http://localhost:8102/api/x-intake/transcripts/stats
```

Backfill processes:
1. Queue DB rows with `has_transcript=1` and `analyzed=0` that have `transcript_path` set
2. Orphaned .md files in `data/transcripts/` not yet in the queue DB (the 2 pre-existing files)

### Listener watchdog (§Z14 fix also applied)

The Redis listener crash bug from 2026-04-11 was fixed in the same pass: startup now launches `_listener_watchdog()` instead of `_redis_listener()` directly. The watchdog checks every 10 seconds and restarts the listener if it has died.

### Observability

| Log event | When it fires |
|---|---|
| `transcript_analyst_start` | File processing begins |
| `transcript_analyzed` | LLM returned results (score, gem count, task count) |
| `transcript_cortex_written` | Memories posted to Cortex (count) |
| `transcript_cortex_posted` | Individual Cortex POST succeeded |
| `transcript_cortex_failed` | Cortex POST failed (Cortex down?) |
| `transcript_analysis_failed` | Both Ollama and OpenAI failed |
| `transcript_too_sparse` | Transcript is too short/garbled to analyze |
| `transcript_bg_analysis` | Background task completed (from main.py) |
| `transcript_bg_analysis_failed` | Background task threw exception |
| `redis_listener_restarting` | Watchdog detected dead listener |

### Remaining limitations

1. **Cortex must be running** — Cortex POST failures are logged and retried only via the backfill path. There is no internal queue to retry failed POSTs automatically.
2. **Transcript file format is fixed** — `transcript_analyst.py` expects the `.md` format written by `video_transcriber.save_transcript()`. Manually created or differently-formatted files may parse incompletely but won't crash.
3. **Ollama host must be accessible** — Ollama is tried first. If `http://192.168.1.199:11434` is unreachable (e.g. running outside the home network), the system falls back to OpenAI automatically.
4. **No cross-transcript de-dup** — If the same video is processed twice (two separate X links pointing to the same content), two separate Cortex memories are created. Low frequency in practice.

### Deploy commands

```bash
# Full rebuild required (new volume mount + new source file)
docker compose up -d --build x-intake

# Cortex is bind-mounted — restart sufficient for dashboard.py change
docker compose restart cortex

# Verify transcript volume mounted correctly
docker exec x-intake ls /data/transcripts

# Trigger backfill of the 2 existing transcripts
curl -X POST http://localhost:8101/transcripts/backfill

# Check analysis stats after backfill
curl http://localhost:8101/transcripts/stats
```

---

## Reference: Transcript Integration Verification (2026-04-13 live audit)

_All findings from live commands against the running container and host filesystem. No assumptions._

**Overall status: NOT WORKING — 0% analysis success rate, 0 memories from transcript_analyst in Cortex.**

---

### Q1 — Where do transcripts actually live today?

| Location | Path | Files | Durable? |
|---|---|---|---|
| Host filesystem | `~/AI-Server/data/transcripts/` | 2 files (Apr 3–4) | ✅ Yes — but orphaned (never analyzed) |
| Container ephemeral | `/root/AI-Server/data/transcripts/` (inside x-intake) | 4 files (Apr 13) | ❌ No — lost on container restart |
| Bind-mount target | `/data/transcripts` (inside x-intake) | Does not exist | — env var not applied |

**Root cause:** The running x-intake container is missing `TRANSCRIPT_DIR` and `CORTEX_URL` from its environment (`docker exec x-intake env` confirmed). The `docker-compose.yml` has both, but the container was last created before those vars were added. It was restarted (not recreated) since, so it runs with the old env. Without `TRANSCRIPT_DIR`, `video_transcriber.py` falls back to `~/AI-Server/data/transcripts` which expands to `/root/AI-Server/data/transcripts` inside the container — an unbound ephemeral path.

Verified: `docker exec x-intake ls /root/AI-Server/data/transcripts/` lists 4 files. `docker exec x-intake ls /data/transcripts/` exits non-zero (directory does not exist).

---

### Q2 — How do transcripts enter the analysis pipeline?

The wiring is correct in code:

1. `video_transcriber.process_x_video()` → calls `save_transcript()` → writes `.md` to `TRANSCRIPT_DIR`
2. `main.py._process_url_and_reply()` → calls `_analyze_transcript_background(transcript_path)` after enqueue if `transcript_path` is set
3. `_analyze_transcript_background()` → calls `transcript_analyst.analyze_transcript_file(path)` in a thread
4. `transcript_analyst` → Ollama (primary) → GPT-4o-mini (fallback) → `POST /remember` to Cortex

The trigger fires correctly. The path is wired. The failures occur inside step 3.

---

### Q3 — Are transcripts being analyzed into structured outputs?

**No. 100% failure rate on all attempts.**

Evidence from `docker logs x-intake --tail 200`:

| Log event | Count (last 200 lines) | Expected |
|---|---|---|
| `transcript_analyst_start` | 2 | ✓ fires correctly |
| `transcript_bg_analysis_failed` | 2 | ✗ should be 0 |
| `transcript_analyzed` | 0 | ✗ should match start count |
| `transcript_cortex_posted` | 0 | ✗ should follow success |

Error captured: `error='\'\\n  "summary"\''` — this is an exception (likely JSONDecodeError or KeyError) where the value `'\n  "summary"'` appears as the error string. This points to Ollama's qwen3:8b model producing malformed JSON in its response — qwen3:8b has a "thinking" mode that prepends reasoning tokens before the JSON output. With `format: json` enabled, the response body may contain a partial or prefix-corrupted JSON structure that both `json.loads()` and the code-block regex fail to parse, ultimately causing an unhandled exception that propagates out of `analyze_transcript_file` and is caught by the outer `transcript_bg_analysis_failed` handler.

The OpenAI fallback (`_openai_analyze`) runs only if `_ollama_analyze` returns `None` cleanly. If Ollama raises an exception that is NOT caught inside `_ollama_analyze`, it propagates before the fallback can run. Reviewing `_ollama_analyze`: all exceptions ARE caught (`except Exception as exc: logger.info(...); return None`). So the exception must originate elsewhere — most likely inside `_write_to_cortex` or `analyze_transcript_file` itself when processing the analysis dict, suggesting Ollama IS returning a response, but the response dict has unexpected structure that causes a downstream error.

**Net result: neither Ollama nor OpenAI paths are successfully producing Cortex memories from transcripts.**

---

### Q4 — Which agent/service is responsible?

| Component | Role | Status |
|---|---|---|
| `x-intake` container (port 8101) | Hosts the pipeline; triggers analysis | Running healthy |
| `integrations/x_intake/transcript_analyst.py` | Deep analysis + Cortex write | Code complete; runtime failing |
| `integrations/x_intake/main.py` | Triggers background analysis task | Wired correctly |
| `integrations/x_intake/video_transcriber.py` | Downloads, transcribes, saves .md | Working (files written) |
| Cortex `POST /remember` | Receives analysis output | Reachable (other services posting successfully) |

---

### Q5 — Are results visible anywhere?

| Store | Transcript-analyst memories | Source |
|---|---|---|
| `brain.db` — `x_intel` category | **0 rows** with `source LIKE 'x_intake:@%'` | Confirmed by `sqlite3` query |
| `brain.db` — `strategy_idea` category | **0 rows** with `title LIKE '[Task/@%'` | Confirmed by `sqlite3` query |
| `brain.db` — total `x_intel` | 92 entries, all titled "X Signal" | From x_alpha_collector / main.py quick-analysis path |
| `data/x_intake/queue.db` (host) | 0 bytes — never initialized | Container DB is ephemeral (no bind mount applied) |
| Cortex dashboard transcript stats | Proxied endpoint exists; returns 0 analyzed | `GET /transcripts/stats` works but shows nothing done |

The 92 `x_intel` memories that DO exist in Cortex come from the **short first-pass analysis** in `main.py._analyze_with_llm()` — not from `transcript_analyst`. These are the `RELEVANCE / TYPE / SUMMARY / ACTION` formatted memories, not the deep structured analysis (no hidden gems, no actionable tasks, no content ideas).

---

### Q6 — What is missing for this to work reliably?

Two blockers, in order of severity:

**Blocker 1 — Container not recreated (CRITICAL)**

```bash
docker compose up -d --build x-intake
```

This one command applies `TRANSCRIPT_DIR=/data/transcripts`, `CORTEX_URL=http://cortex:8102`, and the `./data/transcripts:/data/transcripts` volume mount. Until it runs:
- All new transcripts go to the ephemeral `/root/AI-Server/data/transcripts/` and are lost on restart
- `queue.db` on the host remains 0 bytes (container DB is not bind-mounted)
- The 4 transcripts written today inside the container will be lost on next restart

**Blocker 2 — Ollama JSON parse failure (BUG)**

`qwen3:8b` is the configured `OLLAMA_ANALYSIS_MODEL`. This model's thinking mode causes it to return JSON that the current parser cannot handle, producing an exception that bypasses the OpenAI fallback. Fix options (smallest first):

Option A — Strip thinking tags before parsing in `_ollama_analyze`:
```python
# After: content = raw.get("message", {}).get("content", "")
import re as _re
content = _re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
```

Option B — Disable thinking via Ollama options:
```python
# In the payload dict, change options to:
"options": {"temperature": 0.2, "think": false}
```

Option C — Switch to a model without thinking mode (e.g., `llama3.2`, `mistral`).

Until Blocker 2 is fixed, even after the container rebuild, `transcript_analyst` will fail on every Ollama call and fall through to OpenAI. OpenAI may succeed independently — needs verification after Blocker 1 is resolved.

**Gap 3 — 2 orphaned host-side transcripts never analyzed**

`data/transcripts/@hrundel75...md` (Apr 3) and `@moondevonyt...md` (Apr 4) are on disk but have never been processed. After the container is rebuilt and Blocker 2 is fixed, run:

```bash
curl -X POST http://localhost:8101/transcripts/backfill
curl http://localhost:8101/transcripts/stats
```

Note: `@hrundel75` has only `🎵` as its full transcript — `transcript_analyst` will correctly skip it as "too sparse". `@moondevonyt` has real transcript text (trading strategies, win rates) and should produce 1–3 Cortex memories.

---

### Exact next step

```bash
# Step 1: recreate the container with correct env + volumes
docker compose up -d --build x-intake

# Step 2: verify env applied
docker exec x-intake env | grep -E "TRANSCRIPT|CORTEX"
# Expected: TRANSCRIPT_DIR=/data/transcripts  CORTEX_URL=http://cortex:8102

# Step 3: verify volume mounted
docker exec x-intake ls /data/transcripts
# Expected: 2 .md files (the April 3-4 host files)

# Step 4: trigger backfill of existing transcripts
curl -X POST http://localhost:8101/transcripts/backfill

# Step 5: check results
curl http://localhost:8101/transcripts/stats
# If analyzed > 0, also check Cortex:
curl "http://localhost:8102/memories?category=x_intel" | python3 -m json.tool | grep -A3 "x_intake:@"
```

If step 5 shows `analyzed=0` and `failed=1` for the moondevonyt file, Blocker 2 (Ollama JSON parse) is confirmed and the qwen3:8b thinking-tag strip fix must be applied before the next rebuild.

---

## Reference: Prompt T Drain (§T, 2026-04-13)

### State definitions

| State | Set by | Meaning |
|---|---|---|
| `pending` | openclaw orchestrator | Row created, awaiting human or automated decision |
| `expired` | `openclaw/approval_drain.py` | Auto-expired by the regular drain tick (uses `expired` label) |
| `skipped` | `scripts/prompt_t_drain.py` | One-shot Prompt T auto-decision; reason encoded in linked `decisions.outcome` |
| `approved` | Future: Matt replies YES | Human explicitly approves (not triggered this run) |
| `rejected` | Future: Matt replies NO | Human explicitly rejects (not triggered this run) |

The `expired` state pre-dates Prompt T and is left in place. `skipped` is the new Prompt T state. Both tables are updated atomically per row:
- `pending_approvals.status` → `'skipped'`
- `decisions.outcome` → `'skipped_by_prompt_t:<reason>'`
- `decisions.outcome_at` → ISO timestamp of the drain run

### Skip reasons

| Reason | Description | Count this run |
|---|---|---|
| `stale_auto_expire` | Row is older than 7 days | 0 |
| `auto_low_value` | `email_classification` kind + `classification=GENERAL` + `confidence < 50%` | 1 |
| `duplicate_entry` | Same `email_id` appears more than once (keep first, skip the rest) | 62 |

### What was in the backlog

All 63 `pending` rows were the same email repeated 63 times — `email_id: 42496`, subject "We're making some changes to our PayPal legal agreements", classification `GENERAL`, confidence 45%. This is a dedup bug in the email-monitor: the classifier re-ran on the same email ID across multiple orchestrator ticks without deduplicating `pending_approvals` inserts.

**Follow-up:** Add a `UNIQUE` constraint or a pre-insert check on `(decision_id)` in `pending_approvals` to prevent this from recurring. The `decision_id` column already has `UNIQUE` in the schema — the root cause is likely that each orchestrator tick is creating a new `decisions` row for the same email, producing a unique `decision_id` each time.

### Drain results (2026-04-13 08:24 MDT)

| Metric | Value |
|---|---|
| Total rows before drain | 166 |
| Already `expired` (untouched) | 103 |
| `pending` rows found | 63 |
| Stale (`>7 days`) → `skipped` | 0 |
| Auto low-value → `skipped` | 1 |
| Duplicate entry → `skipped` | 62 |
| Remaining `pending` after drain | **0** |
| `decisions` rows updated with outcome | 63 |
| iMessage summary sent to Matt | ✅ yes (via notification-hub `/api/send`) |
| Cortex memory written | ✅ yes (category: `system`) |

### Verification commands

```bash
# Confirm pending is 0
sqlite3 data/openclaw/decision_journal.db "SELECT status, COUNT(*) FROM pending_approvals GROUP BY status"
# Expected: expired|103  skipped|63

# Confirm decisions outcomes written
sqlite3 data/openclaw/decision_journal.db "SELECT outcome, COUNT(*) FROM decisions WHERE outcome LIKE 'skipped_by_prompt_t%' GROUP BY outcome"
# Expected: skipped_by_prompt_t:auto_low_value|1   skipped_by_prompt_t:duplicate_entry|62

# Re-run drain to confirm idempotent (should drain 0 rows)
python3 scripts/prompt_t_drain.py --dry-run
```

### Script location and re-use

`scripts/prompt_t_drain.py` — self-contained, stdlib-only (no pip installs). Safe to re-run at any time:
- Idempotent: only `pending` rows are touched; `expired`/`skipped` rows are ignored
- Dry-run flag: `--dry-run` prints plan without writing
- Configurable thresholds: `STALE_DAYS`, `AUTO_SKIP_CONFIDENCE_THRESHOLD` at top of file
- The batch-to-Matt path (Phase 6) activates only for high-confidence or non-GENERAL items; it sent 0 iMessages this run because all items were auto-decided

_Prompt T drain run by Cline on 2026-04-13. DB verified via live sqlite3 queries._

---

## Reference: X-Intake Diagnose & Fix (2026-04-16)

### Phase A findings (what was broken)

| Check | Result |
|---|---|
| A1 — Volume mounts on x-intake | ✅ Both `./data/x_intake:/data/x_intake` and `./data/transcripts:/data/transcripts` mounted |
| A2 — TRANSCRIPT_DIR / CORTEX_URL env | ✅ `TRANSCRIPT_DIR=/data/transcripts`, `CORTEX_URL=http://cortex:8102` |
| A3 — Queue DB | 122 880 bytes; 32 rows; 12 rows stuck at `has_transcript=1, analyzed=0`; 3 at `analyzed=2` (failed) |
| A4 — Last 10 rows | `transcript_path` values like `/data/transcripts/@MoonDevOnYT — … — 2026-04-14.md`; `analyzed=0` on rows created Apr 13–14 |
| A5 — Transcripts on disk | 17 .md files in `data/transcripts/`; volume IS mounted to host |
| A6 — x-intake logs | `KeyError: '\n  "summary"'` traceback from `transcript_analyst.py:498::run_backfill` — `_build_prompt` uses `.format()` on a template with literal JSON `{}` braces |
| A7 — Cortex dashboard | `/api/x-intake/stats` → OK; `/api/x-intake/items` → `{"error":"db not found"}` — cortex container has no `data/x_intake` mount |
| A8 — Listener subscriber count | `[(b'events:imessage', 1)]` — listener alive |

### Classification

- **B3 — YES** — 12 rows stuck `analyzed=0`; `_build_prompt` raised `KeyError` crashing every backfill attempt (second bug on top of the qwen3:8b `<think>` tag issue)
- **B5 — YES** — Cortex container missing `./data/x_intake:/data/x_intake:ro` mount

### Fixes applied

| Commit | Fix |
|---|---|
| `0a18fc6` | `fix(x-intake): strip qwen3:8b think tags + backfill CLI for stuck analyze rows` — `re.sub(r"<think>[\s\S]*?</think>", "", content)` in both `transcript_analyst._ollama_analyze` and `main._analyze_with_ollama`; added `--reanalyze-stuck` CLI to `main.py` |
| `847496c` | `fix(cortex): mount x_intake queue db read-only into dashboard container` — added `./data/x_intake:/data/x_intake:ro` to cortex service volumes |
| `4357509` | `fix(x-intake): fix KeyError in _build_prompt by using replace() instead of format()` — `_DEEP_PROMPT` contains literal JSON `{}` example blocks; `.format()` interprets them as named placeholders and raises `KeyError`; switched to `.replace("{author}", author).replace("{body}", body)` |

### Regression test results

```
# POST /transcripts/backfill triggered after rebuild
# After 90s:
GET /transcripts/stats → {"files_on_disk":17,"total_with_transcript":15,"pending_analysis":0,"analyzed":12,"failed":3}

# Listener test: published fake URL → detected and processed (auto_rejected, 0 relevance — expected for non-existent URL)
# Dashboard: GET /api/x-intake/items?limit=3 → returns real rows with full JSON including summary, action, transcript_path

# Log evidence (last 200 lines):
# asyncio.new_event_loop occurrences: 0
# Unhandled Tracebacks: 0
# transcript_analyzed events: multiple (scores 85, 85, 0, 85, 85...)
# transcript_cortex_posted events: multiple (ids acdd7306, d4cb07fb, ec5964c1, ...)
```

### Remaining known limits

- **Ollama unreachable from x-intake container** — all 12 backfill analyses fell back to OpenAI (`transcript_ollama_miss — trying openai`). The `OLLAMA_HOST` default `http://192.168.1.189:11434` is not reachable from inside the x-intake Docker network (likely requires the host's Tailscale IP or `host.docker.internal`). Ollama is optional — OpenAI fallback works — but costs API tokens for each transcript.
- **3 failed rows (`analyzed=2`)** — short/garbled transcripts correctly marked `too_sparse` by the analyst. These are expected failures (e.g. `@hrundel75` with only `🎵` content).
- **x-alpha-collector source not tagged** — still sends no `source` field to `/analyze`, so dashboard can't distinguish iMessage vs collector traffic (pre-existing, low priority).

---

## Reference: X-Intake Pass 2 — Remaining Issues (2026-04-16)

_Second diagnostic pass by Cline (cline-prompt-x-intake-diagnose-and-fix.md). Previous pass fixed volumes/env/schema/cortex-mount. This pass found and fixed the one remaining gap._

### Phase A findings (this session)

| Check | Result |
|---|---|
| A1 — Volume mounts | ✅ Both `./data/x_intake:/data/x_intake` and `./data/transcripts:/data/transcripts` mounted |
| A2 — TRANSCRIPT_DIR env | ✅ `TRANSCRIPT_DIR=/data/transcripts` set in container |
| A3 — Queue DB | 122 880 bytes; 33 rows; schema has `analyzed`, `has_transcript`, `transcript_path` ✅ |
| A4 — Row breakdown | `auto_approved\|0\|0\|8` — text-only posts stuck at `analyzed=0`; transcript posts at `analyzed=1/2` ✅ |
| A5 — Transcripts on disk | 17 .md files present in `data/transcripts/` ✅ |
| A6 — x-intake logs | Only health checks and queue/stats in last 150 lines — no `asyncio.new_event_loop`, no Traceback ✅ |
| A7 — Cortex dashboard | `/api/x-intake/stats` → correct counts; `/api/x-intake/items` → correct JSON rows ✅ |
| A8 — Listener subscriber | `[(b'events:imessage', 1)]` — listener alive ✅ |

### Classification

- **B3 — PARTIAL** — text-only posts have `analyzed=0` permanently. `queue_db.enqueue()` inserts `analyzed=0` as default and no code path ever sets it to 1 for posts without transcripts (only `_analyze_transcript_background` sets it, and only for transcript posts). All other B-class issues (mounts, schema, transcripts, dashboard, listener) were already resolved.

### Fix applied

**Commit `b7c4da9`** — `fix(x-intake): loud errors + set_analyzed for text posts + store watchdog task on app.state`

| Change | File |
|---|---|
| Added `error_msg TEXT DEFAULT ''` to `_MIGRATE_COLUMNS` | `queue_db.py` |
| Added `set_analyzed(row_id, value, error_msg)` function | `queue_db.py` |
| Import `set_analyzed as _db_set_analyzed` | `main.py` |
| Capture `_queue_row_id = _db_enqueue(...)` return value | `main.py` |
| Call `_db_set_analyzed(_queue_row_id, 1)` for text-only posts (not `_has_transcript`) | `main.py` |
| `app.state.watchdog_task = asyncio.create_task(...)` — prevent GC | `main.py` |
| `logger.exception("url_analysis_failed")` — full traceback in logs | `main.py` |

### Backfill of pre-existing rows

```sql
-- Ran directly on host (18 rows updated):
UPDATE x_intake_queue SET analyzed=1
WHERE has_transcript=0 AND analyzed=0 AND summary != '' AND summary IS NOT NULL;
-- Result: all text-only rows (8 auto_approved, 6 auto_rejected, 3 rejected, 1 approved) → analyzed=1
```

### Regression test results

```
# Published https://x.com/karpathy/status/1798616493476192708 via Redis:
docker exec x-intake python3 -c "import redis,os,json,time; r=redis.from_url(os.environ['REDIS_URL']); r.publish('events:imessage', json.dumps({'text':'https://x.com/karpathy/status/1798616493476192708','source':'regression_test','timestamp':time.time()}))"

# After 90s:
sqlite3 data/x_intake/queue.db "SELECT id, status, analyzed, has_transcript FROM x_intake_queue ORDER BY id DESC LIMIT 1"
# → 34|auto_rejected|1|0  ← analyzed=1 for text-only post ✅

curl 'http://127.0.0.1:8102/api/x-intake/items?limit=1' | python3 -m json.tool | grep '"analyzed"'
# → "analyzed": 1  ✅

docker exec x-intake python3 -c "import redis,os; r=redis.from_url(os.environ['REDIS_URL']); print(r.pubsub_numsub('events:imessage'))"
# → [(b'events:imessage', 1)]  ✅

docker logs x-intake --tail 50 | grep -c "new_event_loop"
# → 0  ✅
docker logs x-intake --tail 50 | grep -c "Traceback"
# → 0  ✅
```

### Remaining known limits

- **`analyze_endpoint` row_id not captured** — the `/analyze` HTTP endpoint calls `_db_enqueue` but doesn't capture the row_id to call `set_analyzed`. Text-only posts submitted via `POST /analyze` directly still get `analyzed=0`. Low impact (most traffic is via Redis listener), but worth fixing in a follow-up pass.
- **Ollama unreachable** — `OLLAMA_HOST=http://192.168.1.189:11434` not reachable from inside Docker network; all analysis falls back to OpenAI. Not a blocker; OpenAI fallback works.
- **x-alpha-collector source not tagged** — pre-existing, low priority.

_Pass 2 run by Cline on 2026-04-16. Evidence: live `docker inspect`, `sqlite3`, `curl`, container log grep._

---

## Reference: Meeting Audio Intake Pipeline (2026-04-17)

### What was built

- **`scripts/audio_intake_worker.py`** — host-side Python worker that scans `~/AI-Server/data/audio_intake/incoming/` for `.wav`/`.m4a`/`.mp3`/`.flac`/`.aac`, transcribes via `whisper-cli` (Metal-accelerated on the M4), runs a meeting-focused LLM analysis (Ollama qwen3:8b → GPT-4o-mini fallback), and writes a single `meeting_intel` memory per meeting to Cortex via `POST /remember`. Lock-file guarded so overlapping launchd runs don't double-process.
- **`~/AI-Server/data/audio_intake/{incoming,processing,processed,failed}/`** + `queue.db` (table `audio_intake_queue` with status, transcript path, summary, participants, clients, projects, action items, dollar amounts, cortex memory id, error msg, timestamps).
- **`~/AI-Server/data/transcripts/meetings/<YYYY-MM-DD>__<slug>.md`** — durable markdown artifact per meeting (Summary / Participants / Clients / Projects / Decisions / Action Items / Dollar Amounts / Topics / full transcript).
- **whisper.cpp** — installed via `brew install whisper-cpp` (1.8.4, Metal + BLAS backends). Model: `ggml-large-v3.bin` (2.9 GB) at `~/AI-Server/models/whisper/`.
- **launchd job `com.symphony.audio-intake`** — loaded from `scripts/launchd/com.symphony.audio-intake.plist`, runs every 600s (10 min), `RunAtLoad=true`. Stdout/stderr at `data/audio_intake/launchd.{out,err}.log`.
- **Cortex dashboard** — new `GET /api/meetings/recent` endpoint (reads queue DB via read-only bind mount) + "Meetings" tile in column 3 of the Overview tab, between X Intake and Daily Digest. Shows done-today count, in-queue count, and the 3 most recent meetings with status dots. Card turns red when any row is `failed`.
- **`docker-compose.yml`** — added `./data/audio_intake:/data/audio_intake:ro` to the cortex service so the dashboard can read the queue without touching the host-side worker.
- **`MEETING_INGEST_STEPS.md`** — one-paste Bert seed-run block covering rsync + worker trigger + polling + final per-file report, bounded at 90 min wall-clock. Safe to re-run; rsync and worker both idempotent.

### How to use

Drop any `.wav` / `.m4a` / `.mp3` / `.flac` / `.aac` into `~/AI-Server/data/audio_intake/incoming/`. Within 10 minutes (or instantly if you run `python3 ~/AI-Server/scripts/audio_intake_worker.py` manually), the file will be transcribed, analyzed, written to `data/transcripts/meetings/`, ingested into Cortex as a `meeting_intel` memory, and moved to `processed/`. Failures land in `failed/` and are visible in the queue DB + the dashboard "Meetings" tile.

Search from Cortex:

```bash
curl "http://127.0.0.1:8102/memories?category=meeting_intel" | python3 -m json.tool
curl "http://127.0.0.1:8102/api/meetings/recent" | python3 -m json.tool
```

### Signature note — `transcript_analyst` not reused directly

`integrations/x_intake/transcript_analyst.analyze_transcript_file(md_path)` was designed for the X-video pipeline: it expects a `.md` with specific sections (Summary/Flags/Strategies/Key Quotes/Full Transcript) and writes its own `x_intel` / `strategy_idea` / `external_research` Cortex memories. It does **not** return the `{participants, clients, projects, action_items, dollar_amounts}` shape the meeting pipeline needs. Per Guardrail §6 ("do not rewrite the analyst"), the worker ships a parallel meeting-focused analyzer that reuses the same Ollama-first-then-OpenAI pattern and the same Cortex `/remember` contract but emits a single `meeting_intel` memory with the fields Matt asked for.

### Known limits

- Whisper model is `large-v3` (picked because Bob had 82 GB free at install time). Worker's `pick_model()` falls back to `medium`/`small` if large-v3 is ever removed.
- Language is forced to English (`-l en`). Multilingual runs would need a flag flip.
- Ollama at `192.168.1.189:11434` is usually reachable from Bob's host network but not from the cortex container — not a problem here because the worker is host-side. If Ollama is down, the worker falls through to OpenAI automatically.
- Worker timeout on whisper is 2 hours per file. Multi-hour recordings may need splitting upstream.

_Built by Cline on 2026-04-17 per `.cursor/prompts/cline-prompt-meeting-audio-intake.md` (AUTO_APPROVE=true). Acceptance criteria all green at commit time: whisper-cli installed; `ggml-large-v3.bin` 2.9G on disk; all 4 intake dirs created; queue schema applied; launchd job loaded; empty-queue worker run completes in <0.1s; `/api/meetings/recent` returns `[]`._

### Self-improvement loop — 20260422T120000Z

inbox processed: 1, cards: 1 (0 auto-run / 0 needs-Matt / 0 deferred / 0 external / 1 needs-fetch)

- `20260422T111725Z-imessage-x-com-ihtesham2005-status-2046528187593830850-card.md` — **needs fetch** — iMessage-captured X link from @ihtesham2005; tweet content unknown, cannot assess automation potential until fetched

---

## Self-improvement loop (2026-04-22, autonomous subagent)

Added a bounded, repo-safe self-improvement workflow so Matt can capture
X/Twitter links and automation ideas on the fly and have Claude Code
turn them into scored improvement cards without any external
execution. Captured content is inspiration/evidence only — never run.

- **Docs:** `docs/self-improvement-loop.md` — full loop (capture →
  archive → summarize → classify/score → card → decide → record),
  safety rules, directory map, commands, and explicit mention that
  Linear/Twilio/Zoho are future routing targets, not active.
- **Prompt:** `.cursor/prompts/self-improvement/process-inbox.md` —
  bounded prompt that reads up to 20 small inbox files, archives them
  verbatim, emits one card per item under `ops/self_improvement/cards/`
  with impact/effort/risk scoring and a recommended next action, and
  writes a verification artifact. No web browsing by default, no secret
  reads, no outbound messaging.
- **Script:** `scripts/self-improve.sh` — `add-url`, `add-note`, `list`,
  `process`, `promote`. `process` routes through
  `scripts/ai-dispatch.sh run-prompt` and falls back to direct `claude`
  1M if the dispatcher is absent. `promote` is print-only — it surfaces
  the proposed next command/prompt path for Matt to review and run
  manually, never executes the change itself.
- **Directories:** `ops/self_improvement/{inbox,cards,archive}/` plus
  `.cursor/prompts/self-improvement/`, all with `.gitkeep` where
  appropriate.
- **Docs updated:** `docs/away-workflow.md` §5b and
  `docs/autonomous-llm-orchestration.md` — both include the away-mode
  SSH recipe (`ssh matt@bob`, `add-url`, `process`).

No recurring scheduled tasks were created. No external connectors were
wired. The loop explicitly depends on existing dispatcher / verification
/ STATUS_REPORT gates for anything that would actually change the repo.

---

## Reference: Bob Freezing Diagnosis (2026-04-23)

Static-analysis pass per `.cursor/prompts/diagnose-bob-freezing-and-runtime-hangs.md`. Dynamic checks (phases 1/2/5 and lockfile/log tails) were **skipped** because this run executed on Matt's MacBook M2 Pro, not on Bob; a follow-up pass on Bob is required.

- **Root cause (high confidence):** `scripts/task_runner.py` runs `git pull`/`push`/`commit`/`status` via `subprocess.run` with no `timeout=`. Combined with the `fcntl.flock` single-instance lock on `data/task_runner/.runner.lock`, one stalled git call wedges every subsequent launchd tick. Lines: task_runner.py:131, 218, 652, 722, 743.
- **Secondary:** `scripts/bob-watchdog.sh` `docker_healthy` calls `docker info`/`docker ps` without `--timeout`; can hang on the Docker Desktop "zombie daemon" mode already documented in-repo on 2026-04-21.
- **Ruled out (static):** Cortex loops + HTTP / x_intake listener / bluebubbles — all carry explicit `timeout=` on httpx, subprocess, and redis socket calls.
- **Fix path:** Phase 1 prompt at `.cursor/prompts/fix-bob-freezing-phase-1-runner-git-timeouts.md` (low risk, ≤ 40 LOC across `scripts/task_runner.py` + `scripts/bob-watchdog.sh` + one pytest). Deferred to a Bob-local run so Phase 1/2 baseline capture can precede the patch.
- **Audit:** `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md`
- **Verification:** `ops/verification/20260423-131042-bob-freeze-diagnosis.txt`
- [FOLLOWUP] Run `.cursor/prompts/fix-bob-freezing-phase-1-runner-git-timeouts.md` on Bob to apply Option A+B from the audit.
- [FOLLOWUP] Resolve pre-existing merge conflict in `ios-app/SymphonyOps/SymphonyOps/ContentView.swift` (UU on Matt's MacBook during this pass; not touched per prompt guardrails).

_Diagnosed by Claude Code on 2026-04-23 (static-only). Committed via a clean `git worktree` at origin/main because the main checkout carried the above unresolved conflict._

---

## Phase 1 Fix — Bob Runner/Watchdog Bounded (2026-04-23)

Implements Option A + B from `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md` per `.cursor/prompts/fix-bob-freezing-phase-1-runner-git-timeouts.md`.

- **scripts/task_runner.py** — added `GIT_TIMEOUT=60` + `GIT_NONINTERACTIVE_ENV` (`GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=/usr/bin/true`, `GIT_SSH_COMMAND` with `BatchMode=yes`, `ConnectTimeout=10`, `ServerAliveInterval=5`). Every git `subprocess.run` (git() helper, handle_git_pull, has_changes, pull_latest ff-only, pull_latest rebase fallback) now passes `timeout=GIT_TIMEOUT` + `env=_git_env()` and returns gracefully on `TimeoutExpired` — rc=124 shaped into a `CompletedProcess` so the tick releases its `fcntl.flock` cleanly.
- **scripts/bob-watchdog.sh** — added a portable `bounded` helper (prefers `timeout`/`gtimeout`, falls back to background+kill) and wrapped the `docker info` + `docker ps -q` probes in `bounded 10`. Zombie-daemon mode documented 2026-04-21 can no longer hang the watchdog.
- **ops/tests/test_task_runner_git_timeouts.py** — new smoke test. Monkey-patches `subprocess.run` to raise `TimeoutExpired` and asserts each helper degrades gracefully; also asserts `GIT_TERMINAL_PROMPT=0` + SSH `BatchMode=yes` land in the runner env. 15/15 assertions pass. Pre-existing `ops/tests/test_task_runner_gates.py` still passes.
- **Verification:** `ops/verification/20260423-134031-bob-freeze-fix1.txt`
- **Audit:** `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md`
- [FOLLOWUP] Run on Bob: `bash scripts/pull.sh` → `pgrep -fl scripts/task_runner.py` (identify any wedged tick) → `kill <PID>` (only if one is > 10 min old) → `timeout 30 python3 scripts/task_runner.py` (one-shot re-prime) → confirm `tail -n 5 data/task_runner/heartbeat.txt` advanced. Full commands in the fix prompt's Phase 5.
- **Scope respected:** no launchd plist edit, no Docker/Redis/secrets/messaging changes; the lock semantics (`fcntl.flock`) are unchanged — only the subprocesses inside the tick are bounded.

_Implemented by Claude Code on 2026-04-23 (AUTO_APPROVE). Committed via clean `git worktree` at origin/main because the main checkout on Matt's MacBook carried a pre-existing unresolved merge conflict in `ios-app/SymphonyOps/SymphonyOps/ContentView.swift` that must not be touched per the prompt's guardrail._

## BlueBubbles → Cortex Live Webhook Verification (2026-04-24 UTC, Claude Code)
- Prompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md
- Runbook: ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md
- Evidence: ops/verification/20260424-160905-bluebubbles-cortex-live-webhook.md
- Verdict: FAIL-no-webhook
- [FOLLOWUP: bluebubbles-webhook-url-mismatch] — URL shows cortex:8102 (Docker-only hostname); host-side LaunchAgent cannot resolve it. Fix: change to http://127.0.0.1:8102/hooks/bluebubbles then re-run verification.

## BlueBubbles → Cortex Live Webhook Verification — Re-run after URL fix (2026-04-24 UTC, Claude Code)
- Prompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md
- Prior run (FAIL): ops/verification/20260424-160905-bluebubbles-cortex-live-webhook.md
- Evidence: ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md
- Verdict: PASS-webhook-only
- Fix applied: BlueBubbles Webhook URL changed from http://cortex:8102 to http://127.0.0.1:8102/hooks/bluebubbles
- [NOTE: multi-delivery] inbound_count=3 for single send (expected multi-event behavior, unconfirmed)
- [FOLLOWUP: structured-log-visibility] logger.info lines not surfacing in docker logs cortex

### Self-improvement loop — 2026-04-24T17:00:00Z

inbox processed: 4, cards: 3 new + 1 already-processed (0 auto-run / 0 needs-Matt / 0 deferred / 0 external / 3 needs-fetch)

- `20260422T111725Z-imessage-x-com-ihtesham2005-...-card.md` — **already processed** (archive + card existed from prior run; skipped)
- `20260424T163001Z-imessage-x-com-nousresearch-...-card.md` — **needs fetch** — @nousresearch (AI research org); highest-priority fetch in this batch given likely model/technique relevance to Cortex
- `20260424T163001Z-imessage-x-com-openswarm-...-card.md` — **needs fetch** — @openswarm_ (apparent swarm/agent-coordination account); content may be relevant to multi-service orchestration patterns
- `20260424T163001Z-imessage-x-com-jameszmsun-...-card.md` — **needs fetch** — @jameszmsun (unknown account); same iMessage URL pattern, relevance undetermined

Pattern note: three X links arrived on 2026-04-24 via the same iMessage handle (+19705193013), all bare URLs with no body text. This is the fourth consecutive `needs-fetch` card from the iMessage URL lane. Consider adding x_intake auto-routing for iMessage-captured X URLs to close this recurring gap (see ihtesham2005 card for prior analysis).

## X-Intake Reply-Leg — Live Smoke Attempt 2 on Bob (2026-04-24 UTC, Claude Code)
- Runbook: ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md
- Evidence: ops/verification/20260424-165559-x-intake-reply-leg-live-smoke.txt
- Verdict: BLOCKED — Docker daemon restarted during DRY=0 window; Cortex unreachable when webhook arrived
- +18609171850 added to routing JSON (left for retry; remove via config/bluebubbles_routing.json if not needed)
- [FOLLOWUP: x-intake-reply-leg-retry] Re-seed action, flip DRY=0, retry send with Docker stable

### Self-improvement loop — 2026-04-24T17:03:37Z

inbox processed: 0 (idempotent re-run), cards: 0 new (all 4 inbox items already had archive + card from prior run at 17:00Z)

- `20260422T111725Z-imessage-x-com-ihtesham2005-...-card.md` — **already processed** (committed)
- `20260424T163001Z-imessage-x-com-nousresearch-...-card.md` — **already processed** (untracked, uncommitted from 17:00Z run)
- `20260424T163001Z-imessage-x-com-openswarm-...-card.md` — **already processed** (untracked, uncommitted from 17:00Z run)
- `20260424T163001Z-imessage-x-com-jameszmsun-...-card.md` — **already processed** (untracked, uncommitted from 17:00Z run)

### Self-improvement loop — 2026-04-24T17:35:43Z

inbox processed: 4 (all skipped — idempotent re-run), cards: 0 new (0 auto-run / 0 needs-Matt / 0 deferred / 0 external / 0 needs-fetch)

All 4 inbox items already had archive + card from the 17:00–17:03Z run this session; collector confirmed running (3 new 20260424 files visible as untracked in git). No new cards or prompts drafted.

- `20260422T111725Z-imessage-x-com-ihtesham2005-...-card.md` — **already processed** (committed); Status: needs fetch
- `20260424T163001Z-imessage-x-com-nousresearch-...-card.md` — **already processed** (untracked); Status: needs fetch
- `20260424T163001Z-imessage-x-com-openswarm-...-card.md` — **already processed** (untracked); Status: needs fetch
- `20260424T163001Z-imessage-x-com-jameszmsun-...-card.md` — **already processed** (untracked); Status: needs fetch

Verification: ops/verification/self-improve-20260424T170337Z.txt

### Self-improvement loop — 20260424T180711Z

inbox processed: 4 (all skipped — idempotent re-run), cards: 0 new (0 auto-run / 0 needs-Matt / 0 deferred / 0 external / 0 needs-fetch)

All 4 inbox items already had archive + card from earlier runs this session. No new cards or prompts drafted.

- `20260422T111725Z-imessage-x-com-ihtesham2005-...-card.md` — **already processed** (committed); Status: needs fetch
- `20260424T163001Z-imessage-x-com-nousresearch-...-card.md` — **already processed** (untracked); Status: needs fetch
- `20260424T163001Z-imessage-x-com-openswarm-...-card.md` — **already processed** (untracked); Status: needs fetch
- `20260424T163001Z-imessage-x-com-jameszmsun-...-card.md` — **already processed** (untracked); Status: needs fetch

Verification: ops/verification/self-improve-20260424T180711Z.txt

## X-Intake Reply-Leg — Live Smoke Final (2026-04-24 UTC, Claude Code)
- Runbook: ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md
- Evidence: ops/verification/20260424-174246-x-intake-reply-leg-live-smoke.txt
- Verdict: PARTIAL-PASS — listener/dispatch/cortex_remember/send_ack all verified; BlueBubbles send_text hangs (apple-script) or 500 (private-api helper not connected)
- Fixes committed: listener.py bytes decode, ack.py HTTP via CORTEX_URL, routing JSON allowlist
- [FOLLOWUP: bluebubbles-send-method] Messages.app AppleScript access or Private API helper needed to close outbound leg

## Bob Docker Crash Diagnostic — Re-run (2026-04-24 18:04 UTC, Claude Code)
- Evidence: ops/verification/20260424-180456-bob-docker-crash-diagnostic.md
- Classification: B (rsshub 87%, dtools-bridge 78% of 256m) + C (8.67 GB reclaimable) + D (vpn restart loop) + E (Docker Desktop crash during keychain-locked build)
- [FOLLOWUP] Raise rsshub+dtools-bridge mem_limit 256m→512m (APPROVE: compose-memory-limits)
- [FOLLOWUP] docker image prune -a reclaim 8.67 GB (APPROVE: log-rotation)
- [FOLLOWUP] vpn healthcheck investigation

## Docker Memory + VPN Fixes Applied (2026-04-24 UTC, Claude Code)
- rsshub mem_limit 256m → 512m (was 87% of limit, now 41%)
- dtools-bridge mem_limit 256m → 512m (was 78% of limit)
- vpn healthcheck ping -c 1 → ping -c 1 -W 3 (fix race with 10s Docker timeout)
- vpn start_period 30s → 60s
- Ghost container 57cc6585b5bc_dtools-bridge removed
- docker image prune -a reclaimed 432 MB
- [NEEDS_MATT] WireGuard tunnel not established: peer 185.204.1.211:51820 not responding (0 B received). polymarket-bot cannot reach Polymarket API until tunnel is up. Check VPN credentials or provider status.
