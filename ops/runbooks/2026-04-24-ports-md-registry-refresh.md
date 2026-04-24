# Runbook — PORTS.md registry refresh (docs-only)

Status: ARMED (awaiting Bob operator)
Created: 2026-04-24 (UTC), Claude Code (parent-agent docs-only pass)
Paired prompt: `.cursor/prompts/2026-04-24-cline-ports-md-registry-refresh.md`
Parent evidence: `ops/verification/20260424-182340-port-api-surface-audit/classification.md`

## Why this runbook exists

PORTS.md is 10 days stale (last updated 2026-04-14) and incorrect in two
ways: it claims loopback-only for all ports (4+ services actually bind
LAN-wide) and it is missing 6 active Symphony services that were observed
by the 2026-04-24 audit.

## Scope (docs-only)

- Edit `PORTS.md` to add 6 missing rows, correct the footnote, bump
  "Last updated".
- No runtime changes.
- Write receipt and STATUS_REPORT closure.

## Out of scope

- Changing which interface any service binds to (that is a services-
  hardening prompt, authored separately).
- Re-classifying any port REQUIRED/OPTIONAL/STALE.
- Editing compose, launchd, env, secrets, firewall.

## Operator steps

1. `cd ~/Documents/AI-Server && git pull --ff-only`
2. Paste `.cursor/prompts/2026-04-24-cline-ports-md-registry-refresh.md`
   into Cline (ACT MODE).
3. Cline runs prechecks and prints READY TO APPLY diff.
4. Operator replies `APPROVE APPLY` or `CANCEL`.
5. On APPROVE: file edit, receipt, commit, push.

## Exit criteria

- `PORTS.md` contains 6 new rows and the corrected footnote.
- `Last updated:` is `2026-04-24`.
- Receipt exists at `ops/verification/${STAMP}-ports-md-refresh/`.
- STATUS_REPORT has strikethrough-✅ closure line.
- `git log -1 --name-only` shows the commit on `main`.

## Rollback

- `git revert <hash>` then `git push origin main`. Safe — docs only.

## Closure (append verbatim to STATUS_REPORT after apply)

```
- ~~[FOLLOWUP] Update PORTS.md — 6 active services missing, note inaccurate~~ ✅
  Refreshed in commit <HASH> on 2026-04-24. Receipt:
  ops/verification/${STAMP}-ports-md-refresh/
```
