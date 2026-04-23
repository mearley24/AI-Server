# Priority 1 Stage-Gated Runner (Direct Claude Code, Sonnet 4.6 [1M])

You are running directly on Bob (the user's Mac) via Claude Code with the
`claude-sonnet-4-6[1m]` model. You have the full 1M-token context window.
You are operating in the AI-Server repository at `~/AI-Server` (or the
current working directory if that does not exist).

## Ground rules

- Work autonomously. There is no human in the loop during this run.
- Do NOT inspect, print, or echo any secrets (API keys, tokens, passwords,
  webhook secrets, private keys). When verification requires presence of a
  secret, check only that the variable is set / file exists; never surface
  the value.
- After EACH stage below, you MUST:
  1. Perform the verification steps for that stage.
  2. Write a verification artifact to
     `ops/verification/YYYYMMDD-HHMMSS-<stage-slug>.md` (or `.txt`) using the
     current local timestamp. Include: what you ran, stdout/stderr summary
     (secrets redacted), pass/fail per check, follow-ups.
  3. Update `STATUS_REPORT.md` with a concise entry under the relevant
     Priority 1 section (stage name, timestamp, pass/fail, artifact path,
     next step).
  4. `git add` the changed files, commit with a message of the form
     `ops(priority1): <stage-slug> — <pass|partial|fail>`, and
     `git push origin main`.
  5. Only then proceed to the next stage. If a stage fails, commit the
     failure artifact + STATUS_REPORT update anyway, then STOP and report
     which stage blocked progress.

- Never run `git push --force`. Never amend published commits. Never skip
  hooks. If `git pull --rebase` is needed before push, do it.
- If an external check is impossible from this environment (e.g. a remote
  service is down), mark the stage PARTIAL, record why in the artifact,
  and continue to the next stage unless it hard-depends on this one.

## Stage 1 — Approval Drainer LaunchAgent

Goal: confirm the approval drainer LaunchAgent is loaded and healthy on Bob.

Checks:
- `launchctl list | grep -i approval` shows the drainer job.
- The plist exists under `~/Library/LaunchAgents/` and references a script
  that exists in the repo (check path, do not read secrets).
- Recent log file shows drainer activity within the last 24h (check mtime
  and tail last ~20 lines, redacting any token-like strings).
- If the drainer is NOT loaded, attempt `launchctl bootstrap gui/$UID
  <plist>` (or `launchctl load`) and re-verify.

Artifact slug: `approval-drainer-launchagent`.

## Stage 2 — BlueBubbles Webhook Verification / Manual Doc

Goal: verify the BlueBubbles webhook is reachable and documented.

Checks:
- Local BlueBubbles server health endpoint responds (use
  `scripts/bluebubbles-health.sh` if present, else `curl -fsS` the health
  URL from config — do NOT print auth headers).
- Webhook target (our receiver) responds 200 / expected status to a
  synthetic ping. If no safe synthetic ping exists, document the exact
  manual test steps in `docs/bluebubbles/MANUAL_WEBHOOK_TEST.md` (create
  or update) and note in the artifact that a manual verification is
  required.
- Record: server version, webhook URL path (host only, no secrets), last
  event timestamp if available.

Artifact slug: `bluebubbles-webhook`.

## Stage 3 — Direct Claude Code Sonnet 4.6 [1M] Docs

Goal: ensure the repo documents how to run Claude Code directly against
Sonnet 4.6 with the 1M context window.

Actions:
- Ensure `docs/priority1-direct-runner.md` exists and describes the single
  command `bash scripts/run-priority1-1m.sh` plus prerequisites (claude
  CLI installed, logged in, model access).
- Ensure there is a short note somewhere discoverable (e.g. `AGENTS.md` or
  `docs/` index) pointing at the direct runner for Priority 1 work.
- Do NOT duplicate the full prompt inside the docs — link to
  `.cursor/prompts/direct/priority1-stage-gate.md`.

Artifact slug: `direct-claude-1m-docs`.

## Stage 4 — Polymarket Funding Blocker Verification

Goal: confirm whether the Polymarket funding blocker is still blocking and
capture the current state.

Checks:
- From `polymarket-bot/` (or the relevant module), run the non-destructive
  status / balance check (read-only). Do NOT initiate transfers.
- Record: current on-chain balance visibility, last funding attempt status,
  any error messages (redact addresses only if policy requires; otherwise
  full on-chain data is public and OK to include).
- If the blocker is resolved, note next action (e.g. proceed to enable
  trading). If still blocked, record the precise failing check and the
  minimal next step to unblock.

Artifact slug: `polymarket-funding-blocker`.

## Final step

After all four stages have committed + pushed, append a summary block to
`STATUS_REPORT.md` under a `## Priority 1 Run — <timestamp>` heading with
one line per stage (pass/partial/fail + artifact path). Commit and push
that summary as `ops(priority1): run summary`.

Then print a final report to stdout listing:
- commit hashes produced (in order),
- artifact paths,
- any stages that were PARTIAL or FAIL and why,
- recommended next human action.
