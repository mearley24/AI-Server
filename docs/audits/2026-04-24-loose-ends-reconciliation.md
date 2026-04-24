# Loose-Ends Reconciliation — 2026-04-24 (Claude Code, parent-agent pass)

**Date:** 2026-04-24
**Auditor:** Claude Code (autonomous parent-agent pass, docs-only)
**Source question:** "review and clean up the loose ends"
**Scope:** prompts under `.cursor/prompts/`, runbooks under `ops/runbooks/`,
top-level STATUS_REPORT entries, and `[NEEDS_MATT]` inventory — reconcile
each against committed evidence.

> **Scope guardrail.** This audit is a classification + closure-block
> pass only. It does **not** run Bob runtime actions, `launchctl`,
> `docker`, `sudo`, env mutation, external sends, opened ports, secret
> reads, money/trading actions, or destructive changes. It does not
> erase audit history — prior bullets are struck through with
> `~~...~~ ✅` and retained. Historical receipts under
> `ops/verification/*` are not modified.
>
> Dirty harness-owned files (`.claude/**`, `.mcp.json`, `CLAUDE.md`)
> were preserved across this pass.

---

## TL;DR

Six stale `Status: active` prompts and two runbooks were closed with
explicit `<!-- closure: start --> … <!-- closure: end -->` blocks,
each citing the committed evidence already anchored in
`STATUS_REPORT.md` or `ops/verification/`. One top-level STATUS_REPORT
entry (BlueBubbles → Cortex Live Webhook) was annotated as
**superseded** by the PASS-webhook-only re-run at
`ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`.
Three corresponding `[NEEDS_MATT]` bullets for the BlueBubbles webhook
verification were struck through with evidence.

One work item remains genuinely open and is **not** being closed by
this pass: the X-intake reply-leg **live smoke** (outbound BlueBubbles
`send_text` leg), authoritative runbook
`ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
(`Status: PRECHECKS_PASSED`) and follow-up evidence prompt
`.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`
(`Status: active`). No new evidence file has landed since the
prechecks run on 2026-04-24 T09, so the gate remains open.

---

## 1. Reconciled items (closed or annotated this pass)

### 1.1 BlueBubbles webhook leg (fully-live verify)

- **Prompt:** `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`
  → `Status: active` → **`Status: done`** + closure block.
- **Runbook:** `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md`
  → `Status: DONE` header added.
- **Evidence:** `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`
  — Verdict `PASS-webhook-only`. `inbound_count` advanced 0 → 3 after an
  external iMessage send from a distinct phone number; all 3 events
  returned HTTP 200 at `/hooks/bluebubbles`. Events were policy-dropped
  by `allow_owner_only` because the sender is not on
  `config/bluebubbles_routing.json` `inbound.allowed_phones` — which
  proves the webhook leg is live and the allowlist is the gate.
- **Commit trail:** `03dddc34` (FAIL-no-webhook — URL misconfigured) →
  `e610cddb` (PASS-webhook-only — URL fixed from
  `http://cortex:8102/hooks/bluebubbles` (Docker-only hostname) to
  `http://127.0.0.1:8102/hooks/bluebubbles` (host-side loopback,
  correct for the BlueBubbles LaunchAgent)).
- **STATUS_REPORT.md top entry** marked **superseded** and the three
  webhook-related follow-up bullets struck through with ✅ and receipts.
- **Remaining follow-ups (tracked, not gating this prompt):**
  - To reach `PASS-webhook-and-policy`, add a trusted test number to
    `config/bluebubbles_routing.json` `inbound.allowed_phones`.
  - `[FOLLOWUP: structured-log-visibility]` — `bluebubbles_webhook`
    `logger.info` lines not appearing in `docker logs cortex` despite
    `CORTEX_LOG_LEVEL=INFO`. Investigate logging handler configuration
    in `cortex/engine.py:33`.

### 1.2 Bob Docker crash / memory diagnostic

- **Prompt:** `.cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md`
  → `Status: active` → **`Status: done`** + closure block.
- **Runbook:** `ops/runbooks/2026-04-24-bob-docker-crash-diagnostic.md`
  → `Status: active` → **`Status: DONE`**.
- **Evidence:** `ops/verification/20260424-151202-bob-docker-crash-diagnostic.md`
  — Classification: (A) host memory pressure + (C) disk pressure + (E)
  Docker Desktop translocated-path crash + (F) mild watchdog
  false-recovery.
- **Application commit:** `275f2a83` — `APPROVE ALL` executed on Bob
  2026-04-24 09:25 MDT. Changes recorded in STATUS_REPORT.md L39–L57:
  `scripts/bob-watchdog.sh` cooldown 180s → 300s;
  `docker-compose.yml` `x-intake-lab` decommissioned (512m freed);
  Docker Desktop `MemoryMiB` 4096 → 6144; Ollama `KEEP_ALIVE=0`,
  `MAX_LOADED_MODELS=1`; `docker system prune -a` + `docker builder
  prune -a` reclaimed ~11.5 GB.
- **Remaining follow-ups (tracked as `[NEEDS_MATT]` / `[FOLLOWUP]` in
  STATUS_REPORT.md L55–L57; not gating this prompt):**
  - [NEEDS_MATT] Restart Docker Desktop to apply the 6 GB VM setting.
  - [NEEDS_MATT] `sudo setup/install_bob_watchdog.sh --deploy-system` to
    sync 300s cooldown to the system copy.
  - [FOLLOWUP] Move Docker Desktop from the translocated path to
    `/Applications/` (reinstall).

### 1.3 Five-prompt reconciliation cleanup (2026-04-23 series)

Four prompts remained `Status: active` despite the Five-Prompt
Reconciliation table at STATUS_REPORT.md L535–L539 recording each as
"Completed + verified". Closure blocks added, each citing the commit
trail and the verification receipt:

| # | Prompt | Commits | Receipt |
|---|--------|---------|---------|
| 1 | `.cursor/prompts/2026-04-23-cline-bluebubbles-health-plist.md` | `4b7485f` | `ops/verification/20260424-083518-bluebubbles-health-arm.txt` |
| 2 | `.cursor/prompts/2026-04-23-cline-bluebubbles-attachment-bodies.md` | `fe5f778`, `525940d` | `ops/verification/20260423-102015-bluebubbles-attachment-bodies.txt` |
| 3 | `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md` | `716b14a`, `da532f3`, `758b31f`, `bc8ffdf`, `50feea8` | `ops/verification/20260423-173120-cortex-dedup-backfill.json` + `20260423-173840-...json` |
| 5 | `.cursor/prompts/2026-04-23-cline-x-intake-reply-leg-phases-2-6.md` | `6aa2102`, `7bc0f5e`, `cce41c4`, `c0b9d1f`, `15484a3` | `ops/verification/20260423-104458-x-intake-reply-leg-phases-2-6.txt` |

Prompt #4 (`2026-04-23-cline-cortex-embeddings.md`) was already
correctly `Status: done` with closure block — no change this pass.

Runtime-arm runbooks for these prompts were already marked
`Status: DONE` (cortex-dedup, bluebubbles-health). `cortex-embeddings`
runbook remains `Status: [NEEDS_MATT] + [BOB_CLINE_ONLY]` by design.

---

## 2. Open items (evidence still missing — kept open)

### 2.1 X-Intake reply-leg **live smoke** (outbound BlueBubbles `send_text`)

- **Authoritative runbook:** `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
  (`Status: PRECHECKS_PASSED`).
- **Follow-up prompt:** `.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`
  (`Status: active`) — kept active deliberately; no new
  `ops/verification/*reply-leg-evidence*` file has landed since the
  pre-check run at `ops/verification/20260424-090900-x-intake-reply-leg-live-smoke.txt`
  (the pre-check notes explicitly that the live outbound `send_text`
  path was not exercised because of the self-to-self iMessage routing
  quirk — which is now unblocked by the BlueBubbles webhook
  `PASS-webhook-only` above).
- Only one open prompt and one open runbook cover this gate; no
  duplicates were found.

### 2.2 NEEDS_MATT orchestration prompt

- **Prompt:** `.cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md`
  (`Status: active`) — kept active deliberately. The prompt orchestrates
  three gates (cortex-dedup, bluebubbles-health, x-intake reply-leg
  live smoke). The first two are `DONE` on Bob; the third is the open
  item in §2.1 above. Closing the orchestration prompt is a downstream
  effect of closing the reply-leg live smoke, so it is left as-is.

---

## 3. NEEDS_MATT inventory snapshot

`python3 scripts/needs_matt_inventory.py` (this pass):

```
Counts:
  total hits                 : 185 (pre-pass)
  active (open gates)        : 18
  under-specified active     : 18
```

Of the 18 under-specified active markers, three relate to the
BlueBubbles webhook verification and are struck through this pass.
Post-pass, the active count should drop to **15**. A re-run of the
inventory is part of §4 verification.

No **actionable** markers are being deleted. Historical receipts under
`ops/verification/*` are not modified (policy: append-only).

The under-specified metadata on the remaining 15 markers (owner,
opened, review-by, evidence, next) is a known backlog item not
addressed by this pass — the bullets are still interpretable and
actionable, just missing the five structured fields per
`docs/needs-matt-policy.md`. Adding that metadata is a separate task.

---

## 4. Verification (bounded, read-only)

Executed by this pass:

- `git status --short` → only harness-owned dirty paths (`.claude/**`,
  `.mcp.json`, `CLAUDE.md`) + the files this audit is about to edit.
- `git rev-list --left-right --count origin/main...HEAD` → `0 0`
  (in sync at audit start).
- `git log --oneline dc0a6832..HEAD | wc -l` → 15 commits since the
  parent-agent anchor.
- `python3 scripts/needs_matt_inventory.py` — pre-pass count recorded
  at §3; post-pass count captured in the commit receipt.
- `python3 -m py_compile scripts/needs_matt_inventory.py` → clean.
- `grep -RIn "Status:\s*active" .cursor/prompts/` — counts recorded
  before and after closure blocks.
- `grep -RIn "Status:\s*active" ops/runbooks/` — post-pass confirms
  zero (all active-tagged runbooks closed or were never tagged).
- `git diff --stat` — scope-limited to the files named in §1.

No shell-only side-effects, no `docker`, `launchctl`, `sudo`, no env
mutation, no external send.

---

## 5. Exit state + exact next commands

After this pass, the one genuinely open workstream is the X-Intake
reply-leg live smoke. Resumption commands (Bob-only, Matt-gated; this
audit does not run them):

```
# Runbook-driven, supervised, single-shot:
open ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md
# Then Matt (on Bob) flips DRY_RUN and captures evidence via:
open .cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md
```

For the two outstanding Bob-local follow-ups from the Docker
diagnostic (also Matt-gated):

```
# One-time manual action:
open "Docker Desktop" # restart to apply MemoryMiB=6144
sudo setup/install_bob_watchdog.sh --deploy-system   # syncs 300s cooldown
```

---

_Audit authored by Claude Code, 2026-04-24 UTC, parent-agent docs-only
pass. No Bob runtime actions performed._
