# Self-Improvement Loop

A bounded, repo-safe loop that lets AI-Server ingest ideas Matt captures
on the fly — X/Twitter links, automation riffs, snippets from other
projects — and turn them into concrete, reviewable improvement proposals
without letting any of that external input execute blindly.

The loop is **inspiration-in, proposal-out**. X links and other captured
notes are treated as *evidence*, never as instructions. Actual changes
only land through the existing dispatcher / verification / STATUS_REPORT
gates.

## Operating loop

1. **Capture** — Matt (or a future connector) drops an item into
   `ops/self_improvement/inbox/` via `scripts/self-improve.sh add-url`
   or `add-note`. Each item is a small markdown file with a timestamped
   name, the raw source (URL / text), and an optional "why this matters"
   hint. Items are append-only.
2. **Archive raw input** — when `process` runs, the original inbox file
   is copied verbatim into `ops/self_improvement/archive/` before any
   summarization, so the untouched input is always recoverable.
3. **Summarize** — an LLM pass (Claude Code via `ai-dispatch.sh`, or
   local LLM fallback) produces a short factual summary of what the
   link/note is about. No fetching of external URLs unless the run is
   an explicit direct-Claude session with web access; otherwise the
   item is marked `needs fetch` and Matt can paste the content later.
4. **Classify & score** — each item gets three 1–5 scores (impact,
   effort, risk) and a category tag (e.g. `ingest`, `ops`, `dashboard`,
   `trading`, `knowledge`, `infra`). Scoring is bounded and conservative:
   when unsure, assume **higher effort and higher risk**.
5. **Create improvement card** — a markdown card lands in
   `ops/self_improvement/cards/` with: source URL, summary, automation
   pattern observed, applicability to AI-Server, impact / effort / risk,
   recommended next action, and — if the action is *auto-safe* — a
   proposed implementation prompt path Matt can hand to the dispatcher.
6. **Decide action** — each card ends with one of:
   - **auto-safe prompt** — small, bounded, repo-local change; a
     `.cursor/prompts/<name>.md` is drafted and referenced. Still
     requires Matt to run it through `ai-dispatch.sh run-prompt`.
   - **needs Matt** — architectural or ambiguous; card flagged for
     human decision, no prompt drafted.
   - **reject / defer** — not applicable, duplicate, or out of scope;
     card records the reason so we don't re-triage the same link later.
   - **external connector follow-up** — requires a connector we have
     not yet built (Linear ticket, Twilio alert, Zoho draft, etc.).
     Card names the future lane but does nothing else — those lanes
     are deliberately out of scope for this loop.
7. **Record** — `process` updates `STATUS_REPORT.md` with summary
   counts (`N inbox → M cards: a auto-safe / b needs-Matt / c deferred`)
   and writes a verification artifact under
   `ops/verification/self-improve-<ts>.txt` with the card filenames and
   decisions.

## Safety rules

- **No blind execution of external content.** X posts, blog snippets,
  and scraped text are inputs to *summarize and score*, never to
  `curl | bash`-style runs.
- **No web browsing by default.** The `process` prompt does not fetch
  URLs. If content is missing, the card is marked `needs fetch` and
  Matt provides the text, or he re-runs the prompt in an explicit
  direct-Claude session where web access is allowed for that turn.
- **No secrets touched.** The prompt and script never read, print, or
  log environment variables, API keys, or credential files. Presence
  checks only, and only if strictly required (they aren't, for this
  loop).
- **No outbound communication.** The loop does not post to X, send
  email, DM Slack, or call any external API. Future connectors will
  be separate, explicit dispatcher lanes.
- **Bounded reads.** The `process` prompt reads at most N small files
  from `ops/self_improvement/inbox/` per run (default 20, each capped
  at ~10 KB). Large payloads should be summarized by Matt before
  capture.
- **Promote ≠ execute.** `scripts/self-improve.sh promote <card>` only
  *prints* the proposed next command and prompt path. It never runs
  it. Matt still has to copy the command and run it through the normal
  dispatcher, which enforces verify / commit / push gating.
- **X links are inspiration.** A viral tweet showing an automation
  pattern is a data point, not a design. The card captures *what the
  pattern is* and *whether AI-Server already has something similar*
  before proposing anything new.

## Directory map

```
ops/self_improvement/
  inbox/     # timestamped raw captures (url + why)
  cards/     # generated improvement proposals (markdown)
  archive/   # verbatim copies of processed inbox items
.cursor/prompts/self-improvement/
  process-inbox.md   # the prompt Claude Code runs to do steps 2–7
```

## Commands

| Command                                              | What it does                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------------- |
| `bash scripts/self-improve.sh add-url <url> [note]`  | Writes a timestamped inbox item with the URL and optional note.   |
| `bash scripts/self-improve.sh add-note <text...>`    | Writes a timestamped inbox item with free text (no URL required). |
| `bash scripts/self-improve.sh list`                  | Lists inbox, card, and archive counts and recent entries.         |
| `bash scripts/self-improve.sh process`               | Runs the `process-inbox.md` prompt via the dispatcher.            |
| `bash scripts/self-improve.sh promote <card-file>`   | Prints the proposed next command for the card; never executes.    |

## Future routing targets (not wired)

These are mentioned so the loop stays extensible, not because they are
active:

- **Linear** — ticketize `needs Matt` cards.
- **Twilio / iMessage** — alert on high-impact auto-safe cards.
- **Zoho** — draft client-facing follow-ups when a card maps to a
  client ask.

Each would be a new `ai-dispatch.sh` lane, not a new entry point.
