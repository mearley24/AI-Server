# Tailscale Access — Cortex & Symphony Tools

**Last updated:** 2026-04-24
**Scope:** how to reach Bob (the Mac Mini) and the Symphony tool suite over
Tailscale from another device (laptop, phone, iPad) joined to the same
tailnet. Read-only document — does not change Tailscale configuration.

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

Verified against `PORTS.md` on 2026-04-24:

| Tool                | Local URL                        | Tailscale URL                                           | Notes |
|---------------------|----------------------------------|---------------------------------------------------------|-------|
| Cortex Dashboard    | `http://127.0.0.1:8102/dashboard`| `http://100.89.1.51:8102/dashboard`                      | Currently binds `*:8102` — audit item (see below). |
| OpenClaw            | `http://127.0.0.1:8099/`         | `http://100.89.1.51:8099/`                               | Central LLM orchestration. |
| Cortex Autobuilder  | `http://127.0.0.1:8115/`         | `http://100.89.1.51:8115/`                               | Bob/Betty research loop. |
| X-Intake            | `http://127.0.0.1:8101/`         | `http://100.89.1.51:8101/`                               | Review queue for bookmarked X links. |
| Proposals           | `http://127.0.0.1:8091/`         | `http://100.89.1.51:8091/`                               | Symphony proposal engine. |
| Notification Hub    | `http://127.0.0.1:8095/`         | `http://100.89.1.51:8095/`                               | Alerts / routing. |
| Intel Feeds         | `http://127.0.0.1:8765/`         | `http://100.89.1.51:8765/`                               | News + Polymarket monitors. |
| BlueBubbles         | `http://127.0.0.1:1234/`         | `http://100.89.1.51:1234/`                               | Host-bound, LAN/Tailscale reachable. |
| Markup Tool         | `http://127.0.0.1:8088/`         | *(not reachable by default — see below)*                 | Bound `127.0.0.1:8088` only. |
| iMessage Bridge     | `http://127.0.0.1:8199/`         | *(not reachable by default)*                             | Bound `127.0.0.1:8199` only. |
| Mobile Gateway      | *(not yet documented)*           | *(not yet documented)*                                   | Port TBD — add to `TOOL_REGISTRY` once confirmed. |

### Why some tools aren't Tailscale-reachable

Per `PORTS.md`, a subset of services intentionally bind to `127.0.0.1`:
Markup Tool (`8088`), iMessage Bridge (`8199`), trading-api (`8421`),
Ollama (`11434`), vault-pwa (`8801`), file-watcher / Cortex intake (`8103`).

These are not reachable over Tailscale unless you explicitly publish them
with `tailscale serve`. **This pass does not change any binding.** If you
want Markup accessible on your phone via Tailscale, the supported path is:

```bash
# On Bob:
tailscale serve --bg --https=443 http://localhost:8088
tailscale serve status
```

…then use the HTTPS URL Tailscale prints. Keep in mind `tailscale serve`
exposes the tool to **every device on your tailnet** — that's fine for a
solo tailnet but review ACLs before running it in a shared one.

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
curl -sS http://127.0.0.1:8102/health
curl -sS http://100.89.1.51:8102/health
```

If `lsof` shows a service bound to `*:<port>` (wildcard) when `PORTS.md`
says it should be `127.0.0.1`, that's an audit item — investigate before
shipping network changes.

## Verifying access from a remote device

From a laptop or phone joined to the tailnet:

```bash
# Basic reachability
ping 100.89.1.51
tailscale ping bobs-mac-mini

# Health check via Tailscale
curl -sS http://bobs-mac-mini.tailbcf3fe.ts.net:8102/health
curl -sS http://100.89.1.51:8102/health
```

Browser: open `http://bobs-mac-mini.tailbcf3fe.ts.net:8102/dashboard`
(or the raw IP equivalent). The Cortex dashboard's **Tool Access** card
provides one-click links on every tab.

## Known audit items (do not fix in this pass)

- **`*:8102` wildcard listener.** A port audit on 2026-04-24 flagged
  Cortex listening on `*:8102` rather than `127.0.0.1:8102`. Because
  Tailscale brings up its own interface (`utun*`), a wildcard bind means
  Cortex is reachable on every interface of the host — LAN, Tailscale,
  and any future VPN. For a solo tailnet this is usually acceptable;
  tighten it (bind `100.89.1.51` + `127.0.0.1` only, or use
  `tailscale serve`) before exposing the host on an untrusted LAN.
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
