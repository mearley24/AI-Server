# Away Workflow — Running AI-Server Remotely

Practical runbook for Matt when he is away from Bob and wants autonomous
work to continue. The goal is: SSH in, run one command, walk away.

## 1. Get into Bob

Any of the following, in order of preference:

- **SSH over Tailscale** — `ssh matt@bob` (or the Tailscale magic-DNS name).
  This is the normal path.
- **SSH over the private VPN / LAN** — if Tailscale is unhappy, fall back
  to the LAN IP while on the home network or VPN.
- **iMessage / remote-control surface** — as a last resort, use the
  existing Telegram-Bob-Remote or iMessage bridge to ping a command into
  Bob. This is only for trivial status checks; use SSH for real work.

Once in, always `cd ~/AI-Server` before running anything.

## 2. Check state

```bash
cd ~/AI-Server
bash scripts/ai-dispatch.sh status
```

What this tells you:

- **Host role** — confirms you are on Bob (not accidentally on the
  MacBook).
- **claude CLI** — present / version.
- **Model smoke tests** — whether `claude-sonnet-4-6[1m]` and the fallback
  `claude-sonnet-4-20250514` both respond.
- **Local LLMs** — which of `ollama`, `llama-cli` are on PATH.
- **Latest artifacts** — last 5 files under `ops/verification/`, so you
  can see what the last autonomous run did.

All status output is also written to
`ops/verification/dispatch-<ts>-status.txt`, so the state is durable.

## 3. Kick off work

### Priority 1 stage-gated run (most common)

```bash
bash scripts/ai-dispatch.sh run-priority1
```

This invokes `scripts/run-priority1-1m.sh`, which:

1. Smoke-tests `claude-sonnet-4-6[1m]`.
2. Writes the staged Priority 1 prompt.
3. Execs Claude Code, which carries out each Priority 1 stage with
   verify → `STATUS_REPORT.md` update → `git commit` → `git push`.

### One-off large prompt

```bash
bash scripts/ai-dispatch.sh run-prompt path/to/prompt.md
```

Routes to 1M Sonnet; falls back to `claude-sonnet-4-20250514` if the 1M
smoke test fails. Output is streamed and logged under
`ops/verification/dispatch-<ts>-run-prompt.txt`.

### List what is available

```bash
bash scripts/ai-dispatch.sh models
```

## 4. Where local LLMs fit

Local LLMs (ollama, llama.cpp) are useful when you want low-cost, offline
work. They are **not authoritative** for repo commits.

Good uses:

- **Drafting** — turn a rough idea into a cleaner prompt, then feed that
  prompt into `run-prompt` for the authoritative pass.
- **Summarization** — reduce a long log or artifact into a paragraph you
  can skim on mobile.
- **Simple checks** — "is this config plausibly correct?" — while you are
  offline on a plane.

Invocation:

```bash
bash scripts/ai-dispatch.sh local-prompt path/to/prompt.md
```

The dispatcher picks the first ollama model it finds, or tells you the
install hint if nothing is available. Output is captured to
`ops/verification/dispatch-<ts>-local-prompt.txt`. No git operations are
performed by this mode — if the output is worth landing in the repo,
re-run the change through `run-priority1` or `run-prompt` so the normal
verify / commit / push gating applies.

## 5. Cline, briefly

Cline (the IDE extension) is great for small, bounded edits while you are
at a machine with VS Code open. It is not part of the away workflow —
when Matt is remote, prefer the dispatcher. Rule of thumb: if the task
fits comfortably in 200k tokens and is a tight diff, Cline is fine; if
it is 1M-shaped, go direct via `run-prompt` or `run-priority1`.

## 6. Source of truth reminder

- `origin/main` on GitHub — canonical code + docs + `STATUS_REPORT.md`.
- `ops/verification/` — durable artifacts per run.
- Anything not in those two places is ephemeral and can be lost.

## 7. What this workflow deliberately does not do

- No recurring scheduled runs are created by these docs. If you want one,
  that is a separate, explicit LaunchAgent / cron change.
- No outbound messaging (Twilio, iMessage, Zoho, Linear) is triggered by
  the dispatcher. Those remain future connector lanes on the same
  dispatcher shape.
- No secrets are read, printed, or logged. Presence checks only.
