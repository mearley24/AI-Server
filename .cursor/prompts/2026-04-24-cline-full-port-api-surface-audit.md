# Cline Prompt — Full Bob Port & API Surface Audit (read-only, no mutations)

Status: active
Owner: Cline (ACT MODE on Bob)
Created: 2026-04-24 (UTC)
Parent context: Matt asked "have we done a full audit of all ports recently
to see what's used / not used and next steps?" and asked whether the
BlueBubbles API connection should be turned off. Answer: the last full
snapshot is `ops/verification/20260421-143522-full-system-sweep-and-audit.txt`
(2026-04-21, ~3 days stale) — it covered docker-compose port bindings,
`/health` sweep on the Symphony 8091-8765 range, launchd agent load state,
and BlueBubbles inbound/outbound counters. It did **not** enumerate every
LAN-visible listening socket on Bob, did not inventory launchd plists by
port, and did not classify each listener as required / optional / stale /
unknown. This prompt closes those gaps.

**Do not** stop services, unload launchd agents, close ports, mutate env,
edit firewall state, run `sudo`, publish externally, rotate secrets, or
disable BlueBubbles before this audit ships. The output is evidence + a
classification table; any shutdown proposal is a follow-up prompt gated on
Matt's explicit approval.

---

## 0. Pre-flight (no mutations)

- Repo root: `~/Documents/AI-Server` (Bob canonical path). If running on a
  translocated path, abort and ask Matt.
- Branch: `main`, pull first (`git pull --ff-only`). If dirty, stash with
  a label; do not discard.
- Capture stamp: `STAMP=$(date -u +%Y%m%d-%H%M%S)` (UTC). All receipts use
  this stamp.
- All shell commands below are read-only. If a command requires `sudo`
  (e.g. `lsof` on privileged sockets), use `sudo -n` and record `N/A:
  needs-matt` in the evidence file instead of prompting.

---

## 1. Host listening sockets (loopback + LAN)

Emit into `ops/verification/${STAMP}-port-api-surface-audit/host-listeners.txt`:

```bash
# All TCP listeners, numeric, no DNS, with PID/owner
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | sort -k9

# Fallback if lsof lacks perms for some procs
netstat -anv -p tcp 2>/dev/null | awk '/LISTEN/ {print}'

# UDP listeners (for completeness — e.g. mDNS, Tailscale)
lsof -nP -iUDP 2>/dev/null | awk '/\*:/ {print}' | sort -u
```

For each listener, record: proto, local addr, port, PID, command, user.
Classify the bind:
- `loopback` — `127.0.0.1:*` or `[::1]:*` only
- `lan` — `0.0.0.0:*`, `*:*`, or bound to the Tailscale / en0 address
- `tailscale-only` — bound to the `100.x` Tailscale CGNAT range
- `unknown` — anything else; flag for Matt

---

## 2. Docker container port maps

Emit `ops/verification/${STAMP}-port-api-surface-audit/docker-ports.txt`:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
docker compose ps --format json 2>/dev/null | python3 -c 'import json,sys
for row in json.loads(sys.stdin.read() or "[]"):
    print(row.get("Name"), row.get("Publishers"))'
```

Cross-check against `PORTS.md` (last updated 2026-04-14). Record drift:
services in `PORTS.md` not running, containers running but not in
`PORTS.md`, and containers whose published port no longer matches the
registry.

Do **not** run `docker restart`, `docker stop`, or `docker compose down`.

---

## 3. launchd agent / daemon inventory

Emit `ops/verification/${STAMP}-port-api-surface-audit/launchd-ports.txt`:

```bash
# All loaded symphony.* and bob.* agents
launchctl list | awk '/symphony\.|bob\.|com\.bluebubbles/ {print}' | sort

# Map each plist to the port it binds (if any) by grepping ProgramArguments
python3 ops/launchd_inventory.py --with-port-map 2>/dev/null \
  || for p in setup/launchd/*.plist ~/Library/LaunchAgents/com.symphony.*.plist; do
       [ -f "$p" ] || continue
       echo "=== $p ==="
       grep -E '(Program|Port|--port|:[0-9]{2,5})' "$p" || true
     done
```

For each loaded agent, attempt to tie it to a listening port from step 1
(PID match). Any agent in crash-loop state (e.g. the historical
`com.symphony.network-guard` `security_utils` crash at
`docs/audits/2026-04-23-network-monitoring-launchd-verification.md`) must
be called out.

---

## 4. BlueBubbles API surface — inbound + outbound

BlueBubbles is two distinct legs; do not conflate them when classifying.

**Inbound (webhook listener — we receive events):**
- Cortex route: `POST /hooks/bluebubbles` on `127.0.0.1:8102`
  (`cortex/bluebubbles.py::register_bluebubbles_routes`).
- Cortex health: `GET /api/bluebubbles/health` on same port.
- Config: `config/bluebubbles_routing.json` (`inbound.allowed_phones`).
- Last confirmed live: `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`
  (Verdict `PASS-webhook-only`, commit `e610cddb`, 2026-04-24).
- Disabling this kills x-intake reply-leg fan-in, Cortex message ingest,
  and the "iMessage arrived" signal that downstream skills watch for.

**Outbound (REST client — we send via BlueBubbles server):**
- `cortex.bluebubbles.BlueBubblesClient.send_text` — POSTs to
  `${BLUEBUBBLES_SERVER_URL}/api/v1/message/text` with
  `${BLUEBUBBLES_API_PASSWORD}` (`.env` lines 539–541 of `.env.example`).
- Alternate outbound path: `scripts/imessage-server.py` (host service on
  `:8199`, `com.symphony.imessage-bridge` launchd), which shells to
  AppleScript. This is the **fallback bridge**, not a replacement — it
  does not do attachments or read receipts.
- x-intake reply-leg live smoke (`.cursor/prompts/2026-04-24-cline-x-intake-reply-leg-evidence-capture.md`)
  depends on outbound BlueBubbles — turning it off blocks that gate.

Emit `ops/verification/${STAMP}-port-api-surface-audit/bluebubbles-surface.txt`:

```bash
# Inbound leg health
curl -sS -m 5 http://127.0.0.1:8102/api/bluebubbles/health | python3 -m json.tool

# Outbound leg reachability (server ping; no message send)
bash scripts/bluebubbles-health.sh --json

# Counters since last reset
curl -sS -m 5 http://127.0.0.1:8102/api/bluebubbles/health \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print({k:d.get(k) for k in ("last_inbound_event","counters","server_version","private_api")})'

# Config snapshot (redacted — don't print the password)
python3 -c 'import json,pathlib
c=json.loads(pathlib.Path("config/bluebubbles_routing.json").read_text())
c.pop("credentials",None)
print(json.dumps(c,indent=2,sort_keys=True))'
```

Confirm:
- inbound webhook last-event timestamp is fresh (< 24h) OR known-idle.
- outbound ping returns `server_version` without needing to send a real
  message.
- `config/bluebubbles_routing.json` `allowed_phones` still contains every
  number that downstream skills expect.
- `BLUEBUBBLES_SERVER_URL` is Tailscale-only (100.x / `.ts.net`), not
  public DNS. If it resolves to a public A record, tag `[NEEDS_MATT]`.

---

## 5. Classification table

Emit `ops/verification/${STAMP}-port-api-surface-audit/classification.md`.
One row per listening port found in steps 1-3. Columns:

| Port | Proto | Bind | Owner (PID/container/plist) | Service | Classification | Evidence link | Recommended action |

`Classification` ∈ { `REQUIRED`, `OPTIONAL`, `STALE`, `UNKNOWN` }.

- `REQUIRED` — disabling breaks a live feature (Cortex, openclaw, x-intake,
  BlueBubbles inbound/outbound, Redis, Docker Desktop internal ports,
  Tailscale, launchd logging sockets).
- `OPTIONAL` — experimental or low-use (x-intake-lab :8103, portfolio-site
  static). Record last-access evidence.
- `STALE` — running but known-decommissioned (context-preprocessor,
  remediator, knowledge-scanner, mission_control per `*/DECOMMISSIONED.md`)
  or no heartbeat in > 7 days.
- `UNKNOWN` — not in `PORTS.md`, not mapped to a launchd plist, not a
  Docker container. Flag `[NEEDS_MATT]`.

`Recommended action` is **advisory only**. Examples:
- "Keep — live feature."
- "Propose disable — stale, no traffic since 2026-04-10. Requires Matt
  approval + rollback plan (see §7)."
- "Investigate — unknown listener on :NNNN."

No action is taken in this prompt.

---

## 6. BlueBubbles-specific recommendation

Based on §4 counters, answer in `classification.md`:

1. Is the inbound webhook live (last event < 24h or a known-quiet window)?
2. Is the outbound leg reachable (ping OK, server_version present)?
3. Is `allowed_phones` populated (otherwise webhooks land but get
   dropped by routing)?
4. Is any downstream skill currently gated on BlueBubbles outbound (check
   `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`
   Status field; if `PRECHECKS_PASSED` or `RUNNING`, disabling is a
   regression)?

If all four are healthy and there is a downstream dependency, the
recommendation is **keep enabled**. Do not propose disabling BlueBubbles
before completing steps 1–5. If Matt later wants to disable it, a
separate prompt must include:
- the rollback plan (exact `launchctl load` / config-restore steps),
- a verification that the AppleScript bridge (`:8199`) is healthy as a
  fallback outbound path,
- a verification that no open `[NEEDS_MATT]` / `[FOLLOWUP]` item in
  `STATUS_REPORT.md` depends on the inbound webhook, and
- confirmation that the BlueBubbles server is **not** publicly exposed
  (Tailscale-only).

---

## 7. Receipt + STATUS_REPORT update

- Receipt: `ops/verification/${STAMP}-port-api-surface-audit/README.md`
  summarizing counts (total listeners, REQUIRED/OPTIONAL/STALE/UNKNOWN),
  the 3-5 most important findings, and links to the four sub-files.
- STATUS_REPORT: append a dated section under "Port & API surface audit
  (${DATE}, Cline)" with the receipt dir path and headline counts. Tag
  every UNKNOWN listener and every public-bind finding as `[NEEDS_MATT]`.
- Commit (single commit): `ops(port-audit): full Bob port/API surface
  snapshot — ${STAMP}`.
- Push `main`. Do **not** open a PR (this is an ops receipt, not a code
  change), unless the repo convention on this date requires PRs for
  main (check `CLAUDE.md` / `AGENTS.md` at run time).

---

## Bounded-check checklist (what must appear in evidence)

- [ ] `lsof -nP -iTCP -sTCP:LISTEN` full output captured
- [ ] `docker ps` + `docker compose ps` port columns captured
- [ ] `launchctl list | grep -E 'symphony|bob|bluebubbles'` captured
- [ ] Per-port owner mapping (PID → container/plist) resolved for
      every row, or explicitly marked `UNKNOWN`
- [ ] Loopback vs LAN vs Tailscale-only classification done
- [ ] `PORTS.md` drift called out (registry vs reality)
- [ ] BlueBubbles inbound `/hooks/bluebubbles` health checked
- [ ] BlueBubbles outbound ping checked (no real send)
- [ ] `config/bluebubbles_routing.json` allowlist reviewed
- [ ] `BLUEBUBBLES_SERVER_URL` confirmed Tailscale-only
- [ ] Classification table emitted with Required/Optional/Stale/Unknown
- [ ] STATUS_REPORT updated with receipt dir path
- [ ] Receipt committed + pushed under stamp-prefixed commit

## Hard "do not" list

- No `docker stop`, `docker restart`, `docker compose down`, or image
  rebuilds.
- No `launchctl unload`, `launchctl bootout`, plist deletion, or plist
  edits.
- No firewall / pf / `socketfilterfw` changes.
- No `.env` mutation, no secret rotation, no external sends (email,
  iMessage, Telegram, webhooks).
- No BlueBubbles Private API toggle, no BlueBubbles password change.
- No "clean up unknown listener" actions in this pass — only document.
- Anything requiring `sudo` that is not already passwordless: record
  `N/A: needs-matt` and stop, do not escalate.
