# Runbook — Remove decommissioned x-intake-lab from docker-compose.yml

Status: DONE (applied 2026-04-24 18:39 UTC by Matt; receipt `ops/verification/20260424-183925-x-intake-lab-removal/`)
Created: 2026-04-24 (UTC), Claude Code (parent-agent docs-only pass)
Closed: 2026-04-25 by Claude Code (parent-agent final closure audit).
Paired prompt: `.cursor/prompts/2026-04-24-cline-x-intake-lab-compose-removal.md` (Status: done)
Parent evidence: `ops/verification/20260424-182340-port-api-surface-audit/classification.md`
Final audit: `docs/audits/2026-04-25-final-closure-and-exposure-audit.md`

## Why this runbook exists

The 2026-04-24 port/API surface audit confirmed x-intake-lab (port 8103) is
present in `docker-compose.yml` but the container is not running. The service
was decommissioned earlier (STATUS_REPORT L133) and the 512m reservation
already freed. Keeping the compose service block and the port 8103 row in
`PORTS.md` is a drift risk: future compose operations may spin it back up and
the port registry no longer matches reality.

## Scope

- Remove `x-intake-lab:` service from `docker-compose.yml`
- Remove `x-intake-lab-data:` named volume from `docker-compose.yml`
- Move port 8103 row from "Active Services" to "Removed Services" in `PORTS.md`
- Emit receipt under `ops/verification/${STAMP}-x-intake-lab-removal/`
- Append closure block to STATUS_REPORT Port & API Surface Audit section

## Out of scope

- Removing the stopped container itself (`docker rm`) — separate approval
- Deleting the data volume (`docker volume rm`) — separate approval
- Any other compose service changes
- Running `docker compose up` or `docker compose down`

## Operator steps

1. `cd ~/Documents/AI-Server && git pull --ff-only`
2. Open `.cursor/prompts/2026-04-24-cline-x-intake-lab-compose-removal.md` and
   paste into Cline (ACT MODE).
3. Cline runs the six prechecks; if any fail, STOP and surface the block.
4. Cline prints "READY TO APPLY" with the exact diff. Operator reviews.
5. Operator types `APPROVE APPLY` or `CANCEL`.
6. On APPROVE: Cline edits both files, writes receipt, commits, pushes.

## Exit criteria

- `docker-compose.yml` no longer contains `x-intake-lab:` or
  `x-intake-lab-data:`.
- `docker compose config` succeeds post-edit (file still parses).
- `PORTS.md` shows port 8103 in "Removed Services" only.
- `ops/verification/${STAMP}-x-intake-lab-removal/` receipt exists with
  before/after/diff/commit-hash.
- STATUS_REPORT has the strikethrough-✅ closure line.
- Push succeeded.

## Rollback

- `git revert <commit-hash>` then `git push origin main`.
  The service was already not running; revert restores only the compose
  declaration. No runtime state needs reconstruction.

## Closure (to append verbatim to STATUS_REPORT after apply)

```
- ~~[FOLLOWUP] Remove x-intake-lab from docker-compose.yml (port 8103, not running)~~ ✅
  Removed in commit <HASH> on 2026-04-24. Receipt:
  ops/verification/${STAMP}-x-intake-lab-removal/
```
