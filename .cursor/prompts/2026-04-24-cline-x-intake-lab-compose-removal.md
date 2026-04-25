# Cline Prompt — Remove decommissioned x-intake-lab from docker-compose.yml

Status: done
Owner: Cline (ACT MODE on Bob)
Created: 2026-04-24 (UTC)
Closed: 2026-04-25 by Claude Code (parent-agent final closure audit).
Closure evidence:
- Receipt: `ops/verification/20260424-183925-x-intake-lab-removal/`
  (README.md, before.txt, diff.patch, compose-config.txt — APPROVE APPLY by Matt)
- `docker-compose.yml`: x-intake-lab service block + named volume removed; `docker compose config --services` returns 18 services with no x-intake-lab.
- `PORTS.md`: row 8103 moved to "Removed Services" (2026-04-24); footnote corrected.
- STATUS_REPORT.md: closure line appended in same commit window.
Final audit: `docs/audits/2026-04-25-final-closure-and-exposure-audit.md`.
Parent prompt: `.cursor/prompts/2026-04-24-cline-full-port-api-surface-audit.md` (Status: done)
Parent evidence: `ops/verification/20260424-182340-port-api-surface-audit/classification.md`
  — Finding #4: "x-intake-lab (port 8103) still defined in docker-compose.yml but not running"
Paired runbook: `ops/runbooks/2026-04-24-x-intake-lab-compose-removal.md` (Status: DONE)

## Why this prompt exists

The Port & API Surface Audit (2026-04-24 18:23 UTC) confirmed:
- Port 8103 (x-intake-lab) is listed in `PORTS.md` but the container is **not
  running** on Bob.
- The service remains declared in `docker-compose.yml` (lines ~558, 560, 564,
  580, 733 per the on-disk copy used during audit).
- `STATUS_REPORT.md` L133 already states: "docker-compose.yml — x-intake-lab
  **decommissioned** (512m freed, container stopped)".

Compose still carries the service block and a named volume
(`x-intake-lab-data`). Removing it is a docs+compose hygiene cleanup that
shrinks Bob's compose footprint and removes a stale port allocation from
`PORTS.md`. No running service is affected; the container is already stopped.

## Scope

- Edit `docker-compose.yml` to delete the `x-intake-lab:` service block **and**
  the `x-intake-lab-data:` named-volume entry.
- Remove the port 8103 / x-intake-lab row from `PORTS.md` and move it to the
  "Removed Services" table with today's date.
- Commit on `main` with message `ops(compose): remove decommissioned
  x-intake-lab service — port 8103`.
- Emit verification receipt at `ops/verification/${STAMP}-x-intake-lab-removal/`.
- Append a closure line to `STATUS_REPORT.md` under the Port & API Surface
  Audit section.

## Prechecks (must PASS before any edit)

1. `git fetch --all --prune && git pull --ff-only` on `main`. No local diffs on
   `docker-compose.yml`, `PORTS.md`, or `STATUS_REPORT.md` before starting.
2. `docker ps --format '{{.Names}}'` — confirm `x-intake-lab` is **not** in
   the list.
3. `docker ps -a --filter name=x-intake-lab --format '{{.Names}}\t{{.Status}}'`
   — if a stopped container exists, capture the line in the receipt; do NOT
   remove it in this prompt (compose-down/rm is a separate approval).
4. `docker volume ls --format '{{.Name}}'` — record whether
   `ai-server-aa987033_x-intake-lab-data` (or the equivalent project-prefixed
   volume) exists. If it exists and has data, STOP and open a follow-up
   prompt for volume disposition before proceeding. If absent, continue.
5. `grep -n "8103\\|x-intake-lab" docker-compose.yml PORTS.md` — capture the
   exact line numbers into the receipt for audit trail.
6. No other running service references `x-intake-lab` as `depends_on:`,
   `links:`, or environment. Run `grep -n "x-intake-lab" docker-compose.yml`
   and confirm the only matches are inside the service block itself and the
   volume list. If ANY other match: STOP.

## Approval gate

After prechecks pass, print a "READY TO APPLY" block listing:
- The exact `docker-compose.yml` hunk to remove (service + volume).
- The exact `PORTS.md` hunk: one row removed from Active, one row added to
  Removed Services (`2026-04-24`, reason
  `Decommissioned — container not running, port freed`).
- The STATUS_REPORT closure block to append.

WAIT for the operator to type `APPROVE APPLY`. Do not edit files before
that token is received. If the operator types anything else, STOP.

## Apply

On `APPROVE APPLY`:
1. Edit `docker-compose.yml` — remove the `x-intake-lab:` service block and
   the `x-intake-lab-data:` volume entry. Run `docker compose config` to
   confirm the file still parses (no mutation — `config` is read-only).
2. Edit `PORTS.md` — move the 8103 row to "Removed Services".
3. Write the receipt under `ops/verification/${STAMP}-x-intake-lab-removal/`:
   - `before.txt` — precheck outputs
   - `diff.patch` — `git diff` of the two files
   - `compose-config.txt` — `docker compose config` output after the edit
   - `README.md` — summary + commit hash
4. Append STATUS_REPORT closure block (see Runbook §Closure).
5. `git add docker-compose.yml PORTS.md STATUS_REPORT.md
   ops/verification/${STAMP}-x-intake-lab-removal/` and commit with the
   message above.
6. `git push origin main`.

## Rollback

If anything fails or the operator wants to undo:
- `git revert HEAD` on the commit from step 5.
- `git push origin main`.
  The service was not running; there is nothing to restart. If the
  volume was kept, it is still intact.

## Hard "do-not" list (enforced)

- No `docker compose down` / `docker compose rm` / `docker volume rm`.
- No `launchctl`, `sudo`, firewall, env, or secret edits.
- No restart of any running container.
- No changes to any service other than `x-intake-lab`.
- No external sends or trading actions.
- Do not remove the stopped container or the data volume in this prompt —
  those are separate approvals.

## Verification receipt (must be emitted)

`ops/verification/${STAMP}-x-intake-lab-removal/README.md` must include:
- UTC timestamp, operator, host
- Precheck outputs (steps 1–6)
- Diff applied
- Post-edit `docker compose config` confirmation
- Commit hash + push confirmation
- Closure line mirrored into STATUS_REPORT

## STATUS_REPORT update (mandatory)

Append under the existing `## Port & API Surface Audit` section:

```
- ~~[FOLLOWUP] Remove x-intake-lab from docker-compose.yml (port 8103, not running)~~ ✅
  Removed in commit <HASH> on 2026-04-24. Receipt:
  ops/verification/${STAMP}-x-intake-lab-removal/
```
