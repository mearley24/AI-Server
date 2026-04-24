# X-Intake Reply-Leg Evidence Capture — 2026-04-24

<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must
be zsh-safe: no heredocs, no inline interpreters, no interactive
editors, no long-running watch modes (no tail -f, no --watch, no npm
run dev). Use bounded commands: timeout, --lines N, --since, head/sed
-n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: high
Trigger:   manual
Status:    active
<!-- autonomy: end -->

**Title:** X-Intake Reply-Leg — Evidence Capture. Run the
runbook-approved dry-run-only variant by default; optionally run the
supervised Matt-only live smoke under explicit authorization.

**Owner:** Matt, on Bob (Mac Mini M4), via Cline. **Not** the
task-runner, self-improvement loop, Computer, or any auto-dispatcher.

**Authoritative runbook:** `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
(`Status: [NEEDS_MATT]` + `[BOB_CLINE_ONLY]` + `[EXTERNAL_SEND]`).
This prompt **does not** duplicate the runbook — it orchestrates it
and captures a verification receipt, so the open `[NEEDS_MATT]`
bullets at `STATUS_REPORT.md` L355 + L374 can be closed with evidence.

**Prerequisite reading (in order):**

1. `/CLAUDE.md`
2. `.clinerules`
3. `ops/AGENT_VERIFICATION_PROTOCOL.md`
4. `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
   — all sections including the Appendix "Safer alternative
   (dry-run-only smoke)".
5. `STATUS_REPORT.md` — the NEEDS_MATT Clearance Reconciliation
   entry dated 2026-04-24 UTC.

---

## Why this prompt exists

The 2026-04-23 clearance runbooks for cortex-dedup and
bluebubbles-health already have committed evidence (runbook `Status:
DONE`; receipts under `ops/verification/`). The x-intake reply-leg
runbook does **not** — no receipt exists at
`ops/verification/*x-intake-reply-leg-live-smoke*` as of the
reconciliation pass. The runbook is correctly gated behind a Matt-only
allowlist + supervised DRY_RUN flip; nothing in the repo proves it has
run end-to-end.

This prompt produces the missing evidence, with the safer `dry-run-only`
variant as the default posture. The full live smoke remains
`[NEEDS_MATT]` and requires an explicit authorization string.

---

## Safety gates (hard)

`AUTO_APPROVE = false`. Accepted authorization strings, typed by Matt
in chat before any step that mutates state:

- `DRY_RUN: x-intake-reply-leg` — run the runbook's Appendix dry-run
  variant only. `CORTEX_REPLY_DRY_RUN` stays `1` throughout. No
  outbound BlueBubbles `send_text` call is permitted. This is the
  **default** posture if no authorization string is provided.
- `SMOKE: x-intake-reply-leg TO=<matts-own-number>` — run the full
  live smoke per the runbook's main sequence. `TO=` must be Matt's
  own iMessage handle in E.164 (e.g. `TO=+19705193013`). Any other
  form → decline, leave posture as-is, record `DEFERRED`.
- `SKIP: x-intake-reply-leg` — record `DEFERRED (operator skipped)`,
  commit the receipt-only row, exit.

**Absolute forbids for this prompt** (independent of authorization):

- No `sudo`, no `launchctl bootstrap`, no changes to `~/Library/`.
- No `docker compose down`, no `docker system prune`, no `docker
  volume rm`, no `rm -rf` on `data/`.
- No edits to `.env`, `.env.example`, secrets files, or any file
  matching `*credentials*` / `*secret*` — `scripts/set-env.sh` is the
  only accepted helper, and only under `SMOKE:` authorization (and
  only to set `ALLOWED_TEST_RECIPIENTS` and `CORTEX_REPLY_DRY_RUN`).
- No network calls outside of `localhost` and — only under `SMOKE:`
  authorization — the single BlueBubbles `send_text` baked into the
  runbook sequence. Zero sends to any recipient other than
  `ALLOWED_TEST_RECIPIENTS`.
- No `git push --force`, no `git reset --hard` on shared refs.
- No edits to any file under `ops/verification/` older than this run.
- No modification of harness-owned paths: `.claude/**`, `.mcp.json`,
  `CLAUDE.md`.
- No autonomy metadata added to anything under `ops/runbooks/`.

If the runbook would require any action outside these bounds, stop
and record `DEFERRED — out-of-bounds`.

---

## Step plan

### Phase 0 — Orient

0.1 `git status --short` (expect clean ignoring harness-owned),
`git log --oneline -5`, `git rev-parse HEAD`.
0.2 `grep -n "\[NEEDS_MATT\]" STATUS_REPORT.md | head -20` —
confirm L355 + L374 still show the x-intake bullets as open.
0.3 Read-only probe of x-intake state (no mutation):
```
docker ps --format '{{.Names}} {{.Status}}' | grep -E '^x-intake '
docker exec x-intake sh -c 'echo "DRY=$CORTEX_REPLY_DRY_RUN | ALLOW=$ALLOWED_TEST_RECIPIENTS"'
grep -E '^(CORTEX_REPLY_DRY_RUN|ALLOWED_TEST_RECIPIENTS)=' .env || echo "flags absent from .env"
```
Expected: `DRY=1`, `ALLOW=` empty. **Stop** if `DRY=0` already —
that is unexpected posture.

### Phase 1 — Posture selection

1.1 If operator typed `DRY_RUN: x-intake-reply-leg` (or no
authorization — this is the default): follow Phase 2A.
1.2 If operator typed `SMOKE: x-intake-reply-leg TO=<number>`:
follow Phase 2B. Parse `TO=` and confirm it is E.164; if not, decline.
1.3 If operator typed `SKIP: x-intake-reply-leg`: write the
receipt-only row in Phase 3 and commit.

### Phase 2A — Dry-run-only evidence capture

Follow the runbook's Appendix exactly:

- `CORTEX_REPLY_DRY_RUN` stays `1`. Do **not** run `scripts/set-env.sh`.
- Seed a test action via the runbook's precheck-6 inline Python call
  (bounded, no heredocs — use `docker exec x-intake python3 -c "..."`).
  `thread_guid` = Matt's own thread GUID (operator supplies it in
  chat; do not hard-code).
- Matt sends `reply 1` from his own iPhone.
- Inspect `reply_acks.ndjson` and Cortex `memories` for the expected
  dry-run stub + new memory row.
- No `send_text` call should appear in `docker logs`.

This exercises every moving part **except** the real outbound
BlueBubbles leg.

### Phase 2B — Supervised live smoke (SMOKE: authorization only)

Follow the runbook's main "Ordered arm sequence" verbatim, steps 1–7.
Hard constraints:

- `ALLOWED_TEST_RECIPIENTS` is set to exactly the `TO=` value from the
  authorization string and nothing else.
- The DRY=0 window must be ≤ 5 minutes; step 6 restores `DRY=1` +
  empty allowlist immediately after evidence capture.
- A single message, prefixed `[bob-reply-test]`, to Matt's own
  number only.
- Step 7 (the post-restore allowlist refusal check) is mandatory.

Abort + run the runbook's emergency rollback one-liner at any sign
of trouble.

### Phase 3 — Verification receipt

Write `ops/verification/<YYYYMMDD-HHMMSS>-x-intake-reply-leg-evidence-capture.txt`
containing:

- Start/end timestamps (local, MDT).
- `git rev-parse HEAD`.
- Posture selected (`DRY_RUN_ONLY` / `LIVE_SMOKE` / `DEFERRED`).
- Authorization string received (redact `TO=` digits if desired, but
  record the posture verbatim).
- Pre-flip `.env` flag state.
- Seeded `action_id`.
- For `DRY_RUN_ONLY`: `reply_acks.ndjson` tail showing the dry-run
  stub; Cortex `SELECT` result showing the new memory row; explicit
  attestation `send_text not exercised — dry-run only`.
- For `LIVE_SMOKE`: full runbook §"Verification receipt requirements"
  checklist (pre/post flag state, listener+dispatcher+send_ack+send_text
  log excerpt, ndjson tail, Cortex row, timestamps of the DRY=0 window,
  post-restore refusal check output).
- Explicit attestation: "No send to any recipient other than the
  authorized Matt-only allowlist occurred in this run."

### Phase 4 — STATUS_REPORT update (only on success)

On successful `LIVE_SMOKE` (or `DRY_RUN_ONLY` if operator is
accepting dry-run-only as closure evidence):

- Strike through L355 + L374 bullets in `STATUS_REPORT.md` with
  `~~...~~ ✅` and append the receipt path + outcome.
- Add a dated STATUS_REPORT entry named
  `## X-Intake Reply-Leg — Evidence Captured on Bob (<YYYY-MM-DD> <HH:MM TZ>, Matt)`.
- On `DRY_RUN_ONLY` closure, the entry must explicitly note the
  outbound BlueBubbles leg was **not** exercised and whether that
  was accepted as sufficient.

On `DEFERRED`: leave the bullets as-is; add a one-paragraph note
under the existing "NEEDS_MATT Clearance Reconciliation" entry
explaining why this pass deferred.

### Phase 5 — Commit + push

5.1 `git add` only:

- `.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`
  (this file)
- the new verification receipt under `ops/verification/`
- `STATUS_REPORT.md` (Phase-4 edits, if any)

Do **not** stage harness-owned dirty files.

5.2 Commit message shape:

```
ops(x-intake): reply-leg evidence capture — <DRY_RUN_ONLY|LIVE_SMOKE|DEFERRED>

Receipt: ops/verification/<stamp>-x-intake-reply-leg-evidence-capture.txt
No sends outside the authorized allowlist. No env mutation beyond the
scripts/set-env.sh flips mandated by the runbook (and restored within
the same session).
```

5.3 `git push origin main` (fast-forward only; no `--force`).

---

## Required checks (bounded, before commit)

```
grep -RIn --exclude-dir=.git --exclude-dir=ops/verification -E "\[NEEDS_MATT\]" STATUS_REPORT.md | wc -l
python3 scripts/needs_matt_inventory.py | head -30
docker exec x-intake sh -c 'echo "DRY=$CORTEX_REPLY_DRY_RUN | ALLOW=$ALLOWED_TEST_RECIPIENTS"'
ls ops/verification/ | grep x-intake-reply-leg-evidence-capture | tail -1
git diff --stat HEAD
```

Expected on success:

- Post-run `DRY=1`, `ALLOW=` empty (regardless of posture).
- Exactly one new receipt under `ops/verification/`.
- `git diff --stat HEAD` lists only the files named in Phase 5.1.

---

## Stop conditions

Stop immediately and mark `DEFERRED (reason)` if any of:

- Pre-check shows `DRY=0` already, or non-empty `ALLOWED_TEST_RECIPIENTS`.
- `HANDLER_REGISTRY` doesn't match the expected three handlers.
- BlueBubbles server reports unhealthy on the runbook's status ping.
- `TO=<number>` in the `SMOKE:` authorization is not Matt's own handle
  (ambiguous → decline).
- Any command errors out outside the runbook's tolerated set.
- Any forbid in §Safety gates would have to be relaxed.
- Harness-owned paths become dirty mid-run — back out, do not overwrite.

---

## Final report (what the operator sees at the end)

- One-line summary: `x-intake-reply-leg: outcome=<DRY_RUN_ONLY|LIVE_SMOKE|DEFERRED>`.
- Receipt path.
- Commit hash + push confirmation.
- Post-run `[NEEDS_MATT]` counts (total and actionable-surface) from
  `python3 scripts/needs_matt_inventory.py`.
- If `DEFERRED`: the exact reason and the runbook path to resume with.
