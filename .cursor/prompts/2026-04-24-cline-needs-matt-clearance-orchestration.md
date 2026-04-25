# NEEDS_MATT Clearance Orchestration — 2026-04-24

<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must
be zsh-safe: no heredocs, no inline interpreters, no interactive
editors, no long-running watch modes (no tail -f, no --watch, no npm
run dev). Use bounded commands: timeout, --lines N, --since, head/sed
-n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: high
Trigger:   manual
Status:    done
<!-- autonomy: end -->

<!-- closure: start -->
Closed: 2026-04-25 by Claude Code (parent-agent final closure audit).
All three Bob-runtime gates this prompt orchestrated have committed
evidence:
1. Cortex dedup `--apply` — runbook `Status: DONE`; receipts
   `ops/verification/20260423-173120-cortex-dedup-backfill.json` +
   `20260423-173840-cortex-dedup-backfill.json` (`rows_deleted=1`,
   idempotent).
2. BlueBubbles health plist arm — runbook `Status: DONE`; receipt
   `ops/verification/20260424-083518-bluebubbles-health-arm.txt`
   (`run interval=300`, `.err` empty, BlueBubbles 1.9.9 healthy).
3. X-intake reply-leg live smoke — runbook `Status: PARTIAL-PASS`
   (2026-04-24 17:42 UTC); receipt
   `ops/verification/20260424-174246-x-intake-reply-leg-live-smoke.txt`.
   Chain end-to-end through the BlueBubbles API; final outbound
   `send_text` blocked by macOS 26 apple-script hang, tracked as
   `[FOLLOWUP: bluebubbles-send-method]` in STATUS_REPORT.md (NOT a
   `[NEEDS_MATT]` gate — it is a code/compat issue, not a
   real-world Matt decision).
Reconciliation evidence:
- `ops/verification/20260424-085318-needs-matt-clearance-orchestration.txt`
- `ops/verification/20260424-150000-needs-matt-clearance-reconciliation.txt`
- `docs/audits/2026-04-24-loose-ends-reconciliation.md`
- `docs/audits/2026-04-25-final-closure-and-exposure-audit.md`
<!-- closure: end -->

**Title:** NEEDS_MATT Clearance Orchestration — reconcile the three
remaining Bob-runtime gates against committed evidence, arm the
ones that are still open, record receipts, and close the markers.

**Owner:** Matt, on Bob (Mac Mini M4), via Cline. **Not** the
task-runner, self-improvement loop, Computer, or any auto-dispatcher.
This prompt mutates live state on Bob and is gated. The supporting
runbooks under `ops/runbooks/` are the authoritative per-gate
procedures; this prompt orchestrates them and records closure.

**Prerequisite reading (in order):**

1. `/CLAUDE.md`
2. `.clinerules`
3. `ops/AGENT_VERIFICATION_PROTOCOL.md`
4. `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
5. `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md`
6. `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md`
7. `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
8. `STATUS_REPORT.md` — search for `[NEEDS_MATT]` and read the
   enclosing section of each hit.

---

## Goal

Reconcile the current `[NEEDS_MATT]` markers in the repo against
committed evidence, run the per-gate runbooks where they are still
open (and only where the operator has approved each gate in this
session), capture the required verification receipts, update
`STATUS_REPORT.md`, and commit/push. At the end of a successful run,
the three Bob-runtime gates below are each in exactly one of:
`ARMED` (live, evidence captured), `DRY_RUN_ONLY` (dry-run receipt
captured, live flip deferred), or `DEFERRED` (operator declined this
session). No other `[NEEDS_MATT]` markers are modified.

## Non-goals

- Do **not** touch the external-economic `[NEEDS_MATT]` items (Polymarket
  USDC/MATIC funding at `STATUS_REPORT.md` L1045-1046, L1713). They
  remain as-is.
- Do **not** auto-arm the x-intake reply-leg live smoke. Default posture
  is `DRY_RUN_ONLY`. Only perform the live step if Matt explicitly
  types the authorization string in §Safety gates below, and even
  then the recipient is Matt's own number only.
- Do **not** modify any file under `ops/verification/` that existed
  before this run — historical receipts are immutable.
- Do **not** modify files in `.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`, or anything
  listed as harness-owned. Preserve any pre-existing dirty working
  tree.
- Do **not** add `<!-- autonomy: start -->` metadata to anything
  under `ops/runbooks/`.

## Context

Three outstanding Bob-runtime `[NEEDS_MATT]` gates already have
dedicated human-approved runbooks under `ops/runbooks/`:

| Gate | Runbook | Class |
|------|---------|-------|
| Cortex dedup live `--apply` on `brain.db` | `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md` | (b) Bob-runtime; a prior `--apply` already ran (`ops/verification/20260423-173120-cortex-dedup-backfill.json`, `20260423-173840-cortex-dedup-backfill.json` — each `rows_deleted=1`). |
| Arm `com.symphony.bluebubbles-health.plist` | `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md` | (b) Bob-runtime; user-scope `launchctl bootstrap`, no sudo. |
| X-intake reply-leg live smoke | `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md` | (c) external-send; gated behind Matt-only allowlist + DRY_RUN flip + immediate restore. |

Other markers are already closed (strikethrough ✅), out-of-scope
(Polymarket funding), documentation-only (`ops/AGENT_VERIFICATION_PROTOCOL.md`,
`integrations/x_intake/reply_actions/ack.py:13` comment), or live in
historical receipts under `ops/verification/` (audit trail, do not
touch).

---

## Safety gates (hard)

`AUTO_APPROVE = false` for this prompt. Each of the three gates below
requires an explicit operator decision **in this chat turn** before
its runbook runs. Recognized authorizations are the exact strings:

- `ARM: cortex-dedup` — run `ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md`.
- `ARM: bluebubbles-health` — run `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md`.
- `SMOKE: x-intake-reply-leg TO=<matts-own-number>` — run
  `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
  with `ALLOWED_TEST_RECIPIENTS` set to exactly the provided number
  (must be Matt's own — verify against any locally available config
  or ask Matt to confirm once). If the string is any other form,
  decline and mark the gate `DEFERRED`.
- `DRY_RUN: x-intake-reply-leg` — run only the dry-run variant inside
  the x-intake runbook (§"Dry-run-only smoke" — send path never flips
  `CORTEX_REPLY_DRY_RUN=0`).
- `SKIP: <gate-name>` — leave that gate as-is; record as `DEFERRED`
  with reason string.

**Absolute forbids for this prompt** (independent of authorization):

- No `sudo`, no `launchctl bootstrap system/...`, no `launchctl
  bootstrap gui/<id>` against any plist other than
  `com.symphony.bluebubbles-health.plist`.
- No `docker compose down`, no `docker system prune`, no `docker
  volume rm`, no `rm -rf` on `data/`, `~/Library/`, `~/AI-Server/`.
- No edits to `.env`, `.env.example`, secrets files, or any file
  matching `*credentials*` / `*secret*`.
- No network calls outside of `localhost` and the BlueBubbles
  health probe URL already baked into the plist. No posts, sends,
  or messages to any external destination except the one iMessage
  inside the x-intake smoke (and only when explicitly authorized
  above).
- No `git push --force`, no `git reset --hard` on shared refs, no
  branch deletion. Only fast-forward merges and normal pushes to
  `origin/main`.
- No changes to any file under `ops/verification/` older than this
  run's start time.
- No modification of harness-owned paths: `.claude/**`, `.mcp.json`,
  `CLAUDE.md`.

If a runbook asks for any action outside these bounds, stop and
record `DEFERRED — out-of-bounds` for that gate.

---

## Step plan

### Phase 0 — Orient + census

0.1 `git status --short` and `git log --oneline -5`. Confirm clean
working tree (ignoring harness-owned paths). If dirty, stash
harness-owned edits with a named stash; do not discard.

0.2 `git fetch origin && git status -b --short` to confirm
up-to-date with `origin/main`.

0.3 Census: `grep -RIn --exclude-dir=.git -E "\[NEEDS_MATT\]" | wc -l`
(informational total), and
`grep -RIn --exclude-dir=.git --exclude-dir=ops/verification -E "\[NEEDS_MATT\]"`
(actionable surface). Write both counts into the final receipt.

0.4 Verify the three runbook paths exist and each header contains
both `[NEEDS_MATT]` and `[BOB_CLINE_ONLY]`:

```
ls ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md \
   ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md \
   ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md
grep -n "\[NEEDS_MATT\]" ops/runbooks/2026-04-23-*.md
grep -n "\[BOB_CLINE_ONLY\]" ops/runbooks/2026-04-23-*.md
```

### Phase 1 — Per-gate reconciliation (evidence first, action second)

For each of the three gates, in this order: (a) cortex-dedup,
(b) bluebubbles-health, (c) x-intake-reply-leg. For each gate:

1.1 **Read prior evidence first.** Check `ops/verification/` for any
receipts keyed to the gate. Record commit hashes for each. For
cortex-dedup specifically, confirm the two prior `rows_deleted=1`
receipts exist (`20260423-173120`, `20260423-173840`).

1.2 **Check live state** with read-only probes only:

- cortex-dedup: inside `brain.db`, report row counts and the
  current dedupe-key coverage via the runbook's pre-check query
  (read-only `SELECT`). If coverage is already 100% and no
  duplicates exist, mark `ARMED (no-op, idempotent)` and skip 1.3.
- bluebubbles-health: `launchctl print gui/$(id -u)/com.symphony.bluebubbles-health` and
  `ls ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist`.
  If loaded and the probe log shows successful ticks in the last
  10 minutes, mark `ARMED (already live)` and skip 1.3.
- x-intake-reply-leg: `grep -E '^(CORTEX_REPLY_DRY_RUN|ALLOWED_TEST_RECIPIENTS)=' .env`
  (read-only). If `CORTEX_REPLY_DRY_RUN=1` and `ALLOWED_TEST_RECIPIENTS`
  is empty, posture is correct-safe; only advance to 1.3 under
  explicit `SMOKE:` or `DRY_RUN:` authorization.

1.3 **Run the runbook** only if the operator provided the
matching authorization string. Follow the runbook verbatim;
do not improvise. Capture the runbook's required receipt under
`ops/verification/<YYYYMMDD-HHMMSS>-<gate>-clearance.txt` (or
`.json` when the runbook specifies JSON). Record the receipt path.

1.4 **Record outcome** in this prompt's final receipt as one of:
`ARMED` / `DRY_RUN_ONLY` / `DEFERRED (reason)`.

### Phase 2 — STATUS_REPORT updates

2.1 For each gate that transitioned to `ARMED` or `DRY_RUN_ONLY`,
append a dated entry under the top "NEEDS_MATT Clearance" section
of `STATUS_REPORT.md` with: gate name, outcome, receipt path,
and commit hash (leave commit-hash placeholder until after the
commit, then fix up in a single follow-up commit or inline once
known). Do **not** remove the original `[NEEDS_MATT]` bullets —
strike them through and append ` ✅` only when outcome is `ARMED`
(per the tagging conventions in `STATUS_REPORT.md` header).

2.2 Leave `DEFERRED` gates untouched in place; add one paragraph
explaining what was deferred and why under the same top section.

2.3 Do **not** edit any `[NEEDS_MATT]` bullet outside the three
tracked gates. Specifically leave L1045, L1046, L1713 (Polymarket
funding) exactly as they are.

### Phase 3 — Verification receipt

Write `ops/verification/<YYYYMMDD-HHMMSS>-needs-matt-clearance-orchestration.txt`
containing:

- Start/end timestamps (local, MDT).
- Total `[NEEDS_MATT]` count (`grep -RIn ... | wc -l`) and
  actionable-surface count (excluding `ops/verification/`).
- Per-gate row: runbook path, prior-evidence commits, live-state
  probe output (trimmed), authorization string received, outcome,
  receipt path, and the new commit hash.
- Explicit "no runtime actions outside the authorized runbooks"
  attestation.
- A final `git diff --stat HEAD~1..HEAD` snippet (captured after
  the commit — append in a second write if needed).

### Phase 3.5 — Post-runbook hygiene check (mandatory)

After the per-gate runbooks complete and **before** the Phase-4
commit, run the inventory checker and close any stale markers by
evidence. This prevents the exact confusion class (`[NEEDS_MATT] is
causing a lot of issues`) that motivated this orchestration.

3.5.1 `python3 scripts/needs_matt_inventory.py --write ops/verification/<YYYYMMDD-HHMMSS>-needs-matt-inventory-post-orchestration.txt`

3.5.2 Read the receipt. For each gate that this pass transitioned to
`ARMED`, verify the corresponding STATUS_REPORT bullet is now
struck-through with ✅ and an evidence path. If the inventory still
reports it as active, the Phase-2 strikethrough was missed — fix
before commit.

3.5.3 For any markers the checker reports as **stale** or
**under-specified** that are *not* in scope for this orchestration
(i.e. the Polymarket items or unrelated historical entries), do
**not** modify them here. Record their count in the Phase-3
verification receipt and point to
`.cursor/prompts/needs-matt-hygiene-check.md` as the next pass.

3.5.4 Policy reference: `docs/needs-matt-policy.md`. The checker is
advisory — exit code is always 0; this step is a sanity gate on the
diff, not a blocker.

### Phase 4 — Commit + push

4.1 `git add` only:

- `.cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md`
  (this file)
- the new verification receipt under `ops/verification/`
- the Phase-3.5 inventory receipt under `ops/verification/`
- `STATUS_REPORT.md` (the Phase-2 edits)
- any gate-specific receipt files that the runbooks wrote

Do **not** stage harness-owned dirty files.

4.2 Commit message shape:

```
ops(needs_matt): orchestration pass — <ARMED|DRY_RUN_ONLY|DEFERRED>×<N>

- cortex-dedup:        <outcome>  <receipt-path>
- bluebubbles-health:  <outcome>  <receipt-path>
- x-intake-reply-leg:  <outcome>  <receipt-path>

No external sends, no sudo, no env mutation outside authorized runbook.
Historical ops/verification/* receipts untouched.
```

4.3 `git push origin main` (fast-forward only; no `--force`).

---

## Required tests / checks (bounded, before commit)

Run each and paste the last line into the verification receipt:

```
grep -RIn --exclude-dir=.git -E "\[NEEDS_MATT\]" | wc -l
grep -RIn --exclude-dir=.git --exclude-dir=ops/verification -E "\[NEEDS_MATT\]" | wc -l
ls ops/runbooks/2026-04-23-*.md
ls .cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md
head -20 .cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md
grep -n "^Status:" .cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md
python3 scripts/needs_matt_inventory.py | head -20
git diff --stat HEAD
```

Expected:

- Both `grep | wc -l` numbers drop by at least the number of
  `ARMED` gates.
- All three runbook paths listed.
- This prompt's header shows `Status:    active` (inside the
  `<!-- autonomy: start -->` block).
- `git diff --stat HEAD` lists only the files named in Phase 4.1.

---

## Per-marker action rules (explicit)

- **Historical `[NEEDS_MATT]` hits in `ops/verification/*`:** never
  modify. These are frozen receipts.
- **`STATUS_REPORT.md` L1045, L1046, L1713 (Polymarket funding):**
  never modify in this pass.
- **`integrations/x_intake/reply_actions/ack.py:13`:** it is an
  explanatory code comment about the gated live-flip. Leave as-is.
- **`ops/AGENT_VERIFICATION_PROTOCOL.md`, `ops/AUTONOMOUS_EXECUTION_PIPELINE.md`,
  `docs/audits/*`, `docs/network-monitoring-v2-prompt.md`,
  `.cursor/prompts/full-system-sweep-and-audit.md`,
  `.cursor/prompts/2026-04-23-cline-*`:** all documentation/history
  references to `[NEEDS_MATT]` — do not modify.
- **`STATUS_REPORT.md` L592/593/626 (network-guard / dropout-watch):**
  already have ✅ strikethrough immediately below. Do not modify.
- **`STATUS_REPORT.md` L778/838/911 (watchdog deploy):** the final
  form is already ✅. Do not modify.
- **`STATUS_REPORT.md` L665 (sudoers/network-guard separate gate):**
  not in scope this pass. Leave as-is.

---

## Stop conditions

Stop immediately and mark the gate `DEFERRED (reason)` if any of:

- The runbook's prechecks fail.
- Live-state probe shows an unexpected posture (e.g.
  `CORTEX_REPLY_DRY_RUN` already `0`, or `ALLOWED_TEST_RECIPIENTS`
  already populated with an unknown value).
- Any command errors out or returns a non-zero code outside the
  runbook's tolerated set.
- Any authorization string is ambiguous or malformed.
- Any forbid in §Safety gates would have to be relaxed to proceed.
- The tree becomes dirty in harness-owned paths mid-run — back
  out, do not overwrite.

If >1 gate defers, still write the verification receipt and commit;
record the deferrals and exit cleanly. Do not retry silently.

---

## Final report (what the operator sees at the end)

- One-line summary: `outcomes: cortex-dedup=<x>, bluebubbles-health=<x>, x-intake-reply-leg=<x>`.
- List of files changed.
- Commit hash and push confirmation line.
- Post-run `[NEEDS_MATT]` counts (total and actionable-surface).
- Links (paths) to the three per-gate receipts and this prompt's
  orchestration receipt.
- Any gate marked `DEFERRED` with the reason and the exact runbook
  path to resume with.
