# NEEDS_MATT Hygiene Check

<!-- CLAUDE.md preamble: Read /CLAUDE.md first. zsh-safe commands only:
no heredocs, no inline interpreters, no interactive editors, no
long-running watch modes. Use bounded commands: timeout, head/sed -n
ranges, --lines N. -->

<!-- autonomy: start -->
Category: docs
Risk tier: low
Trigger:   manual
Status:    active
<!-- autonomy: end -->

**Title:** Run `scripts/needs_matt_inventory.py`, close stale
`[NEEDS_MATT]` markers by evidence, and add missing metadata to any
under-specified active markers.

**Owner:** any coding agent or human operator. Safe to run in any
environment (does not touch Bob runtime, no sudo, no external surface).

**Purpose:** prevent `[NEEDS_MATT]` markers from accumulating as stale
or under-specified noise. This is the periodic complement to
`.cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md`.
The clearance prompt arms live gates on Bob; this prompt keeps the
repo-side surface clean.

**Prerequisite reading:**

1. `/CLAUDE.md`
2. `docs/needs-matt-policy.md` (authoritative metadata + lifecycle)
3. `STATUS_REPORT.md` — tagging conventions at the top.

## Step plan

### Phase 0 — Inventory

0.1 `python3 scripts/needs_matt_inventory.py > /tmp/needs_matt_inventory.txt`

0.2 Note the counts: total, active, stale, under-specified. If
`stale == 0` and `under_specified == 0`, stop — nothing to do.

0.3 `python3 scripts/needs_matt_inventory.py --all > /tmp/needs_matt_inventory_full.txt`
for the per-hit classification.

### Phase 1 — Close any stale markers whose evidence already exists

For each stale active marker:

1.1 Search `ops/verification/` for receipts that match the gate
(`grep -l <gate-slug> ops/verification/`). Also check
`git log --oneline -- STATUS_REPORT.md | head -20` for recent
closure commits.

1.2 If a closing receipt exists, wrap the bullet in `~~...~~`,
append ` ✅ <ISO date> — <one-line outcome>. Evidence:
<path>.` per `docs/needs-matt-policy.md` closure rules. Do **not**
delete.

1.3 If no closing evidence exists and the gate is genuinely still
open, extend `Review-by:` by a bounded amount (at most 14 days)
with a one-line reason appended to the bullet.

### Phase 2 — Add metadata to under-specified active markers

For each under-specified active marker:

2.1 Determine `Owner` (always `Matt` unless delegated), `Opened`
(use `git blame` on the bullet line to recover the date — round to
the commit's ISO date), `Review-by` (default `Opened + 14 days`),
`Evidence` (path to the most specific receipt or runbook;
`pending` if none yet), and `Next` (authorization string or
runbook path).

2.2 Insert the metadata block directly below the bullet in the
canonical form from `docs/needs-matt-policy.md`.

### Phase 3 — Re-inventory + receipt

3.1 `python3 scripts/needs_matt_inventory.py --write ops/verification/<YYYYMMDD-HHMMSS>-needs-matt-hygiene.txt`.

3.2 Verify `stale == 0` and `under_specified == 0` in the new
receipt. If not, record what remains and why in the receipt.

### Phase 4 — Commit + push

4.1 `git add STATUS_REPORT.md ops/verification/<stamp>-needs-matt-hygiene.txt`
plus any runbook files touched.

4.2 Commit message shape:

```
docs(needs_matt): hygiene pass — closed <N>, metadata <M>

- closed:   <gate-slug> (evidence: <path>)
- metadata: <gate-slug> × <M> (under-specified -> canonical form)
```

4.3 `git push origin main` (fast-forward only).

## Safety / forbids

- No runtime actions (no docker, no launchctl, no sudo, no env
  mutation, no external sends).
- No edits to files under `ops/verification/` older than this run.
- No edits to `.claude/**`, `.mcp.json`, `CLAUDE.md`.
- Never delete an active `[NEEDS_MATT]` bullet — close or reclassify.
- Do not touch Polymarket funding markers unless Matt has explicitly
  confirmed the wallet is funded.

## Expected outcome

- `scripts/needs_matt_inventory.py` reports `stale == 0` and
  `under_specified == 0`.
- A new `ops/verification/<stamp>-needs-matt-hygiene.txt` records the
  before/after counts and the closures made.
- No runtime state on Bob is changed by this prompt.
