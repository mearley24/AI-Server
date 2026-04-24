# NEEDS_MATT Marker Policy

**Status:** authoritative. Scope: every `[NEEDS_MATT]` marker anywhere in
the repo except frozen history under `ops/verification/*`. Owner: Matt;
day-to-day enforcement by any coding agent that touches STATUS_REPORT.md
or adds a new `[NEEDS_MATT]` bullet.

## Why this policy exists

`[NEEDS_MATT]` was introduced as a light-touch bullet prefix that the
`ops/status_report_summarizer.py` groups under "Needs Matt". In practice
the tag has accumulated:

- duplicate entries for the same underlying gate,
- stale bullets whose real-world action was already performed but whose
  marker was never struck through,
- doc/code-comment references that mention `[NEEDS_MATT]` explanatorily
  (not as an open gate) and are routinely mistaken for active items,
- frozen historical receipts under `ops/verification/*` that appear in
  grep counts and inflate the "needs Matt" surface.

This policy exists to (a) make a marker's lifecycle explicit, (b) list
the required metadata for every *active* marker so a human or agent can
act on it without chasing context, and (c) provide a single inventory
command that tells Matt which markers are actually open, which are
stale, and which are just noise.

## Classes of `[NEEDS_MATT]` references

Any `[NEEDS_MATT]` hit belongs to exactly one of these classes. Only
**active** hits represent real outstanding work.

| Class | Meaning | Where it lives | Modifiable? |
|-------|---------|---------------|-------------|
| active | open gate that requires a Matt decision or runtime action | `STATUS_REPORT.md` (top-level bullets) or a runbook `Status:` header | yes — transitions to closed or deferred |
| closed | done, struck through with `~~...~~ ✅` | `STATUS_REPORT.md`, kept as history | no (append-only) |
| runbook-header | runbook that is itself a `[NEEDS_MATT]` gate | `ops/runbooks/*.md` with `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` in header | only via the runbook's own closure flow |
| doc-reference | documentation or code comment that *mentions* the tag for context | `docs/**`, `ops/*.md`, `integrations/**/*.py`, `tools/**/*.py`, `scripts/**` | no (not an open gate) |
| prompt-reference | prompt file that references `[NEEDS_MATT]` in its guidance text | `.cursor/prompts/*.md` | no unless the prompt itself owns an active gate |
| historical | frozen receipt written by a prior run | `ops/verification/*` | **never** |

## Required metadata for active markers

Every *active* `[NEEDS_MATT]` bullet must carry — either inline on the
bullet or within three lines below it — all five fields:

1. **Owner.** Always `Matt` unless explicitly delegated.
2. **Opened.** ISO date `YYYY-MM-DD` the gate was first recorded.
3. **Review-by.** ISO date. If the gate is still open on or after this
   date, the inventory script flags it as **stale**. Default window:
   14 days from `Opened`. Extend only by re-dating the bullet with a
   reason.
4. **Evidence path.** Pointer to the committed artifact that lets a
   reviewer verify the gate's current state — typically an
   `ops/verification/*` receipt or an `ops/runbooks/*.md` runbook. For
   brand-new gates where no evidence yet exists, use the string
   `pending` and record the path the closing receipt will take.
5. **Next action.** One short line naming the exact runbook path or
   authorization string (e.g. `ARM: bluebubbles-health` via
   `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md`).

A bullet missing any of these fields is **under-specified** and the
inventory script flags it. Under-specified markers are the #1 cause of
confusion — they are not yet *stale* but they are not acceptable for
more than one working day.

### Canonical active form

```
- [NEEDS_MATT] <one-line gate description>
  Owner: Matt  Opened: 2026-04-24  Review-by: 2026-05-08
  Evidence: ops/verification/<stamp>-<slug>.txt (or `pending`)
  Next:     <authorization string or runbook path>
```

The inventory script treats the metadata block as optional whitespace-
insensitive plain text; either `Owner:` or `owner:` matches.

## Closure rules

A marker transitions out of **active** by exactly one of:

- **Closed / done.** Wrap the original bullet in `~~...~~` and append
  ` ✅ <ISO date> — <one-line outcome + evidence path>`. The bullet
  stays in place for history. Do **not** delete.
- **Deferred.** Append a sibling bullet beginning with
  `- [NEEDS_MATT] DEFERRED <ISO date>:` and include the reason and the
  date the gate will be revisited. The original bullet remains active
  from the inventory's point of view until it is re-reviewed.
- **Reclassified.** If the gate was wrongly tagged (e.g. a doc-
  reference that was mis-parsed as active), re-tag or rephrase so the
  inventory script's classifier demotes it.

Never delete an active `[NEEDS_MATT]` bullet outright. Either close it
with evidence or reclassify it with a reason recorded in the same diff.

## Duplicates

If the same underlying gate appears as multiple bullets (e.g. the same
runbook referenced from three sections of `STATUS_REPORT.md`), keep one
canonical bullet with full metadata and mark the rest as cross-
references:

```
- [NEEDS_MATT] See L<N>: <one-line pointer>
```

The inventory script will collapse cross-references to the canonical
hit when reporting.

## What is *not* a `[NEEDS_MATT]` issue

These are common false positives that the inventory script excludes by
default:

- Files under `ops/verification/*` — immutable receipts.
- Strings inside the regex source of `ops/status_report_summarizer.py`.
- Audit documents under `docs/audits/*` that reference the tag
  explanatorily.
- Prompt files under `.cursor/prompts/*` that reference the tag in
  guidance or stop-condition text (as opposed to claiming an active
  gate themselves).

If you believe one of these *is* an active gate, lift the actionable
part into `STATUS_REPORT.md` as a properly metadata'd active bullet and
leave the reference in place.

## The inventory script

Run this from the repo root:

```
python3 scripts/needs_matt_inventory.py
```

Default output: human-readable summary of active / stale / under-
specified / doc-reference / historical counts, plus the top-5 stale and
under-specified hits with file:line. Exit code is always 0 (advisory —
this is a report, not a gate).

Common flags:

- `--json` — machine-readable output for tooling.
- `--all` — enumerate every non-historical hit, classified.
- `--stale-days N` — override the default 14-day review window.
- `--include-history` — also scan `ops/verification/*` (normally
  skipped); use for forensic audits only.
- `--write ops/verification/<stamp>-needs-matt-inventory.txt` — write
  the report to a timestamped receipt.

The script is pure stdlib; no install step. Safe on any clone. It does
not mutate any file.

## When to run it

- Before opening a PR that adds or touches any `[NEEDS_MATT]` bullet.
- At the end of any clearance or cleanup prompt that closes gates.
- Periodically by a human operator — monthly is sufficient today; the
  optional prompt `.cursor/prompts/needs-matt-hygiene-check.md` can be
  used for a guided pass.

CI enforcement is deliberately **not** wired in today — the script is
advisory only. If the stale count grows despite the cleanup prompt, the
next escalation is to add it as a non-blocking GitHub Action check.

## Relationship to the clearance orchestration prompt

`.cursor/prompts/2026-04-24-cline-needs-matt-clearance-orchestration.md`
is the authoritative driver for the three remaining Bob-runtime gates.
This policy is its long-tail complement: the clearance prompt handles
the live arm work; this policy + inventory script stops the surface
from growing back.

## Change control

Edit this file directly when the policy changes — record the date and
reason in the commit message. Do not fork a copy into `.cursor/` or
`ops/runbooks/`; this is the single source of truth.
