<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. Do not print secrets. Do not send external messages. Do not enable launchd jobs or Docker services in this run. -->

<!-- autonomy: start -->
Category: ops
Risk tier: low
Trigger:   manual
Status:    active
<!-- autonomy: end -->

# Network Monitoring v2 — Visibility Audit & Architecture Design (Bob, Cline-first)

## Goal

Produce an **audit + design** for Network Monitoring v2 that treats
`tools/network_guard_daemon.py`, `tools/network_dropout_watch.py`,
`setup/nodes/node_health_monitor.py`, `api/host_modules/network.py`,
`setup/launchd/com.symphony.network-guard.plist`,
`data/network_guard_*`, `data/network_watch/*`, and
`knowledge/network/*` as the source of truth.

This run is **design only**. Do NOT implement the new monitor, do NOT
load launchd jobs, do NOT start Docker services, do NOT send messages,
do NOT print or decode secrets.

Deliverables (all in-repo, committed):

1. `docs/audits/network-monitoring-v2-visibility-audit.md` — what Bob
   can actually see on macOS, on this LAN, with the current tooling.
2. A Phase-1 implementation prompt at
   `.cursor/prompts/implement-network-monitoring-v2-phase-1.md`
   (skeleton only; leave concrete commands for the next run).
3. A verification artifact under `ops/verification/` named
   `YYYYMMDD-HHMMSS-network-monitoring-v2-audit.txt` capturing the
   bounded command output used to reach the conclusions.
4. A `STATUS_REPORT.md` entry linking to 1–3.
5. Commit + push to `origin/main`.

## Preconditions

Read these before doing anything else:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`
  (the immediately-prior run; don't duplicate its Phase-1 work)
- `docs/audits/2026-04-23-unfinished-setup-audit.md`
- `STATUS_REPORT.md` (last ~200 lines only)

Read the source-of-truth components (headers + CLI only; do not dump
secrets, do not print `data/network_guard_*` contents in full):

- `tools/network_guard_daemon.py`
- `tools/network_dropout_watch.py`
- `setup/nodes/node_health_monitor.py`
- `api/host_modules/network.py`
- `setup/launchd/com.symphony.network-guard.plist`
- `knowledge/network/client_registry.json` (structure only; redact IPs
  and MACs in the audit doc — use `xx:xx:xx:…` / `10.x.x.N`)
- `knowledge/network/ip_addressing_standard.md`
- `knowledge/network/device_count_analysis.md`
- `data/network_watch/` (listing only — file names + sizes + mtimes;
  do not cat event payloads into the audit)
- `data/network_guard_*` (listing only; same rule)

Confirm host + repo:

```
hostname
pwd
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
```

If `hostname` is not Bob or `git status` is dirty in unexpected ways,
stop and report. Do not proceed.

## Step 1 — Visibility audit (Bob, macOS-native)

Goal: answer "what can Bob actually see on this LAN right now?" with
evidence, not assumptions. **Docker containers on macOS cannot sniff
the host LAN** — do not design around that assumption.

Record every command + its bounded output into the verification
artifact. Use `timeout`, `-c N`, `--lines`, `head`, `sed -n` to keep
output small. Never use `tail -f`, `-w`, `--watch`, or interactive
capture.

Bounded checks to run (add more only if they stay bounded):

1. Active interface + link state:
   - `route -n get default`
   - `ifconfig en0` (and whichever interface `route` returned)
   - `networksetup -listallhardwareports`
   - `networksetup -getinfo "Wi-Fi"` (redact password fields if any
     appear — they should not)
2. Baseline reachability + latency:
   - `ping -c 5 -W 1000 <default-gateway>`
   - `ping -c 5 -W 1000 1.1.1.1`
   - `ping -c 5 -W 1000 8.8.8.8`
   - `traceroute -n -w 1 -q 1 -m 8 1.1.1.1`
3. Passive listen capability (determines hybrid design):
   - `sudo -n tcpdump -D` — can Bob enumerate interfaces? If `sudo -n`
     fails, record "needs one-time sudoers grant" as a bump; do NOT
     edit sudoers in this run.
   - `sudo -n timeout 10 tcpdump -i <iface> -c 50 -nn 'udp port 5353'`
     (mDNS) — count packets, redact payloads
   - `sudo -n timeout 10 tcpdump -i <iface> -c 50 -nn 'udp port 1900'`
     (SSDP)
   - `sudo -n timeout 10 tcpdump -i <iface> -c 50 -nn 'udp port 67 or udp port 68'`
     (DHCP) — DHCP unicast-to-server is frequently invisible to a
     non-router host; record what you actually see
   - `sudo -n timeout 10 tcpdump -i <iface> -c 100 -nn 'multicast and not (port 5353 or port 1900)'`
     (other multicast — mDNS/SSDP already counted)
   - Unicast between *other* LAN devices: on a switched LAN Bob will
     NOT see A↔B unicast. Confirm with a short capture filtered to
     `not host <bob-ip>` and record count (should be ~0 for unicast
     unless broadcast/multicast).
4. ARP + neighbor table (redacted):
   - `arp -an` (redact MACs + last octet of IPs in the doc)
   - `ndp -an` if IPv6 is active
5. Router / switch management plane — **discovery only, no login**:
   - Is the gateway web UI reachable? `curl -sS -o /dev/null -w '%{http_code}\n' --max-time 3 http://<gw>/`
   - Is SNMP open? `nc -z -u -w 2 <gw> 161` (record result; do NOT
     send SNMP queries or guess community strings).
   - Is there a known managed switch? Check `knowledge/network/` for
     any mention of switch model / SPAN / mirror port. If unknown,
     record as a gap.
6. What the existing stack already emits:
   - `ls -lah data/network_watch/ | head`
   - `ls -lah data/ | grep network_guard | head`
   - `wc -l data/network_watch/*.jsonl 2>/dev/null | tail -n +1 | head`
   - Head 5 lines of the newest `events.jsonl`-style file **with
     structural redaction** (keys only, values replaced by `<redacted>`)
     so the audit shows schema without leaking identifiers.
   - `launchctl print gui/$(id -u)/com.symphony.network-guard 2>&1 | head -40`
     (observe-only; do not load/unload)

For every check, write one sentence in the audit doc: **what we
learned**, not a raw command dump. The raw dump belongs in the
`ops/verification/` artifact.

## Step 2 — Inventory endpoints + dashboard hooks

Grep the repo (bounded) for what already exposes network health and
where a UI would hook in. Record findings in the audit doc as a table.

- Endpoints: `grep -RIn --include='*.py' -E 'network|dropout|guard' api/ | head -80`
- Dashboard widgets / Cortex tiles: `grep -RIn -E 'network|NetStatus|dropout' dashboard/ cortex/ 2>/dev/null | head -80` (adjust paths to whatever exists)
- Existing `/network-status` or similar: `grep -RIn -E '/network[-_]?status|network_status' api/ dashboard/ 2>/dev/null | head`
- CLI entrypoints: `grep -RIn 'if __name__' tools/network_*.py`

Outcome: a list of what already exists and a short proposal for:

- A read-only `/network-status` JSON endpoint if none exists (schema
  sketch only — do not implement).
- A Cortex / mission-control widget surface that consumes it.

## Step 3 — Propose hybrid architecture

The audit doc must include an **architecture** section with:

- **macOS-native sensor layer** (runs on Bob directly, not in Docker):
  packet/event capture via `tcpdump` or BPF, ping/latency probes, mDNS
  observer, ARP-table delta watcher. This is where actual LAN
  visibility lives.
- **Docker / API / Cortex presentation layer**: consumes the sensor's
  JSONL event stream + rolled-up metrics; serves `/network-status`;
  renders the dashboard widget. Docker does NOT sniff the LAN.
- **Optional add-ons** (gated on Step 1 evidence): `ntopng` or
  `netdata` only if the visibility audit shows they would actually see
  more than what we already capture — otherwise call them out as
  "deferred pending SPAN/mirror port or router API access."

Include a simple ASCII diagram: sensor (Bob-native, launchd) →
JSONL + rollup files under `data/network_monitor/` → API module →
dashboard widget + alerting hook.

## Step 4 — Event schema + retention + alerting

Define (in the audit doc) for `data/network_monitor/events.jsonl`:

- Fields: `ts` (ISO8601 UTC), `severity` (`info|warn|error|critical`),
  `category` (`latency|loss|multicast|dhcp|device_flap|arp_change|…`),
  `source` (sensor component), `iface`, `summary` (<=140 chars),
  `details` (bounded JSON object), `dedupe_key`.
- Capture directory: `data/network_monitor/captures/` for short
  rotating pcap snippets (size-bounded, e.g., 10 × 5 MB), explicitly
  gitignored.
- Retention: events 30 days, captures 24 hours, rollup summaries kept.
- Dedupe + cooldown: same `dedupe_key` suppressed for N minutes (N
  per severity).
- Alerting: one-message-per-incident via the existing alert channel,
  with reply-options only if the current reply-actions surface
  supports it (cite the file; do NOT add a new surface here).

## Step 5 — Specific checks to enumerate

For each, state **visibility prerequisite** in the audit (what Step 1
proved / disproved) before marking it in/out of Phase 1:

- Multicast storms — visible from Bob: yes/no (mDNS + SSDP baseline
  rate established in Step 1).
- Bandwidth / top talkers — include **only if** SPAN / mirror / router
  API is available. Otherwise deferred.
- Packet loss + latency — always in scope (ping-based, Bob-native).
- DHCP churn — only if DHCP traffic is actually visible to Bob
  (Step 1.3 DHCP capture). Otherwise deferred to router-API path.
- Device flaps — ARP-table delta watcher is Bob-visible; scope in.
- Switch / port instability — deferred unless managed switch API /
  SNMP is reachable (Step 1.5).

## Step 6 — Outputs to write

1. `docs/audits/network-monitoring-v2-visibility-audit.md` —
   sections: Summary, Existing stack inventory, Visibility evidence
   (from Step 1, redacted), Endpoints + dashboard hooks, Proposed
   hybrid architecture (with ASCII diagram), Event schema + retention
   + alerting, Per-check scope table, Bumps / risks / [NEEDS_MATT],
   Phase-1 prompt path, Verification artifact path.
2. `.cursor/prompts/implement-network-monitoring-v2-phase-1.md` —
   skeleton prompt only: goal, preconditions, scoped steps that flow
   from this audit, explicit `[NEEDS_MATT]` gates (sudoers for
   tcpdump, launchd arm, router/switch creds). **Do not prefill
   commands that depend on Step 1 outcomes** — leave TODO markers
   referencing the audit doc.
3. `ops/verification/YYYYMMDD-HHMMSS-network-monitoring-v2-audit.txt`
   — raw bounded command outputs from Step 1, redacted.
4. `STATUS_REPORT.md` — one entry at the top linking to the three
   files above and the commit hash.

## Step 7 — Guardrails (hard)

- No `tail -f`, no `--watch`, no interactive editors, no heredocs.
- No `sudo` that edits sudoers, no `launchctl load|bootstrap|kickstart`
  for network-guard or any new job.
- No `docker compose up`, no starting/stopping containers.
- No external sends (no curl to Slack/Discord/SMS/email APIs).
- Redact MACs, full IPs, SSIDs, BSSIDs, and any device identifier
  tied to a person in the committed docs. The verification artifact
  may keep redacted-but-structurally-useful values; check before
  commit.
- If a command requires creds you don't have, mark `[NEEDS_MATT]` in
  the audit and move on.

## Step 8 — Commit + push

- `git add` only the four output paths above.
- Commit message: `docs(network-v2): visibility audit + hybrid architecture design`.
- `git push origin main`.
- Record commit hash in STATUS_REPORT entry and in the final report.

## Final report (printed to stdout at end)

Must include:

1. What is already in place (one-paragraph synthesis of the existing
   stack inventory).
2. What Bob can actually see (bullet list from Step 1 evidence).
3. Recommended architecture (two or three sentences).
4. Bumps / risks / `[NEEDS_MATT]` items.
5. Phase-1 implementation prompt path.
6. Verification artifact path.
7. Commit hash + `git push` result line.
