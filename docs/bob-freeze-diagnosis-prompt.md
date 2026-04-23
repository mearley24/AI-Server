# Bob Freeze Diagnosis — How to Run

Short reference for Matt. The prompt itself lives at
`.cursor/prompts/diagnose-bob-freezing-and-runtime-hangs.md`. Read that file
for the full spec; this doc is just how to kick it off.

## What it does

Runs a bounded, read-only diagnosis on Bob for the "Bob is freezing up"
symptom. Captures evidence, writes an audit under `docs/audits/`, a
verification artifact under `ops/verification/`, updates `STATUS_REPORT.md`,
and either applies a very low-risk fix or emits a Phase 1 fix prompt. Sends
no messages. Touches no secrets.

## Primary path — Cline "New Task" on Bob

1. Open Cursor / Cline **on Bob** in the `AI-Server` repo.
2. New Task → paste:

   ```
   Run .cursor/prompts/diagnose-bob-freezing-and-runtime-hangs.md.
   Follow every step. AUTO_APPROVE per the prompt's Operating mode.
   Do not send messages. Do not touch secrets. Commit and push at the end.
   Return the final report fields listed in the prompt.
   ```

3. Let it run. Expected wall time: 10–20 minutes.
4. When it finishes, read the last message — it returns root cause, changed
   files, tests, verification path, commit hash, and a next-task pointer.

## Fallback — ai-dispatch

If Cline on Bob is itself wedged (the freeze symptom), use `ai-dispatch` to
run the same prompt headlessly:

```
ai-dispatch run --prompt .cursor/prompts/diagnose-bob-freezing-and-runtime-hangs.md --auto-approve --quiet
```

If the repo wrapper script exists, prefer it:

```
ops/cline-run-prompt.sh .cursor/prompts/diagnose-bob-freezing-and-runtime-hangs.md
```

Both paths must land on Bob (`hostname` check is the first thing the prompt
runs — it will bail if it's on the wrong machine).

## What to look for in the output

- **Root cause** — one sentence. If it names a specific file:line, that's
  the place to act.
- **Verification artifact** — `ops/verification/<ts>-bob-freeze-diagnosis.txt`.
  This is the full evidence log, safe to share.
- **Next Cline task** — if the fix wasn't applied inline, the prompt will
  have dropped a `fix-bob-freezing-phase-1-*.md` into `.cursor/prompts/`.
  Run that next, same way.

## If the diagnosis itself hangs

The prompt uses bounded commands (`timeout`, `sample <pid> 2`, `tail -n`) so
it should always finish or bail cleanly. If it genuinely hangs:

1. Cancel the task in Cline.
2. Read the partial `ops/verification/<ts>-bob-freeze-diagnosis.txt` — the
   last captured phase is usually the culprit (a hanging `docker ps`, a
   hung `redis-cli`, etc.).
3. That hanging command *is* the freeze signal — treat it as a finding and
   proceed to a targeted fix prompt.

## Do not

- Do not run this on any machine other than Bob.
- Do not re-run in a tight loop if it times out — read the artifact first.
- Do not hand-edit the prompt mid-run to "make it go faster" by removing
  bounds — the bounds are what keep it safe on a wedged machine.
