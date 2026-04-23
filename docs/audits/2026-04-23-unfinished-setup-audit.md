# Unfinished Setup Audit — "What We Worked On and Never Set Up" (2026-04-23)

**Date**: 2026-04-23
**Auditor**: Claude Code (autonomous, docs-only pass)
**Source question**: "look through the entire space and see what we worked on and never setup."
**Approach**: Static cross-reference of two prior audits (bob-freezing runtime
hangs and x-intake deep-dive) plus a repo-state sanity pass (`ls setup/launchd/`,
`ls tools/`, `ls .cursor/prompts/`, git log on main). No runtime services were
touched; no secrets were read; no destructive operations were performed. Every
classification below is grounded in a commit hash, a repo path, or a prior-audit
anchor — in-memory claims from past sessions are treated as hypotheses until
the repo confirms them.

> **Scope guardrail.** This audit is a classification pass only. It does *not*
> load launchd jobs, start services, touch Bob's runtime, open ports, expose
> anything publicly, send external messages, or modify runtime state. The only
> artifacts produced by this pass are this file, the STATUS_REPORT entry that
> links to it, and the follow-up Cline prompt in `.cursor/prompts/`.

---

## TL;DR — Highest-Priority Next Setup Gap

> **CLOSED 2026-04-23 09:43 MDT.** The TL;DR gap this audit flagged is ✅ as of
> commit `cece843`. The rest of §1–§5 below remain accurate for gaps that
> were *not* the top priority. Do **not** use the text below this block as a
> basis for reopening the network-monitoring work — use the Run-4 evidence.
>
> Network-monitoring supervision is complete:
> - Both plists committed: `setup/launchd/com.symphony.network-guard.plist`
>   (pre-existing) and `setup/launchd/com.symphony.network-dropout-watch.plist`
>   (commit `9e12fc6`, PATH fix `4dbd996`).
> - `security_utils` crash in `tools/network_guard_daemon.py` fixed by
>   commit `329ea8c` (inlined `sanitize_for_telegram`).
> - Both agents armed, running, `exit=0`, healthy — evidenced by
>   `ops/verification/20260423-094342-network-monitoring-launchd.txt` and
>   `docs/audits/2026-04-23-04-network-monitoring-launchd-verification.md`.
> - Superseding prompts marked `Status: done`:
>   `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`,
>   `.cursor/prompts/2026-04-23-cline-network-monitoring-arm-and-fix.md`.
>
> Remaining items are `[FOLLOWUP]` housekeeping only (prune pre-fix `.err`
> after a stable day; optional `~/Library/LaunchAgents/` copy).
>
> **Remaining §1 open items → Cline prompts (2026-04-23):** five
> self-contained, copy/paste-runnable prompts now cover every other §1
> gap. They were authored docs-only; no runtime was touched. Run in
> this order:
>
> 1. `.cursor/prompts/2026-04-23-cline-bluebubbles-attachment-bodies.md`
> 2. `.cursor/prompts/2026-04-23-cline-bluebubbles-health-plist.md`
> 3. `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md`
> 4. `.cursor/prompts/2026-04-23-cline-cortex-embeddings.md`
> 5. `.cursor/prompts/2026-04-23-cline-x-intake-reply-leg-phases-2-6.md`
>
> **Update (2026-04-23 17:05 UTC):** All five prompts are now
> `Status: done` and verified repo-side. The only remaining items are
> human-gated runtime arms on Bob. Track them via:
> - `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md` (new;
>   supersedes inline arm notes for embeddings).
> - The `[NEEDS_MATT]` / `[BOB_CLINE_ONLY]` gates already recorded in
>   the STATUS_REPORT entries for the other four prompts.
> - `ops/verification/20260423-164850-five-prompt-reconciliation.md`
>   (plus its 17:05 addendum) for the full per-prompt outcome table.
>
> ---
>
> *Original TL;DR (preserved for history):* "No committed launchd plist
> exists for `tools/network_dropout_watch.py`, and there is no committed
> verification path that proves either `tools/network_guard_daemon.py` or
> `tools/network_dropout_watch.py` is actually loaded, supervised, and
> producing events on Bob today." This is no longer accurate — see above.

---

## 1. Not Set Up (no clear evidence of completion)

Grounded in: `docs/audits/x-intake-deep-dive-audit.md`, repo file tree, and
the Apr-23 bob-freezing audit.

- **Full LAN traffic-monitoring stack** (ntopng / netdata / tcpdump / full
  traffic capture). No compose service, no launchd plist, no repo-owned
  daemon beyond the two lightweight reachability scripts in `tools/`. The
  x-intake deep-dive did not surface one either. Status: **absent by
  choice, not by ship.** Evidence: `grep -l` for ntopng/netdata across
  the repo returns nothing; `docker-compose.yml` has no such service.
- **End-to-end one-message source-driven loop for x-intake beyond the
  webhook / ingest scaffolding.** Deep-dive confirmed fetch + normalize +
  Cortex write paths are all present, but the *integrated reply-leg
  executor* (Phases 2–6 in the reply-action design) is absent by design
  and not scheduled. Evidence: `docs/audits/x-intake-deep-dive-audit.md`
  reply-action module discussion; `integrations/x_intake/reply_actions/`
  exists as Phase-1-only schema + module.
- **Committed launchd plist for `tools/network_dropout_watch.py`.**
  Evidence: `ls setup/launchd/ | grep -i dropout` is empty;
  `grep -r network_dropout_watch --include="*.plist" .` is empty. The
  Python tool itself is present at `tools/network_dropout_watch.py:1`
  with `--watch` and `--status` modes (CLI parsed at lines 189–199).
- **Bluebubbles attachment bodies + outbound-reply consolidation +
  `bluebubbles-health.sh` plist.** Evidence: no
  `scripts/bluebubbles-health.sh`, no `com.symphony.bluebubbles-health.plist`
  in `setup/launchd/`. Memory noted this as a known absence; repo confirms.
- **Cortex cross-source dedup (UNIQUE/upsert) and embeddings.**
  ~~Evidence: prior x-intake deep-dive lists both as open gaps; no
  `UNIQUE` constraint on `cortex_events` in `cortex/engine.py` schema
  grep, no embedding write-path file in `cortex/`.~~
  **CLOSED repo-side 2026-04-23.** Dedup: commits `716b14a` (schema +
  UNIQUE index), `da532f3` (remember upsert), `758b31f` (backfill +
  12 tests), `bc8ffdf` + `50feea8` (verification). Embeddings: commits
  `9f0b7c4` (schema), `89ad9fc` (module), `814f746` (search + backfill),
  `7eab1eb` (8 tests). Default posture `CORTEX_EMBEDDINGS_ENABLED=0`.
  ~~Live `--apply` on Bob `brain.db` is `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]`
  and tracked in the runbook
  `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md`.~~
  **Embeddings runtime arm CLOSED 2026-04-23 UTC** — runbook executed
  on Bob, VERDICT: ARMED (4559 rows, `nomic-embed-text`, `/health`
  200). Receipts: `ops/verification/20260423-131459-cortex-embeddings-live-arm.txt`
  (commit `555274cd`), `ops/verification/20260423-135512-cortex-embed-arm-evidence.txt`
  (commit `412ec2bc`), `ops/verification/20260423-200253-cortex-embed-arm-closure.txt`.
  See STATUS_REPORT §"Cortex Embeddings Arm Closure". Historical
  backfill of remaining ~48k rows is a [FOLLOWUP], not a gate.

## 2. Partially Set Up (meaningful hooks exist; end-state not evidenced)

- **BlueBubbles / iMessage integration.** Cortex normalizes
  `/hooks/bluebubbles` and publishes to `events:bluebubbles` /
  `events:imessage`. Committed at ab11dcb (see STATUS_REPORT). Memory
  frames this as "hardening," not end-state. Outbound-reply
  consolidation and attachment handling are still open (above).
- **Full-system audit process.** Ran previously and produced 5
  low-risk fixes (per STATUS_REPORT). Some closures remain, and the
  audit machinery itself is not on a schedule.
- **Task-runner / autonomous execution pipeline.** Built
  (`scripts/task_runner.py` + `ai-dispatch.sh` + `self-improve.sh` +
  launchd plists under `setup/launchd/`). But sessions have shown
  wedge/recovery issues; the 2026-04-23 bob-freezing audit narrowed the
  root cause to unbounded `subprocess.run` git calls (no `timeout=`).
  Hotfix chain landed today (e223dd9 → b0bb0ff), but Phase-5 Bob
  runtime capture of the git-timeout fix is still pending.
- **Watchdog v3 deploy on Bob.** Repo script PASSes under local checks
  (ba3c298, b0bb0ff), but the system-copy deploy step is gated behind
  `[NEEDS_MATT] sudo bash setup/install_bob_watchdog.sh --deploy-system`.
  Hotfix is complete in the repo; it has not been proven live on Bob.
- **Reply-actions Phase 1.** Module + schema + deep-dive audit
  committed (`integrations/x_intake/reply_actions/`). Phases 2–6 are
  absent by design.

## 3. Set Up but Unverified (code exists; no end-to-end receipt)

- **Repo-owned Cline-first workflow.** Exists across
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`, `.clinerules`,
  `CLAUDE.md`, and dozens of `cline-prompt-*.md` files. No single
  end-to-end prompt-verification receipt exists proving every path.
- **Watchdog fixes committed and passing `bash -n` / `--check`.**
  Repo content was not re-verified against a clean checkout in the
  past-context pass beyond the local script checks recorded in
  STATUS_REPORT.
- **Direct Claude runner / ai-dispatch orchestration.** Exists in
  prompts (`.cursor/prompts/cline-prompt-AA-claude-max-setup.md`) and
  docs; no conclusive completion receipt for *all* modes. The
  autonomous-loop mode is live (launchd plist + heartbeat commits every
  ~15 min in `git log`), but the remote-trigger / scheduled-run mode
  coverage is not proven end-to-end in a single artifact.
- **`tools/network_guard_daemon.py` plist.** `setup/launchd/com.symphony.network-guard.plist`
  is committed (verified this pass). Whether it is currently loaded on
  Bob, what its current launchd exit-code history is, and whether its
  stdout/stderr log paths exist on disk — none of that is captured in
  `ops/verification/`. See §0 TL;DR.

## 4. Already Complete (strong evidence)

- BlueBubbles integration + hardening committed at **ab11dcb** and
  subsequent hardening commits.
- Full-system sweep/audit outputs captured in `ops/verification/` and
  commits **a7eef00** / **851e722** (per STATUS_REPORT history).
- Bob watchdog freeze root-cause diagnosed (2026-04-23) at
  **2b0648f**; hotfix chain e223dd9 → 5b85ba9 → 0781348 → 4375e63 →
  ba3c298 → b0bb0ff. `--check` passes locally; repo scripts pass
  `bash -n` and dry-run tick simulation.
- X-intake deep-dive audit shipped at
  `docs/audits/x-intake-deep-dive-audit.md` (2026-04-23, Claude Code).
- Bob-freezing runtime-hangs audit shipped at
  `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md` with
  verification artifact
  `ops/verification/20260423-131042-bob-freeze-diagnosis.txt`.

## 5. Unresolved / Cross-Cutting

- **STATUS_REPORT alignment.** Approval-drainer plist status is
  contradicted between sections of STATUS_REPORT.md. Pending_approvals
  backlog = 237 and `ops/verification/` prune are still open
  `[FOLLOWUP]`s.
- **Reply-actions Phase 1 prompt vs. runtime implementation.** Prompt
  scope and module scope are aligned for Phase 1; Phases 2–6 are
  design-only.
- **X-intake / Cortex / self-improvement integrated verification
  trail.** Per-hop receipts exist but a single stamped end-to-end
  artifact proving a representative message flows all the way to a
  Cortex write + self-improvement note does not.
- **Polymarket funding / DNS blockers.** Called out in prior audits
  as `[NEEDS_MATT]`.

---

## 6. Highest-Priority Next Setup Path (Recommended)

**Close the network-monitoring launchd gap, end-to-end, repo-owned only.**

Rationale:
1. **Bounded and safe.** Both tools are single-process Python scripts
   that perform ping/reachability only. No ports are opened, no new
   inbound surface, no Bob-only-secret dependency. Adds one launchd
   plist, verifies the existing one, writes a committed verification
   doc.
2. **Compounds with the watchdog work.** The watchdog fix chain that
   shipped today already addresses the *container* supervision story;
   this closes the *host-network* supervision story on the same day.
3. **High signal for low effort.** A LaunchDaemon that ticks every 60s
   and a `--watch` mode writing to `data/network_watch/` will surface
   LAN/WAN/Control4/Sonos dropouts that are otherwise invisible to the
   container-level watchdog.
4. **Does not expand external surface.** Keeps Bob behind LAN,
   preserves the "Bob-only runtime" posture, adds zero new open ports.

**Scope of the follow-up work** (handed off to the Cline prompt):

- Inspect — not load — the currently-committed
  `setup/launchd/com.symphony.network-guard.plist` on Bob, record
  `launchctl list | grep network-guard`, and the last 200 lines of
  `/Users/bob/AI-Server/logs/network-guard.log` into a bounded
  verification artifact.
- Add a committed plist for `tools/network_dropout_watch.py` (e.g.
  `setup/launchd/com.symphony.network-dropout-watch.plist`) that runs
  `--watch` as a long-lived LaunchAgent with `KeepAlive` and an explicit
  `WorkingDirectory` / `StandardOutPath` / `StandardErrorPath`, plus a
  bounded `ThrottleInterval` for restarts.
- **Do not** `launchctl load` the new plist during the Cline run;
  leave the actual load behind an explicit `[NEEDS_MATT]` gate, so the
  change ships as repo-only and Matt decides when to arm it on Bob.
- Create `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`
  (or next-available dated filename) capturing the result.
- Add the verification text artifact under `ops/verification/` with the
  stamp format the repo uses today (`YYYYMMDD-HHMMSS-*.txt`).
- Update `STATUS_REPORT.md` with a `[FOLLOWUP]` for the arm step and a
  link to the verification artifact.
- Commit and push **only** the repo-owned files. No Bob runtime mutation.

---

## 7. Evidence Paths

- Repo file tree: `setup/launchd/`, `tools/network_guard_daemon.py`,
  `tools/network_dropout_watch.py`.
- Prior audits: `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md`,
  `docs/audits/x-intake-deep-dive-audit.md`.
- Commits referenced: ab11dcb, a7eef00, 851e722, 2b0648f, e223dd9,
  5b85ba9, 0781348, 4375e63, ba3c298, b0bb0ff, 73bb0f8.
- Control docs: `.clinerules`, `CLAUDE.md`, `AGENTS.md`,
  `ops/AGENT_VERIFICATION_PROTOCOL.md` (referenced, not modified).
- Prior deploy prompt for reference:
  `cursor-prompts/DONE/Auto-14-network-guard-deploy.md`.
