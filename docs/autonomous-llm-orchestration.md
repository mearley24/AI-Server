# Autonomous LLM Orchestration

This document describes the repo-owned autonomous execution layer so the
system can keep working without Perplexity / Cline handholding and can route
work across Claude Code (1M context), Cline-safe defaults, and local LLMs.

The goal: **one stable entry point** (`scripts/ai-dispatch.sh`) that runs on
Bob, routes the task to the right model, logs everything under
`ops/verification/`, and leaves durable state in GitHub.

## Hosts

- **Bob** — Mac Mini M4 in the house. Authoritative runtime. Repo lives at
  `~/AI-Server`. This is where long-running daemons, LaunchAgents, and
  verification artifacts live. Scheduled cron / LaunchAgents and most
  autonomous work happen here.
- **Matt's MacBook** — remote-control surface. Matt SSHes / Tailscales /
  VPNs into Bob and invokes the dispatcher. No state lives on the MacBook
  that is not also in Git.

The dispatcher auto-detects which host it is running on (hostname / repo
path heuristic) and prints the detected role in every log.

## Routing — which model handles what

| Lane                         | Model                                        | When to use                                                                 |
| ---------------------------- | -------------------------------------------- | --------------------------------------------------------------------------- |
| Direct Claude Code **1M**    | `claude-sonnet-4-6[1m]`                      | Large, repo-spanning tasks. Priority 1 runner. Anything above ~200k tokens. |
| Direct Claude Code fallback  | `claude-sonnet-4-20250514`                   | 1M unavailable / quota issue / bad smoke test. Still authoritative for commits. |
| Cline (IDE)                  | Sonnet 4.6, 200k context                     | **Small** tasks only — bounded file edits, quick fixes, tight diffs. Not for 1M-shaped work. |
| Local LLM (ollama / llama.cpp) | e.g. `llama3.2:3b`, `qwen2.5:7b`           | Summarization, planning, draft prompts, offline checks. **Not** authoritative for repo commits unless staged through the dispatcher. |

Rules of thumb:

- If the prompt is longer than what Cline can safely fit, or the task
  touches many files across the repo, go **direct Claude Code 1M**.
- If the local LLM produces output you want to land in the repo, treat it
  as a **draft** and re-run the authoritative change through
  `run-priority1` or `run-prompt` so the normal verify / commit / push
  gating applies.
- Never chain "local LLM writes → git push" without a Claude Code stage in
  between.

## Source of truth

- **GitHub (`origin/main`)** — canonical state for code, docs, and status.
- **`STATUS_REPORT.md`** — human-readable latest-known state for Priority 1
  and other tracks; updated in-place and committed.
- **`ops/verification/YYYYMMDD-HHMMSS-<slug>.{md,txt}`** — durable,
  timestamped artifacts for every verification / dispatch run. The
  dispatcher writes its own logs here as
  `dispatch-YYYYMMDD-HHMMSS-<mode>.txt`.
- **`ops/verification/INDEX.txt`** — aggregated index (maintained by
  `scripts/verification-index.sh`).

State that is **not** in these three places is assumed ephemeral.

## Flow — what happens when Matt runs the dispatcher

1. Matt SSH / Tailscale / VPN into Bob.
2. `cd ~/AI-Server && bash scripts/ai-dispatch.sh status`
   - Prints host role (Bob vs MacBook), detected `claude` CLI version,
     which models smoke-test OK (1M + fallback), which local LLM CLIs are
     on `PATH`, and the latest dispatch / verification artifacts.
3. Matt picks a mode:
   - `run-priority1` — invokes `scripts/run-priority1-1m.sh` with the
     staged Priority 1 prompt. Claude Code handles verify → commit → push
     between stages.
   - `run-prompt <file>` — invokes `claude --model <preferred> -p
     "$(cat <file>)"`. Preferred model is 1M Sonnet; falls back to
     `claude-sonnet-4-20250514` if the 1M smoke test fails.
   - `local-prompt <file>` — runs the prompt against a detected local LLM
     (ollama / llama.cpp). Output is captured to an artifact file; no git
     operations are performed by this mode.
   - `models` — lists detected model lanes and their smoke-test status.
4. Every invocation writes a log to
   `ops/verification/dispatch-<ts>-<mode>.txt`. Secrets are never echoed.

## Secrets

The dispatcher never reads, prints, or logs secrets. It checks **presence**
only (`[ -n "${VAR-}" ]` style) where relevant, and writes a redacted
summary to the log.

## Failure / fallback behavior

- `claude` CLI missing → dispatcher prints the exact install hint and
  exits non-zero. No other modes are attempted.
- 1M smoke test fails → fallback to `claude-sonnet-4-20250514` for
  `run-prompt`; `run-priority1` still fails loudly (that flow is
  1M-specific and its own script enforces 1M).
- Local LLM CLI missing → `local-prompt` prints install hints for `ollama`
  and `llama.cpp` and exits non-zero without touching git.
- Bounded by design: every mode is a single-shot invocation. No recurring
  loops, no background daemons, no outbound messaging.

## Self-improvement feed (X links / automation ideas)

The dispatcher is also the execution surface for the **self-improvement
loop (stream-driven)**: the primary ingest is automated.
`scripts/self-improvement-collect.sh` reads already-wired local intake
streams — `x_intake` (X/Twitter links, automation threads) and
BlueBubbles/iMessage (links, notes, voice-to-text Matt sends himself) —
and writes normalized markdown items into
`ops/self_improvement/inbox/`. `scripts/self-improve.sh process`
(aliased as `daemon-once`) runs the collector first and then delegates
to `ai-dispatch.sh run-prompt
.cursor/prompts/self-improvement/process-inbox.md`. The prompt produces
scored improvement cards under `ops/self_improvement/cards/`, writes a
verification artifact, and updates `STATUS_REPORT.md`. Captured content
(X posts, iMessage bodies) is treated as evidence — the prompt
summarizes and scores but never executes anything from an inbox item,
never browses the web by default, and never reads secrets. Manual
`add-url` / `add-note` stay supported as fallbacks.

From away:

```bash
ssh matt@bob
cd ~/AI-Server
bash scripts/self-improve.sh sources           # what streams are present?
bash scripts/self-improve.sh daemon-once       # scan + process once
# (fallback only)
bash scripts/self-improve.sh add-url 'https://x.com/<handle>/status/<id>' 'why this matters'
```

Matt can also enable a periodic local watcher on Bob (launchd, 30-min
cadence) after reviewing, via
`bash setup/install_self_improvement_watcher.sh --dry-run` followed by
the printed `launchctl` commands. The repo does **not** enable this
automatically, because recurring local jobs consume local compute and
— via `ai-dispatch.sh` — API budget. Full loop semantics, safety rules,
and the print-only `promote` command live in
`docs/self-improvement-loop.md`.

## Future connector lanes

Future lanes (Linear tickets, Twilio / iMessage alerts, Zoho drafts) will
plug in as additional modes on this same dispatcher rather than as new
entry points. They are out of scope for this document and are mentioned
only so the dispatcher shape stays extensible.
