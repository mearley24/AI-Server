<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: messaging
Risk tier: medium
Trigger:   manual
Status:    active
<!-- autonomy: end -->

# BlueBubbles Attachment Bodies + Outbound-Reply Consolidation (Cline-first)

## Owner / runtime context

- Runtime owner for live BlueBubbles server calls: **Bob** (M4). Anything
  that hits the BlueBubbles server over the LAN is marked
  **[BOB_CLINE_ONLY]** and must be run by Cline-on-Bob, not from Matt's
  MacBook.
- Repo-side work (code + unit tests + docs) is runnable from any clean
  checkout of `origin/main`.
- Scope anchor: `docs/audits/2026-04-23-unfinished-setup-audit.md` §1
  "BlueBubbles attachment bodies + outbound-reply consolidation". This
  prompt closes the *attachment bodies* and *outbound-reply
  consolidation* halves only. The paired **health plist** work lives
  in `.cursor/prompts/2026-04-23-cline-bluebubbles-health-plist.md`
  and must not be folded in here.

## Goal

Extend the BlueBubbles integration so that:

1. Inbound webhooks at `POST /hooks/bluebubbles` capture attachment
   bodies — not just metadata — with a size cap and a mimetype
   allow-list, and publish a single normalized event shape to
   `events:bluebubbles` / `events:imessage` that downstream consumers
   (cortex memory writer, x-intake bridge) can rely on.
2. Outbound-reply code paths are consolidated behind a single
   `cortex.bluebubbles.send_text` (and any sibling `send_*`) helper so
   every caller hits the same rate-limit, logging, routing-allowlist,
   and error-shape contract. No new caller invokes the BlueBubbles
   HTTP API directly.

## Non-goals

- **Not** writing/loading the `com.symphony.bluebubbles-health.plist`
  — that is a separate prompt.
- **Not** sending any real outbound iMessage during automated tests
  (use mocked HTTP + recorded fixtures only).
- **Not** changing the BlueBubbles server-side config, admin panel,
  private-api toggles, or any BlueBubbles-side plist/LaunchDaemon.
- **Not** adding a new port, new public surface, or new webhook source.
- **Not** rewriting the normalizer for non-BlueBubbles providers
  (SMS, Telegram, etc.) — this is scoped to iMessage/BlueBubbles.
- **Not** refactoring the reply-actions module
  (`integrations/x_intake/reply_actions/`) beyond the one call-site
  swap to the consolidated helper.

## Safety gates

- **No secrets**: never `cat .env`, never print `BLUEBUBBLES_API_PASSWORD`
  or any other secret. Use `git diff` redacted previews and
  `sed -n '1,40p'` on non-secret files only.
- **No destructive data changes**: do not drop, truncate, or rebuild
  any SQLite table. The new attachment-capture path may *create* a
  new table (e.g. `bluebubbles_attachments`) with `CREATE TABLE IF NOT
  EXISTS` and `INSERT OR IGNORE` semantics only.
- **No external sends from tests**: unit and integration tests must
  mock `httpx.AsyncClient`/`respx` for the BlueBubbles HTTP surface.
  Any manual send test on Bob must use the approved local reply path
  with a dedicated **TEST** recipient (Matt's own phone number) and be
  flagged `[BOB_CLINE_ONLY]` — no broadcast, no group chat, no
  arbitrary recipient.
- **No recurring/scheduled jobs** loaded by this prompt. No
  `launchctl load`, no `bootstrap`, no `kickstart`.
- **No Bob runtime mutation from the MacBook**: any step that probes
  live BlueBubbles (`curl http://127.0.0.1:8102/api/bluebubbles/health`,
  `curl http://$BB_HOST:$BB_PORT/api/v1/server/info`) is
  `[BOB_CLINE_ONLY]`.
- **No sudo. No new open port. No public exposure.**
- **No heredocs, no inline interpreters, no interactive editors, no
  `tail -f`, no `--watch`.** Bounded commands only.

## Preconditions

Read in this order before doing anything else:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `docs/audits/2026-04-23-unfinished-setup-audit.md` (§1 only)
- `docs/audits/x-intake-deep-dive-audit.md` (skim: reply-actions +
  BlueBubbles sections only)
- `cortex/bluebubbles.py` (full)
- `cortex/engine.py` (look at how `events:bluebubbles` /
  `events:imessage` are published + consumed)
- `cortex/memory.py` (look at schema only — do not modify in this
  prompt)
- `scripts/bluebubbles-health.sh` (header only; do not modify)

Confirm git state — this block is safe to paste into zsh as-is:

```
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
git pull --ff-only
```

If `git status` shows unexpected local changes outside your working
area, **stop and report** — do not stash, reset, or clean.

## Safe inspection steps (read-only, bounded)

```
python3 -c "import ast,sys; ast.parse(open('cortex/bluebubbles.py').read()); print('ok')"
python3 -m py_compile cortex/bluebubbles.py
grep -nE "attachment|send_text|_publish_event|normalize_webhook_payload" cortex/bluebubbles.py | sed -n '1,80p'
grep -rnE "BLUEBUBBLES|send_text\(|/api/v1/message/text" --include="*.py" . | sed -n '1,80p'
grep -rnE "/hooks/bluebubbles|events:bluebubbles|events:imessage" --include="*.py" . | sed -n '1,60p'
```

On Bob only (**[BOB_CLINE_ONLY]** — skip on MacBook):

```
curl -sS -m 8 http://127.0.0.1:8102/api/bluebubbles/health | head -c 400
bash scripts/bluebubbles-health.sh --json | head -c 800
```

## Implementation tasks (scoped to this one item)

Keep the change surface small. Each task below should land as a
discrete commit so a reviewer can read the diff without scrolling.

1. **Attachment bodies — inbound normalizer**
   - In `cortex/bluebubbles.normalize_webhook_payload`, keep the
     existing attachment metadata list and add a bounded body field
     per attachment. Hard cap: **≤ 5 MiB per attachment, ≤ 8 MiB
     total per event** — bail out (log + drop body, keep metadata)
     if either limit is exceeded.
   - Mimetype allow-list: `image/png`, `image/jpeg`, `image/gif`,
     `image/heic`, `application/pdf`, `text/plain`, `text/vtt`,
     `audio/m4a`, `audio/mp4`. Anything else: metadata only.
   - Body storage: write raw bytes to
     `data/bluebubbles/attachments/<yyyy>/<mm>/<sha256>.<ext>` with
     `mkdir -p` + atomic rename (`os.replace`). The published event
     carries the **path** + `sha256` + `size` + `mime`, not the raw
     bytes.
   - `sha256` doubles as the de-dup key. If the destination path
     exists and its digest matches, skip re-write.

2. **Outbound-reply consolidation**
   - Keep `cortex.bluebubbles.send_text` as the single outbound entry
     point. Add sibling helpers `send_attachment` (optional — only if
     a non-test caller needs it) behind the same class.
   - Grep for every current caller of `httpx.AsyncClient(...).post`
     that targets `/api/v1/message/text` or similar. Each caller
     must be rewritten to route through the consolidated helper.
     Suggested target call-sites (verify by grep, do not add
     imaginary ones):
     - `cortex/bluebubbles.py` itself (internal helper paths)
     - anywhere under `integrations/x_intake/` that may currently
       bypass Cortex
   - The helper must continue to honor
     `Routing.is_outbound_allowed(...)` and must **fail closed** on
     any allowlist miss.

3. **Event contract**
   - One and only one published event shape for inbound iMessage. Add
     a short dataclass or TypedDict in `cortex/bluebubbles.py` naming
     the fields. Minimum fields:
     `event_id`, `thread_guid`, `author_handle`, `text`,
     `attachments: list[AttachmentRef]`, `received_at_utc`,
     `source="bluebubbles"`.
   - Update `_publish_event` to publish the same payload on both
     `events:bluebubbles` and `events:imessage` (preserve backwards
     compat with existing consumers).

4. **No schema churn**
   - Do **not** alter `cortex/memory.py` schema. Attachment rows, if
     needed, land in a new small table under a new module (or a
     JSON-per-file path under `data/bluebubbles/`). Schema changes on
     `memories` / `decisions` / `goals` are out of scope.

## Full verification / test checklist (bounded)

Every block below is bounded. Run them sequentially; capture output
into the verification file named in "Required artifacts".

### V1 — Repo static checks

```
python3 -m py_compile cortex/bluebubbles.py
python3 -m py_compile scripts/bluebubbles-health.sh 2>/dev/null || bash -n scripts/bluebubbles-health.sh
git diff --stat
git diff cortex/bluebubbles.py | head -n 400
grep -nE "normalize_webhook_payload|send_text|AttachmentRef" cortex/bluebubbles.py | head -n 40
```

### V2 — Path existence checks

```
test -f cortex/bluebubbles.py && echo ok-bluebubbles
test -d data/bluebubbles || mkdir -p data/bluebubbles
test -d data/bluebubbles/attachments || mkdir -p data/bluebubbles/attachments
test -f scripts/bluebubbles-health.sh && echo ok-health-script
```

### V3 — New unit tests (add under `ops/tests/`)

Create `ops/tests/test_bluebubbles_attachments.py` with at minimum:

- `test_normalize_drops_oversize_attachment_body`
- `test_normalize_enforces_mime_allowlist`
- `test_sha256_dedups_identical_attachments`
- `test_publish_event_emits_both_channels`
- `test_send_text_routes_through_allowlist` (uses `respx` /
  `httpx.MockTransport`)
- `test_send_text_fails_closed_on_allowlist_miss`

Run:

```
python3 -m pytest ops/tests/test_bluebubbles_attachments.py -q
python3 -m pytest ops/tests/ -q -k bluebubbles
```

Do not network-egress during tests. If a test accidentally reaches
the real BlueBubbles server, **that is a failure** — fix the mock.

### V4 — Sample fixture round-trip (local, no network)

- Drop a 12-byte `image/png` fixture under
  `ops/tests/fixtures/bluebubbles/tiny.png` if one doesn't already
  exist (do not commit binaries larger than 4 KB).
- Add a test that feeds a synthetic webhook payload referencing the
  fixture + asserts the normalizer writes to `data/bluebubbles/
  attachments/<yyyy>/<mm>/<sha256>.png`, with the published event
  carrying the path + sha256.

### V5 — Live health probe (**[BOB_CLINE_ONLY]**, bounded, no sends)

Skip on MacBook. On Bob only, capture:

```
bash scripts/bluebubbles-health.sh --json | head -c 1000
curl -sS -m 5 http://127.0.0.1:8102/api/bluebubbles/health | head -c 400
```

If BlueBubbles server is unreachable, record that in the verification
artifact and stop — do not attempt to "fix" the server from this
prompt.

### V6 — Optional manual send test (**[BOB_CLINE_ONLY]**, **[NEEDS_MATT]**)

Only if Matt explicitly approves during this run:

```
python3 -c "from cortex.bluebubbles import BlueBubblesClient; import asyncio, os; c=BlueBubblesClient(); print(asyncio.run(c.ping()))"
```

**Do not** call `send_text` as part of this prompt unless Matt
explicitly approves in-session and provides the test recipient (his
own number). If he does, send exactly one message with a
`[bob-test]` prefix and log the server response into the
verification artifact — nothing else.

## Required artifacts

1. **STATUS_REPORT.md** — append a dated section under a new
   subheading `BlueBubbles Attachment Bodies + Reply Consolidation
   (<YYYY-MM-DD>)` listing:
   - Commits landed on this run.
   - Files touched (≤ 10 bullet points).
   - Test pass counts (`pytest -q` summary tail).
   - `[BOB_CLINE_ONLY]` / `[NEEDS_MATT]` follow-ups remaining (if any).
2. **Verification receipt** —
   `ops/verification/<YYYYMMDD>-<HHMMSS>-bluebubbles-attachment-bodies.txt`
   containing the raw output of V1–V5 (and V6 only if Matt
   approved). Redact nothing from test output; everything in that
   output is mock data.
3. **Commits** — one commit per task in "Implementation tasks" above
   is ideal. Example subject lines:
   - `feat(bluebubbles): capture attachment bodies with size+mime gate`
   - `refactor(bluebubbles): route all outbound replies through send_text`
   - `test(bluebubbles): attachment normalizer + send_text allowlist`
4. **Push to `origin/main`** at the end with `git push origin main`.
5. **Summary** — in the final STATUS_REPORT entry, list:
   - Changed files (from `git diff --stat origin/main~N..HEAD`).
   - Commit hashes (short form).
   - Bounded reproducer command a reviewer can paste.

## Stop conditions / blockers

Stop and report (do not work around) if any of the following occur:

- `git pull --ff-only` fails.
- `pytest` cannot import `cortex.bluebubbles` (missing dependency in
  `cortex/requirements.txt`).
- Adding the attachment-body path would require a schema migration on
  `cortex/memory.py`'s `memories` table — that is a separate prompt.
- The consolidated `send_text` change surface exceeds ~150 LOC net
  diff — split into a follow-up prompt rather than landing a mega-PR.
- BlueBubbles server is unreachable on Bob during V5 — that is a
  separate operational issue; document it as a `[FOLLOWUP]` and stop.
- Any step would require `sudo`, opening a port, or editing
  `~/Library/LaunchAgents/` — **stop**, those are out of scope.

## Closing checklist

- [ ] All tests in `ops/tests/test_bluebubbles_attachments.py` pass.
- [ ] No new caller of the BlueBubbles HTTP API exists outside
      `cortex/bluebubbles.py` (grep proves it).
- [ ] `data/bluebubbles/attachments/` is in `.gitignore` (add if
      missing; attachments are runtime data, not repo data).
- [ ] STATUS_REPORT entry written and committed.
- [ ] `ops/verification/<timestamp>-bluebubbles-attachment-bodies.txt`
      written and committed.
- [ ] `git push origin main` succeeds.
