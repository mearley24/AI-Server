# Self-Improvement Loop

A bounded, repo-safe, **always-on** loop that watches AI-Server's existing
intake streams — `x_intake` (X/Twitter links and automation threads),
BlueBubbles/iMessage (links, notes, voice-to-text captures Matt sends
himself), and future read-only connector lanes — and turns the incoming
signal into concrete, reviewable improvement proposals.

The loop is **stream-driven first, manual fallback second.** Incoming
links and messages are treated as *evidence*, never as instructions.
Actual code changes still only land through the existing dispatcher /
verification / `STATUS_REPORT.md` gates.

> Why: Matt is already firing items into `x_intake` and BlueBubbles all
> day. The self-improvement loop should read those streams continuously,
> find the items that describe automation patterns or efficiency wins,
> and feed them into the card pipeline. Manual `add-url` / `add-note`
> modes remain as a fallback for items that come from outside those
> streams.

## Sources

The collector reads **local-only**, read-only, already-present data.
Nothing in this loop opens a new external service.

### Primary (on by default)

- **`x_intake`** — local X/Twitter intake pipeline.
  - SQLite queue: `integrations/x_intake/queue_db.py` → `/data/x_intake/queue.db`.
    Table `x_intake_queue(url, author, summary, status, source, created_at, …)`.
  - Action queue (rejected / deferred): `/data/x_intake/action_queue.db`.
  - Scan window: last 24 h of rows with `status in ('pending','auto_approved','approved')`.
  - Filter: items whose `summary` or `url` matches automation / agent /
    tooling / workflow / pipeline / scraper / efficiency keywords.

- **BlueBubbles / iMessage** — already-wired bridge.
  - Inbound events land on Redis channel `events:imessage`
    (duplicate on `events:bluebubbles`) via `cortex/bluebubbles.py`.
  - Routing config (owner allowlist): `config/bluebubbles_routing.json`.
  - Local iMessage SQLite (read-only, when available) is exposed by
    `scripts/imessage-server.py` via `IMESSAGE_DB_PATH`.
  - Scan window: last 24 h of events. Only messages from the owner
    allowlist (already enforced by the bridge) are considered.
  - Filter: messages containing a URL, a `TODO:` / `IDEA:` prefix, or
    automation/efficiency keywords. Voice-to-text notes surface here
    too — BlueBubbles dictations arrive as normal text messages.

### Future connector lanes (read-only first, gated, **not** enabled here)

These are named so the collector stays extensible. None are wired by
this loop; each will be a separate, reviewed connector.

- **Zoho Mail** — starred / labeled "ideas" threads, read-only.
- **Twilio** — inbound SMS log (same shape as iMessage).
- **Linear** — comments on issues tagged `automation-idea`, read-only.
- **GitHub** — `@matt/ideas` discussions or a specific issue label,
  read-only.
- **Web fetch / search** — only inside an explicit direct-Claude turn
  with web access. Never part of the always-on collector.

Each future lane must land as a new `scan-<lane>` mode in
`scripts/self-improvement-collect.sh`, behind feature detection, with
**read-only credentials** and bounded windows.

## Always-on loop

```
┌─────────────────────────────────────────────────────────────────┐
│  discover  →  fetch/normalize  →  summarize  →  classify  →     │
│  score (impact/effort/risk)  →  create card  →  propose prompt  │
│  →  safe auto-run via ai-dispatch.sh    OR    flag for Matt     │
└─────────────────────────────────────────────────────────────────┘
```

1. **Discover** — `scripts/self-improvement-collect.sh daemon-once`
   (or the launchd watcher, once Matt enables it on Bob) runs
   `scan-x`, `scan-bluebubbles`, and any future `scan-<lane>`.
   Each source emits candidate items with `{source, source_url,
   captured_at, raw_excerpt, why_relevant, origin_stream, confidence}`.
2. **Dedupe** — the collector hashes `(source_url || raw_excerpt)` and
   skips items whose hash already appears in `inbox/`, `archive/`, or
   `cards/`. Hashes are kept in an inline fenced block at the top of
   each inbox file so `grep` can find them without a side-channel DB.
3. **Fetch / normalize** — the collector writes a bounded markdown
   file into `ops/self_improvement/inbox/` with the frontmatter above.
   It does **not** browse the web and does **not** call any third-party
   API. The raw excerpt is whatever was already stored locally
   (x_intake summary, iMessage text body).
4. **Summarize + classify** — `scripts/self-improve.sh process` invokes
   `.cursor/prompts/self-improvement/process-inbox.md` via
   `scripts/ai-dispatch.sh run-prompt`. The prompt turns each inbox
   item into a card with an **automation hypothesis** and an
   **efficiency lever** (what AI-Server could do faster / cheaper /
   more reliably).
5. **Score** — each card gets 1–5 scores for impact, effort, and risk.
   When unsure, assume higher effort and higher risk.
6. **Propose** — if the card is *auto-safe* (repo-local, bounded, no
   secrets, no new external service, no trading/auth/launchd surgery),
   the prompt drafts a `.cursor/prompts/self-improvement/<slug>.md`
   and records the exact `bash scripts/ai-dispatch.sh run-prompt …`
   command. Otherwise the card is flagged `needs Matt`.
7. **Run or wait** — the loop never auto-executes on its own. The
   dispatcher still decides when to run. An auto-safe card *may* be
   picked up by the dispatcher's normal run; a `needs Matt` card sits
   until Matt reviews it.

## `scripts/self-improvement-collect.sh` modes

| Mode                | What it does                                                                  |
| ------------------- | ----------------------------------------------------------------------------- |
| `scan`              | Runs every available `scan-<lane>` in order. Prints a summary at the end.     |
| `scan-x`            | Reads `x_intake` SQLite queue (read-only) and emits inbox items.              |
| `scan-bluebubbles`  | Reads BlueBubbles events / iMessage DB / Redis channel if already available.  |
| `sources`           | Prints detected sources and what is missing (without failing).                |
| `daemon-once`       | Runs `scan`, then `scripts/self-improve.sh process` once. No looping.         |

All modes are **bounded**: row limits, byte caps, time windows. No mode
opens an outbound connection.

## `scripts/self-improve.sh` modes

| Mode                                                 | What it does                                                                     |
| ---------------------------------------------------- | -------------------------------------------------------------------------------- |
| `process`                                            | Runs `daemon-once` (collector first, then the `process-inbox` prompt).           |
| `scan`                                               | Runs `self-improvement-collect.sh scan` only (no LLM pass).                      |
| `scan-x` / `scan-bluebubbles`                        | Runs the single-source scan.                                                     |
| `sources`                                            | Runs `self-improvement-collect.sh sources`.                                      |
| `add-url <url> [note...]`                            | **Fallback**: manual inbox item with a URL.                                      |
| `add-note <text...>`                                 | **Fallback**: manual inbox item with free text.                                  |
| `list`                                               | Inbox, card, and archive counts and recent entries.                              |
| `promote <card-file>`                                | Prints the proposed next command; never executes.                                |

`add-url` and `add-note` remain supported so Matt can drop in something
that came from outside the wired streams (a podcast, a blog, a
conversation). Stream-driven ingest covers the bulk of the signal.

## Safety rules

- **No blind execution of external content.** X posts, iMessage text,
  and any future connector payload are inputs to *summarize and score*,
  never to `curl | bash`-style runs.
- **No web browsing by default.** The process prompt does not fetch
  URLs. If content is missing, the card is marked `needs fetch`.
- **No secrets touched.** Neither the collector nor the prompt opens
  `.env`, `.env.*`, `*.key`, `*.pem`, `~/.ssh/`, or anything that
  smells like a credential. The collector only reads from locations
  already used by the repo's existing scripts/config, and it never
  prints environment-variable values. Presence/absence of a config
  is reported as a source, not a value.
- **No outbound communication.** The loop does not post to X, send
  email, DM Slack, send SMS, or call any third-party API. Every future
  connector lane starts as read-only and requires an explicit new
  dispatcher lane.
- **Bounded reads.** Each source has a row cap (default 200) and a
  per-item byte cap (default 10 KB). Larger payloads are summarized
  before capture, or dropped.
- **Dedupe.** Items whose content hash is already present in inbox /
  archive / cards are skipped silently.
- **No auto-enable of launchd / cron.** The launchd template and
  installer in `setup/launchd/` ship with a `--dry-run` installer.
  Matt enables recurring local jobs on Bob manually after reviewing.
  Recurring local jobs consume local compute and — when `process`
  invokes Claude Code — API budget.
- **Promote ≠ execute.** `scripts/self-improve.sh promote <card>`
  only *prints* the proposed next command and prompt path.

## Directory map

```
ops/self_improvement/
  inbox/     # normalized markdown captures from streams + manual
  cards/     # generated improvement proposals (markdown)
  archive/   # verbatim copies of processed inbox items
scripts/
  self-improve.sh                 # user-facing entry point
  self-improvement-collect.sh     # stream collector (scan/daemon-once)
setup/launchd/
  com.symphony.self-improvement.plist        # launchd template (NOT loaded)
setup/
  install_self_improvement_watcher.sh        # dry-run installer
.cursor/prompts/self-improvement/
  process-inbox.md                # LLM pass that turns inbox → cards
```

## Commands (cheat sheet for Bob)

```bash
cd ~/AI-Server

# What does the collector see today?
bash scripts/self-improve.sh sources

# Pull candidates from streams, then process them once.
bash scripts/self-improve.sh daemon-once           # (equivalent to `process`)

# Single-source scan, no LLM pass.
bash scripts/self-improve.sh scan-x
bash scripts/self-improve.sh scan-bluebubbles

# Dry-run the launchd watcher installer. Does NOT load anything.
bash setup/install_self_improvement_watcher.sh --dry-run
```

### Enablement (Bob, manual) and rollback

The installer never invokes `launchctl`. It only stages the plist into
`~/Library/LaunchAgents/` and prints the bootstrap command for you to run
knowingly.

Enable:

```bash
cd ~/AI-Server
git pull --ff-only
bash scripts/self-improve.sh sources         # sanity
bash scripts/self-improve.sh scan            # sanity
bash scripts/self-improve.sh daemon-once     # sanity (one real tick)
bash setup/install_self_improvement_watcher.sh --install
# Installer prints the next two commands; run them yourself:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.symphony.self-improvement.plist
launchctl kickstart -k gui/$(id -u)/com.symphony.self-improvement

# Watch:
tail -f ~/AI-Server/data/task_runner/self-improvement.out.log
tail -f ~/AI-Server/data/task_runner/self-improvement.err.log
```

Rollback:

```bash
launchctl bootout gui/$(id -u)/com.symphony.self-improvement || true
bash setup/install_self_improvement_watcher.sh --uninstall
```

## Future routing targets (not wired)

Still listed so the loop stays extensible, not because any of these are
active:

- **Linear** — ticketize `needs Matt` cards.
- **Twilio / iMessage outbound** — alert on high-impact auto-safe cards.
- **Zoho** — draft client-facing follow-ups when a card maps to a
  client ask.

Each would be a new `ai-dispatch.sh` lane, not a new entry point.
