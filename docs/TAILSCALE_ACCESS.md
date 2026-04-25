# Tailscale Access — Cortex & Symphony Tools

**Last updated:** 2026-04-24 (post wildcard-listener fix)
**Scope:** how to reach Bob (the Mac Mini) and the Symphony tool suite over
Tailscale from another device (laptop, phone, iPad) joined to the same
tailnet. Read-only document — does not change Tailscale configuration.

> **2026-04-24 update.** The `*:8102` wildcard listener flagged by the
> 2026-04-24 port audit was **not** Cortex — it was the host
> `com.symphony.file-watcher` agent accidentally binding the same port
> LAN-wide. It has been rebound to `127.0.0.1:8103` (loopback only). As a
> result, every Docker-backed Symphony service now binds **loopback only**
> on Bob; direct Tailscale URLs (e.g. `http://100.89.1.51:8102/…`) no
> longer work. Use `tailscale serve` or an SSH tunnel to reach them —
> see the “How to actually reach a loopback tool” section below.

## Bob's Tailscale identifiers

| Field         | Value                                  |
|---------------|-----------------------------------------|
| Machine name  | `bobs-mac-mini`                         |
| Tailscale IP  | `100.89.1.51`                           |
| MagicDNS FQDN | `bobs-mac-mini.tailbcf3fe.ts.net`       |

Prefer MagicDNS in bookmarks (it survives Tailscale IP reassignment);
prefer the raw IP when debugging DNS issues.

## Tool access cheat sheet

Cortex now surfaces a machine-readable registry at
`GET /api/tools` (filterable with `?tab=overview|xintake|symphony|autonomy`).
The dashboard's **Tool Access** card on each tab is rendered from that
endpoint — edit `TOOL_REGISTRY` in `cortex/dashboard.py` to add or retarget
a tool, no frontend change required.

Verified against `PORTS.md` and the 2026-04-24 port audit
(`ops/verification/20260424-182340-port-api-surface-audit/`):

| Tool                | Local URL                        | Tailscale URL (default)                                 | Notes |
|---------------------|----------------------------------|---------------------------------------------------------|-------|
| Cortex Dashboard    | `http://127.0.0.1:8102/dashboard`| *(not reachable by default — needs `tailscale serve`)*   | Docker-bound `127.0.0.1:8102`. |
| OpenClaw            | `http://127.0.0.1:8099/`         | *(not reachable by default)*                             | Docker-bound `127.0.0.1:8099`. |
| Cortex Autobuilder  | `http://127.0.0.1:8115/`         | *(not reachable by default)*                             | Docker-bound `127.0.0.1:8115`. |
| X-Intake            | `http://127.0.0.1:8101/`         | *(not reachable by default)*                             | Docker-bound `127.0.0.1:8101`. |
| Proposals           | `http://127.0.0.1:8091/`         | *(not reachable by default)*                             | Docker-bound `127.0.0.1:8091`. |
| Notification Hub    | `http://127.0.0.1:8095/`         | *(not reachable by default)*                             | Docker-bound `127.0.0.1:8095`. |
| Intel Feeds         | `http://127.0.0.1:8765/`         | *(not reachable by default)*                             | Docker-bound `127.0.0.1:8765`. |
| BlueBubbles         | `http://127.0.0.1:1234/`         | `http://100.89.1.51:1234/`                               | Host-bound, LAN/Tailscale reachable. |
| Markup Tool         | `http://127.0.0.1:8088/`         | *(not reachable by default)*                             | Bound `127.0.0.1:8088` only. |
| iMessage Bridge     | `http://127.0.0.1:8199/`         | *(not reachable by default)*                             | Bound `127.0.0.1:8199` only. |
| Voice Receptionist  | `http://127.0.0.1:8093/health`   | *(not reachable by default)*                             | Bob the Conductor (Twilio + OpenAI Realtime). Container 3000 → host 127.0.0.1:8093. |
| Mobile Gateway      | *(not yet documented)*           | *(not yet documented)*                                   | Port TBD — add to `TOOL_REGISTRY` once confirmed. |

The dashboard's `/api/tools` payload keeps a `tailscale_url` field for each
tool because the UI still shows it, but any entry with `status="lan_only"`
(most of them) means that URL only works **after** you publish the tool
via `tailscale serve` on Bob. See below.

### How to actually reach a loopback tool from Tailscale

Every Docker-backed Symphony service, plus the host-bound utilities
(Markup `8088`, iMessage Bridge `8199`, trading-api `8421`, Ollama
`11434`, vault-pwa `8801`, file-watcher `8103`), binds `127.0.0.1` only.
A raw Tailscale URL like `http://100.89.1.51:8102/dashboard` will time
out — Tailscale IPs live on Bob's `utun*` interface, and a
`127.0.0.1`-bound socket isn't listening there. Two supported paths:

**Option A — `tailscale serve` (recommended; TLS):**

```bash
# On Bob: publish the Cortex dashboard over Tailscale HTTPS
tailscale serve --bg --https=443 http://localhost:8102
tailscale serve status
# Use the HTTPS URL Tailscale prints (e.g.
#   https://bobs-mac-mini.tailbcf3fe.ts.net/ )
```

`tailscale serve` terminates TLS with a Let's Encrypt cert, rewrites
onto the loopback port, and exposes the tool to **every device on your
tailnet** (ACL-reviewed). One port at a time per scheme; use `--https=`
for different ports, or different path prefixes for multiple tools
behind one hostname. See `docs/bluebubbles/build_bluebubbles_guide.py`
for a worked BlueBubbles example.

**Option B — SSH tunnel (ad-hoc, no Bob config change):**

```bash
# From your laptop/phone client:
ssh -L 8102:127.0.0.1:8102 bob@bobs-mac-mini.tailbcf3fe.ts.net
# Then open http://127.0.0.1:8102/dashboard in your local browser.
```

Good for one-off debugging; not good for a phone bookmark.

## Verifying access from Bob

Run these on Bob itself to confirm what's actually listening and how:

```bash
# Which ports are open and on which interface?
lsof -iTCP -sTCP:LISTEN -P -n | grep -E "8102|8099|8101|8091|8088|8095|8765"

# Does the Tailscale IP actually resolve to this machine?
tailscale ip -4               # expect 100.89.1.51
tailscale status | head -5

# Are any tools published via tailscale serve / funnel?
tailscale serve status

# Health-check a tool end-to-end (Cortex):
curl -sS http://127.0.0.1:8102/health              # works — loopback bind
curl -sS http://100.89.1.51:8102/health            # expected to hang/fail
                                                   # unless `tailscale serve`
                                                   # is publishing :8102
```

If `lsof` shows a service bound to `*:<port>` (wildcard) when `PORTS.md`
says it should be `127.0.0.1`, that's an audit item — investigate before
shipping network changes. (The 2026-04-24 `*:8102` finding was
`com.symphony.file-watcher`, rebound to `127.0.0.1:8103` — see **Known
audit items** below.)

## Verifying access from a remote device

From a laptop or phone joined to the tailnet:

```bash
# Basic reachability
ping 100.89.1.51
tailscale ping bobs-mac-mini

# Health check via Tailscale — expected to FAIL for Docker services
# (Cortex/OpenClaw/etc) unless `tailscale serve` has been configured
# on Bob. BlueBubbles on :1234 is the only Symphony tool that responds
# here by default (it binds all interfaces on the host).
curl -sS http://bobs-mac-mini.tailbcf3fe.ts.net:1234/api/v1/server/info
# If `tailscale serve` is set up for Cortex, use the HTTPS URL it prints
# rather than the raw :8102 URL.
```

Browser: `http://bobs-mac-mini.tailbcf3fe.ts.net:8102/dashboard` will
**not** work out of the box — Cortex binds `127.0.0.1:8102`. Either
publish it with `tailscale serve` (see above) or reach it by SSH tunnel.
The Cortex dashboard's **Tool Access** card still renders the raw
Tailscale URL so it can become live the moment `tailscale serve` is
configured.

## Known audit items

- **`*:8102` wildcard listener.** ✅ **Resolved 2026-04-24.** The `*:8102`
  wildcard flagged by the 2026-04-24 port audit was
  `com.symphony.file-watcher` (PID 962), not Cortex — it had been
  accidentally bound on the same port LAN-wide. It is now rebound to
  `127.0.0.1:8103` (loopback only). Evidence:
  `ops/verification/20260424-182340-port-api-surface-audit/classification.md`
  and the `STATUS_REPORT.md` "Port & API Surface Audit" closure lines.
  Cortex itself has always bound `127.0.0.1:8102` via Docker; no Cortex
  binding changed.
- **No auth on Cortex dashboard.** The dashboard has no login. Tailscale
  is the trust boundary. If you ever add non-Tailscale exposure (funnel,
  port-forward, reverse proxy), add auth first.

## Changing the registry

Edit `TOOL_REGISTRY` in `cortex/dashboard.py`. The `_tool()` helper takes:

```python
_tool(
    name="My Tool",
    port=8123,
    tab="symphony",           # overview | xintake | symphony | autonomy
    category="Business",
    health_path="/health",    # optional
    local_path="/",           # optional — appended to the URL
    notes="Short description of what it is and any caveats.",
    status="ok",              # ok | unknown | lan_only
)
```

Entries with `status="unknown"` render in the UI with the Tailscale link
disabled — use this when a port isn't yet documented in `PORTS.md`.

## Rollback

The entire change is contained to:

- `cortex/dashboard.py` — new `TOOL_REGISTRY`, `_tool()` helper,
  `/api/tools` endpoint (additive; removes nothing).
- `cortex/static/index.html` — four new `<div class="card">` blocks for
  the Tool Access panels.
- `cortex/static/dashboard.css` — `.tool-list` + `.tool-row` rules.
- `cortex/static/dashboard.js` — `loadToolAccess()` + two call sites.
- `ops/tests/test_dashboard_assets.py` — extended with tool-access tests.
- `docs/TAILSCALE_ACCESS.md` — this file.

To roll back: `git revert` the commit. No data migrations, no binding
changes, no systemd / launchd changes — nothing to undo on the host.
