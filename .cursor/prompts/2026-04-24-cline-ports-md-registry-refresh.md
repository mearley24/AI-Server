# Cline Prompt — PORTS.md registry refresh (docs-only)

Status: active
Owner: Cline (ACT MODE on Bob) — docs-only, no Bob runtime actions
Created: 2026-04-24 (UTC)
Parent evidence: `ops/verification/20260424-182340-port-api-surface-audit/classification.md`
Paired runbook: `ops/runbooks/2026-04-24-ports-md-registry-refresh.md`

## Why this prompt exists

The 2026-04-24 port/API surface audit found PORTS.md has drifted from
reality:

- **Missing entries (6 active services):** 1234 (BlueBubbles), 8088
  (markup-tool), 8199 (imessage-bridge), 8421 (trading-api), 8801
  (vault-pwa), 11434 (Ollama).
- **Inaccurate footnote:** PORTS.md says "All ports bind to `127.0.0.1`
  only (no external exposure)" — false. Ports 1234, 8199, 8421, 11434
  bind `*` (LAN-wide); port 8102 has a second unexplained LAN-wide
  binding (see the `:8102` evidence-gap prompt).

This prompt refreshes PORTS.md so the registry matches the committed
classification table. No services are changed; this is a docs-only hygiene
pass. "Last updated" becomes 2026-04-24.

## Scope

- Edit `PORTS.md` only.
- Add the 6 missing rows with Category + Bind column populated from
  `ops/verification/20260424-182340-port-api-surface-audit/classification.md`.
- Replace the "All ports bind to `127.0.0.1` only" line with a truthful
  paragraph that distinguishes loopback vs LAN-wide bindings and points at
  the audit evidence directory for the per-port source of truth.
- Update "Last updated:" to `2026-04-24`.
- Emit receipt under `ops/verification/${STAMP}-ports-md-refresh/`.
- Append closure line to STATUS_REPORT.

## Hard scope limits

- **Docs-only.** No container, launchctl, firewall, env, secret, or port
  edits. No `docker compose ...`. No restarts.
- **Do not re-classify.** Use the REQUIRED/OPTIONAL/STALE/UNKNOWN labels
  from the audit verbatim. Any new classification is a separate prompt.
- Do not add rows for macOS system services (AirPlay 5000/7000, rapportd
  49168/51703/51704, Dropbox 17600/17603). Those are out of scope of the
  Symphony registry.

## Prechecks

1. `git pull --ff-only` on `main`; no local diff on `PORTS.md` or
   `STATUS_REPORT.md`.
2. `test -f ops/verification/20260424-182340-port-api-surface-audit/classification.md`
   — confirm source of truth exists; copy its row for each missing port
   into the new PORTS.md entry.
3. Dry render: print the new PORTS.md to stdout before writing. Diff
   against the working tree version. Verify 6 new rows + footnote text
   change + `Last updated:` bump. No other changes.

## Approval gate

Print "READY TO APPLY" with the full unified diff of `PORTS.md`. WAIT for
`APPROVE APPLY`. Any other token: STOP.

## Apply

1. Write the new `PORTS.md`.
2. Receipt under `ops/verification/${STAMP}-ports-md-refresh/`:
   - `before.md` — pre-edit copy
   - `after.md` — post-edit copy
   - `diff.patch`
   - `README.md` — rationale + commit hash
3. Append STATUS_REPORT closure (see Runbook §Closure).
4. Commit: `docs(PORTS): refresh registry against 2026-04-24 audit
   evidence`.
5. `git push origin main`.

## Rollback

- `git revert <hash>` then push. Nothing runtime depends on PORTS.md —
  revert is safe.

## Verification receipt (mandatory)

- UTC timestamp, operator, host
- 6 new rows listed with the specific Bind classification
  (loopback / LAN `*`) copied from audit evidence
- Footnote replacement text quoted
- Diff + commit hash

## STATUS_REPORT closure (to append)

```
- ~~[FOLLOWUP] Update PORTS.md — 6 active services missing, note inaccurate~~ ✅
  Refreshed in commit <HASH> on 2026-04-24. Receipt:
  ops/verification/${STAMP}-ports-md-refresh/
```
