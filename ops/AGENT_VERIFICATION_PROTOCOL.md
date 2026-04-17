# Agent Verification Protocol

**Authoritative rule for any AI agent (Cline, Perplexity Computer, Claude, etc.) working in this repo.**

Matt's time is expensive and chat credits are expensive. Don't ask him to paste output. Ever.

---

## The rule

**Every diagnostic / verification / seed-run / deployment command block an agent hands Matt MUST end with tee-to-file + git commit + git push to `ops/verification/`, so another agent can pull the repo and read the result directly.**

No "paste this output back to me." No screenshots of terminal windows. No multi-step conversations where Matt copies long logs. One paste in, one commit out.

---

## Required tail for every command block

Every bash block an agent produces for Matt to run must end with this pattern (or its functional equivalent):

```bash
# at the very top of the block, before any real work:
OUT="ops/verification/$(date '+%Y%m%d-%H%M%S')-<topic>.txt"
mkdir -p "$(dirname "$OUT")"

{
  # ... all the real work (checks, rsyncs, curls, sqlite queries, etc.) ...
} > "$OUT" 2>&1

cd /Users/bob/AI-Server
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" add "$OUT"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" commit -m "ops: <topic> verification $(date '+%Y-%m-%d %H:%M')"
git push origin main 2>&1 | tail -3
echo "DONE. Tell the agent: pulled."
```

If the block runs on Bert (or any non-repo host), it must `scp` the log to Bob at `/Users/bob/AI-Server/ops/verification/<filename>` and trigger the commit+push via `ssh`. See the Meeting Audio seed-run block in `MEETING_INGEST_STEPS.md` for a worked example.

---

## Naming

- File: `ops/verification/YYYYMMDD-HHMMSS-<topic>.txt`
- Topic: dash-separated, lowercase, matches the task (e.g. `audio-pipeline`, `bb-handshake`, `polymarket-dns`, `seed-run`)
- Commit subject: `ops: <topic> verification YYYY-MM-DD HH:MM` (or `ops: <topic> seed-run log ...` for runs)

---

## What goes in the log

Whatever the receiving agent needs to verify the task. Default sections:

1. Labelled banner with timestamp + topic
2. Every check or command under an `echo "=== N. NAME ==="` header so the receiving agent can grep
3. `set +e` or `|| true` on exploratory checks so one failure doesn't abort the whole dump
4. `set -euo pipefail` on destructive / seed-run blocks so failures don't silently continue
5. Full output of relevant commands — don't pre-truncate, the receiving agent will `head` / `tail` as needed

---

## What Matt does

1. Pastes the block once
2. Waits for `DONE. Tell the agent: pulled.` (or `seed run pushed`, etc.)
3. Replies with a single word: `pulled` (or `seed run pushed`)
4. The receiving agent clones the repo and reads the file

That's it. No copying output, no scrolling, no credit waste.

---

## When NOT to use this pattern

- **One-line facts** Matt already has on screen (e.g. "what's the BB server URL?") — just answer inline
- **Interactive / mutative flows** that require live decision points (e.g. `npm init`) — but these should be rare and explicitly flagged
- **Commands the receiving agent can run itself** via its own tools — in that case, don't ask Matt to run anything

---

## Rationale

Matt said it on 2026-04-17:

> "anything you ever need from me should be added to the code at the end and saved to the file so you can access it without me pasting a bunch of credit wasting slop"

Honor this. Every block. No exceptions.
