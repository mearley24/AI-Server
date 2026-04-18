# Realized Changes — launchd watch target

Any file an agent drops into this directory (or touches anywhere inside
it) triggers `com.symphony.realized-change-watcher`, which runs
`scripts/autonomy_sweep.py` and writes a timestamped verification report
to `ops/verification/`.

The watcher also fires whenever `STATUS_REPORT.md` at the repo root is
saved.

## When to drop a sentinel here

- You (an agent) just did something that *will* have downstream effects
  another agent should know about within a minute or two, but you don't
  want to queue a full Symphony Task Runner JSON.
- You want the repo to record a cheap "something happened" pulse for
  another agent's sweep to land on.

## Sentinel format

Any non-empty file with a `.change`, `.json`, or `.txt` extension is a
valid sentinel. The newest file in the directory is embedded in the
sweep report. Recommended shape:

```
realized-change: <short slug>
by:              <agent name>
at:              <iso8601 timestamp>
summary:         <one sentence>
next:            <optional: what the next agent should do>
```

Delete old sentinels once they have been picked up by a sweep (the
sweep's verification report is the durable audit trail). Keep at most a
handful of active sentinels at a time.

## Hard rules

- Never put secrets or credentials in a sentinel file.
- Never put production data (customer info, prices, transcripts) here —
  sentinels are public-ish signals, not storage.
- Do not drop sentinels from inside `data/` or `knowledge/`. This dir is
  the only watch target for the realized-change loop.

See:

- `scripts/realized_change_watcher.sh` — the launchd-invoked handler
- `scripts/autonomy_sweep.py` — the sweep engine
- `ops/launchd/com.symphony.realized-change-watcher.plist` — install target
- `setup/install_realized_change_watcher.sh` — installer
