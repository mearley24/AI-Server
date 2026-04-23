# Audit: X-Intake Deep Dive, Reply-Action Loop, and Docker Testbed

You are Cline/Claude running inside the `AI-Server` repo. This is an **audit + design + planning** task. Do **not** implement the feature yet beyond creating the prompt, docs, audit report, schema, and verification artifact. Do **not** change runtime behavior of any service. Do **not** inspect or print secrets. Do **not** send messages (no iMessage/BlueBubbles/X posts) while running this.

## Scope

Audit and design work across three intertwined surfaces:

1. The **X-intake deep-dive pipeline** (how deep it actually goes today, where it's slow, where it silently drops signal).
2. An **interactive reply-action loop** over BlueBubbles/iMessage using concise `Reply 1 / Reply 2 / Reply 3` options.
3. An **isolated Docker testbed** for sandboxed prototypes that successful experiments can be promoted out of.

---

## 1. Audit — current X-intake deep dive

Produce a written audit (not a rewrite) covering **how deep** the current pipeline actually goes end-to-end, with file paths and line anchors. At minimum investigate:

- **Fetch/source depth** — which accounts, lists, keywords, bookmarks, search queries are pulled; scrape vs. API; poll cadence; backoff.
- **Thread context** — do we hydrate parent/quoted/reply tweets, or only the leaf tweet? How far up the thread, and to what timeout?
- **Link expansion** — which URLs get unfurled, which domains are skipped, do we follow redirects, do we render JS-heavy pages, do we cache expansions?
- **Summarization depth** — which model/router handles summaries, context length, whether we summarize thread+links together or only the tweet body, and what fields land in the outbound card.
- **Memory/Cortex writes** — what gets written, under which namespaces/tables, dedupe keys, TTL, whether embeddings are generated, and whether Cortex actually gets queried on the next intake (i.e., is the memory loop closed).
- **Relevance scoring** — scoring signals, thresholds, where the "is this worth surfacing" gate lives, and its false-negative behavior.
- **Latency bottlenecks** — measure or estimate per-stage latency (fetch, expand, summarize, score, write, deliver). Identify the top 2–3 dominant stages.
- **Cache/dedupe behavior** — what we dedupe on (tweet id? URL? normalized text?), cache layers, stale-while-revalidate behavior, and any duplicate delivery paths.
- **Why it feels slow** — a plain-language root-cause section tying measurements above to the user-perceived lag.

Bound the audit: spend the grep/read budget on `x_intake*`, `bluebubbles*`, `cortex*`, `meeting_intel*`, and the dispatcher/router; do not endlessly browse unrelated modules.

## 2. Map the full event path

Draw (in Markdown, mermaid allowed) the full path:

```
X intake → normalizer → thread/link hydrator → summarizer → Cortex write
       → relevance gate → outbound composer → BlueBubbles send
       → user reply inbound → reply parser → action router → follow-up handler
```

For each hop, note: which file/function owns it, what queues/channels connect it to the next hop, what state it reads/writes, and which failure modes silently drop messages.

## 3. Reply-action loop design

Design (do not build yet) a reply-action loop where every outbound deep-dive message ends with concise options, e.g.:

```
Reply 1 — build card
Reply 2 — deep research
Reply 3 — spin test container
```

The user replies with a short token (`1`, `Reply 2`, `r3`, etc.) and the server executes the matching action.

Specify:

- **Action catalog** — at least the three above plus a clear extension pattern. Suggested examples: `card`, `deep-research`, `prototype`, `save-to-cortex`, `mute-author`, `open-thread-in-browser`.
- **Parsing rules** — accepted formats, case-insensitive, tolerant of typos, with a clear "unrecognized" fallback that does nothing destructive.
- **Context binding** — how a reply is tied back to the original outbound message (per-message action ID, not a global mode).
- **Outbound format** — exact template for the trailing options block, short enough to not bloat messages.

## 4. Safety & idempotency rules

Non-negotiable rules the design must satisfy:

- **No ambiguous action execution** — if the reply doesn't unambiguously match exactly one action for that message's ID, do nothing and log.
- **Per-message action IDs** — each outbound message embeds a short opaque ID; replies without a resolvable ID are ignored.
- **Expiry window** — action IDs expire (propose default, e.g. 24h). Expired replies get a single "expired" acknowledgement, not execution.
- **Confirmation for risky actions** — risky actions require a second-step confirm reply (e.g., `YES`).
- **Hard denylist** — no trading, no moving money, no sending external messages (email, X post, outbound iMessage to new numbers) without an explicit human-approval step that already exists in the repo. Reuse the existing approvals flow; do not invent a new one.
- **Dedupe** — repeated identical replies within a short window execute the action at most once.
- **Audit trail** — every executed action writes a row to an auditable log with action ID, source message, reply text, actor, result.

## 5. Testbed architecture

Propose an **optional** Docker container/service for sandboxed prototypes. Requirements:

- **Network isolation** — default to no egress; explicit allowlist per prototype.
- **Read-only mounts by default** — source dirs mounted `:ro`; a single writable scratch volume per prototype, wiped on teardown.
- **Resource limits** — CPU, memory, pids, disk quota; killed cleanly on exceed.
- **No secrets unless explicitly injected** — container starts with a stripped env; secrets come in via a named injection step the operator runs manually.
- **Reproducible build** — single Dockerfile + compose file, pinned base image, no "latest" tags.
- **Promotion path** — a documented flow for turning a successful prototype into a repo task (prompt file under `.cursor/prompts/`, code under the appropriate module, tests required).
- **Teardown** — one command to stop, remove, and prune volumes/networks for a given prototype ID.

Reply-action `Reply 3 = spin test container` should route through this testbed and only this testbed — never touch production compose stacks.

## 6. Phased implementation plan

Produce a plan split explicitly into phases. Do not collapse them.

1. **Phase 0 — Audit only** (this prompt's deliverables).
2. **Phase 1 — Design sign-off** (schema, action catalog, safety rules finalized).
3. **Phase 2 — Testbed container** (Dockerfile, compose, teardown script, promotion docs).
4. **Phase 3 — Reply parser** (inbound reply → action-ID resolution; pure function, unit-tested; not wired to execution yet).
5. **Phase 4 — Action router** (wires resolved action IDs to handlers; dry-run mode first).
6. **Phase 5 — Self-improvement integration** (tie action outcomes into the existing learning/digest loop under `ops/self_improvement/`).
7. **Phase 6 — Production rollout** (feature-flagged, default off, enable per-action).

Each phase names its artifacts, owner-review checkpoint, and the gate that must pass before the next phase starts.

## 7. Required outputs

Produce and commit exactly these artifacts:

- `docs/audits/x-intake-deep-dive-audit.md` — the audit report from §1 and the event map from §2.
- `config/reply_actions.schema.json` (or `ops/reply_actions.schema.json` if that fits repo conventions better) — machine-readable action catalog, per-action safety flags, expiry defaults, confirmation requirement, and the outbound template.
- `ops/verification/reply-actions-design-verification.md` — a verification artifact listing checks performed (files read, greps run, assumptions made, open questions). No runtime changes required to verify; audit-only verification is fine.
- Update `STATUS_REPORT.md` with a short entry under the current date pointing to the above.
- Commit and push to `origin/main`.

## 8. Running commands

Use bounded, non-interactive commands only:

- `git status`, `git diff --stat`, `git log --oneline -20`.
- `grep -rn`, `rg` (if present), `find ... -maxdepth N`.
- `python -c '...'` and short scripts for log slicing.
- `docker compose config` is OK (read-only). `docker ps`, `docker images`.

Do **not** use: `tail -f`, `watch`, `less`, `vim`, `nano`, interactive shells in containers, anything that attaches to a live stream. Do not `cat` files that may contain secrets (`.env`, `secrets/`, `*.pem`, `*.key`, anything under `ops/approvals/` that looks like credentials). If you need to confirm a secret exists, check the file's existence and size, not its contents.

## 9. Success metrics

Define the metrics that Phase 6 will be judged on. At minimum:

- **Latency** — median and p95 time from tweet ingested → outbound card delivered (target: state an explicit number based on the audit).
- **One-message behavior retained** — one deep-dive per relevant tweet; no re-notify storms.
- **% links with useful cards** — proportion of expanded links where the card contains non-trivial summary content (define "useful" concretely).
- **Duplicate rate** — % of outbound messages that are duplicates within 24h; target near zero.
- **False action rate** — % of executed actions the user later flags as wrong-action-for-reply; target near zero.
- **Time-to-prototype** — minutes from `Reply 3` to a running, isolated testbed container.
- **Rollback safety** — every phase is reversible with a documented single command or PR revert; no phase leaves orphaned state.

## Guardrails recap

- No runtime behavior changes outside the artifacts in §7.
- No secrets inspected or printed.
- No outbound messages sent.
- Audit-only tool use: read, grep, write the listed artifacts, commit, push.
- If an approach gets stuck, switch tactics within 2 retries — do not loop.
