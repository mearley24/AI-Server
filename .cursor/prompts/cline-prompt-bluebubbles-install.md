# Cline Autorun — BlueBubbles Install (Bob + Bert + Cortex Dashboard Tile)

> **Cline:** read this file top to bottom. Operate in **Plan → Act**. Restate the goal, post a short plan, then execute without further prompting unless a Guardrail (§7) triggers. After each tool use, summarize in ≤3 bullets. When done, produce the Final Report in §8.
>
> `AUTO_APPROVE = true`. Read `.clinerules`, `CLAUDE.md`, `STATUS_REPORT.md`, and `docs/bluebubbles/build_bluebubbles_guide.py` (the canonical install guide — follow its architecture) before starting.

---

## 1. Role & Operating Mode

You are Cline, autonomous coding agent running across two Macs on the same Tailscale tailnet:

- **Bob** — Mac Mini M4, always-on, iMessage-signed-in, `/Users/bob/AI-Server`. **Primary install target.**
- **Bert** — M2 MacBook Pro, `/Users/bert/…` (confirm actual path). **Client-only.** Also on Tailscale.

You have terminal + Docker + git + Homebrew access on both hosts. You may `ssh` into Bert from Bob using the existing tailnet SSH config (confirm with `ssh bert.<tailnet>.ts.net echo ok` — if that fails, pause and ask the user to run the Bert-side steps manually). Use conventional commits only (`feat:`, `fix:`, `docs:`, `chore:`, `ops:`). Never invent paths; verify with `read_file` / `ls` first.

## 2. Objective

Stand up a working, TLS-secured, Tailscale-only BlueBubbles server on Bob, install the BlueBubbles Desktop client on Bert, and surface server health in the Cortex dashboard's Symphony Ops tab. End state:

1. `BlueBubbles.app` installed and running on Bob, listening on `:1234` loopback, reachable at `https://bob.<tailnet>.ts.net/` via **Tailscale serve** (HTTPS on the tailnet, **NOT** Tailscale Funnel — do not expose publicly).
2. API passphrase generated (24+ chars, `openssl rand -base64 24`), stored in `~/.config/bluebubbles/credentials` (mode 600), and mirrored into `/Users/bob/AI-Server/.env` as `BLUEBUBBLES_API_PASSWORD` and `BLUEBUBBLES_SERVER_URL`.
3. BlueBubbles Private API helper installed (plugin into Messages.app) so tapbacks/reactions/editing work.
4. A launchd watchdog (`com.symphony.bluebubbles-watchdog.plist`) that relaunches BlueBubbles.app if it quits.
5. `BlueBubbles Desktop` installed on Bert, configured to point at `https://bob.<tailnet>.ts.net/` with the shared passphrase, verified by sending a test iMessage round-trip to `OWNER_PHONE_NUMBER`.
6. A new **BlueBubbles** tile on the Cortex dashboard (Symphony Ops tab) mirroring the Markup Tool tile pattern — shows `online`/`offline` plus the Tailscale URL. Backed by a new `/api/symphony/bluebubbles/health` proxy.
7. Existing `scripts/imessage-server.py` on `:8199` continues to work untouched. BlueBubbles runs **alongside** it, not as a replacement.

## 3. Environment & Pre-flight

### 3.1 Read first (do not skip)

- `.clinerules`, `CLAUDE.md`, `STATUS_REPORT.md`
- `docs/bluebubbles/build_bluebubbles_guide.py` — the canonical architecture document
- `cortex/dashboard.py` — see `symphony_markup_health`-adjacent endpoints + `PROPOSALS_URL` pattern as the model for the new BlueBubbles proxy (around lines 1060–1090)
- `cortex/static/index.html` — the Markup Tool tile at lines ~475–494 and `checkMarkupHealth()` at ~1362 are the template for the BlueBubbles tile
- `ops/launchd/com.symphony.markup-tool.plist` — existing plist to mirror
- `.env.example` — where to add the two new env vars

### 3.2 Pre-flight checks on Bob

```bash
cd /Users/bob/AI-Server
git pull --ff-only

# P1. Confirm Bob is signed into iMessage (the check the guide specifies)
osascript -e 'tell application "Messages" to return name of first account' \
  || { echo "FAIL: Messages.app not signed in — pause and report"; exit 1; }

# P2. Confirm Tailscale up + MagicDNS enabled
tailscale status | head -5
tailscale ip -4
BOB_TAILNET_NAME=$(tailscale status --json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["Self"]["DNSName"].rstrip("."))')
echo "Bob tailnet DNS: $BOB_TAILNET_NAME"
[ -n "$BOB_TAILNET_NAME" ] || { echo "FAIL: no MagicDNS — stop"; exit 1; }

# P3. Confirm Homebrew
command -v brew || { echo "FAIL: Homebrew missing"; exit 1; }

# P4. Confirm the four macOS permissions BlueBubbles needs (the guide §2 list).
#     We cannot toggle TCC from a script without an MDM profile — print the
#     current status and instruct the user to click-through if anything is RED.
#     Use `tccutil reset` ONLY if the user approves; default is just to report.
sqlite3 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" \
  "SELECT service, client, auth_value FROM access WHERE client LIKE '%BlueBubbles%' OR client LIKE '%Messages%' OR client LIKE '%Contacts%';" \
  2>/dev/null || echo "TCC.db not readable from this shell — acceptable, proceed"

# P5. Confirm iMessage bridge on :8199 is still running (we must not break it)
curl -sf http://127.0.0.1:8199/health && echo "existing imessage bridge OK" \
  || echo "WARN: existing :8199 bridge not responding — note in Final Report but continue"

# P6. Confirm Bert reachable
BERT_TAILNET_NAME=$(tailscale status --json | python3 -c '
import sys, json
d = json.load(sys.stdin)
for p in d["Peer"].values():
    if p.get("HostName","").lower().startswith("bert"):
        print(p["DNSName"].rstrip("."))
        break
')
echo "Bert tailnet DNS: $BERT_TAILNET_NAME"
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    "$BERT_TAILNET_NAME" 'echo bert-ssh-ok' \
  || echo "WARN: Bert not SSH-reachable — Phase D will require manual run on Bert"
```

## 4. Step Plan

### Phase A — Install BlueBubbles Server on Bob

```bash
# A1. Install via Homebrew cask (reproducible, versioned)
brew install --cask bluebubbles

# A2. Launch once headlessly so it creates ~/Library/Application Support/BlueBubbles/
open -a BlueBubbles
sleep 8

# A3. Confirm it registered a port (default 1234)
lsof -iTCP:1234 -sTCP:LISTEN | head -3 \
  || { echo "BlueBubbles didn't start listening — abort"; exit 1; }
```

### Phase B — Generate and store the API passphrase

```bash
# B1. Generate 24-byte base64 passphrase
mkdir -p "$HOME/.config/bluebubbles"
chmod 700 "$HOME/.config/bluebubbles"
BB_PASS_FILE="$HOME/.config/bluebubbles/credentials"
if [ ! -f "$BB_PASS_FILE" ]; then
  umask 077
  BB_PASS=$(openssl rand -base64 24)
  printf 'BLUEBUBBLES_API_PASSWORD=%s\n' "$BB_PASS" > "$BB_PASS_FILE"
  chmod 600 "$BB_PASS_FILE"
  echo "Generated new BlueBubbles passphrase (${#BB_PASS} chars)"
else
  BB_PASS=$(grep '^BLUEBUBBLES_API_PASSWORD=' "$BB_PASS_FILE" | cut -d= -f2-)
  echo "Using existing passphrase"
fi

# B2. Configure BlueBubbles Server to use this passphrase via its CLI or plist.
#     BlueBubbles writes settings to ~/Library/Application Support/BlueBubbles/config.json
#     Patch it atomically:
BB_CFG="$HOME/Library/Application Support/BlueBubbles/config.json"
python3 - <<PY
import json, os, shutil
from pathlib import Path
cfg_path = Path(os.path.expanduser("~/Library/Application Support/BlueBubbles/config.json"))
cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
cfg["password"] = os.environ["BB_PASS"]  # BlueBubbles key is "password"
cfg["use_custom_certificate"] = False    # TLS handled by Tailscale serve, not BB itself
cfg["server_port"] = 1234
cfg["use_ngrok"] = False                 # NEVER use ngrok
cfg["use_cloudflare"] = False            # NEVER use cloudflare tunnel
cfg["use_local_tunnel"] = False
cfg["proxy_service"] = "Dynamic DNS"     # Tailscale MagicDNS counts as dynamic DNS
cfg["server_address"] = f"https://{os.environ['BOB_TAILNET_NAME']}"
tmp = cfg_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
shutil.move(tmp, cfg_path)
print("config.json patched:", cfg_path)
PY

# B3. Restart BlueBubbles to pick up the new config
osascript -e 'tell application "BlueBubbles" to quit' 2>/dev/null
sleep 3
open -a BlueBubbles
sleep 8
```

### Phase C — Wire Tailscale serve (HTTPS on tailnet, not Funnel)

```bash
# C1. Stop any prior tailscale serve config on 443 that's not us
sudo tailscale serve status || true
sudo tailscale serve reset

# C2. Serve HTTPS 443 → http://localhost:1234 on the tailnet ONLY
sudo tailscale serve --bg --https=443 http://localhost:1234

# C3. Confirm — this MUST return a Funnel=false line
sudo tailscale serve status

# C4. End-to-end TLS check (from Bob itself; hits the real Tailscale cert)
curl -sf "https://$BOB_TAILNET_NAME/api/v1/server/info" \
  -H "password: $BB_PASS" | python3 -m json.tool | head -20

# C5. Mirror creds into AI-Server .env (never commit the actual password)
cd /Users/bob/AI-Server
if ! grep -q '^BLUEBUBBLES_API_PASSWORD=' .env 2>/dev/null; then
  printf '\n# BlueBubbles — populated by install prompt\n' >> .env
  printf 'BLUEBUBBLES_API_PASSWORD=%s\n' "$BB_PASS" >> .env
  printf 'BLUEBUBBLES_SERVER_URL=https://%s\n' "$BOB_TAILNET_NAME" >> .env
fi
# Ensure .env is gitignored (it already is, confirm)
grep -q '^\.env$' .gitignore || echo ".env" >> .gitignore
```

### Phase D — Install Private API helper

BlueBubbles' Private API requires injecting a dylib into Messages.app. The app has a built-in installer (Settings → Private API → Install). Since that's a GUI click, do this:

```bash
# D1. Open the settings page to the Private API section via deep link if supported;
#     otherwise, print instructions and pause.
osascript -e 'tell application "BlueBubbles" to activate'

cat <<'EOF'

┌─ MANUAL STEP (Bob) ───────────────────────────────────────────────┐
│ 1. BlueBubbles → Settings → Private API                           │
│ 2. Click "Install Helper"                                         │
│ 3. Authorize with admin password when prompted                    │
│ 4. Confirm the toggle flips to "Installed ✓"                      │
│ 5. Messages.app will restart automatically                        │
└───────────────────────────────────────────────────────────────────┘

EOF

# D2. After user confirms, verify via the API
read -p "Press Enter once Private API shows Installed..."
curl -sf "https://$BOB_TAILNET_NAME/api/v1/server/info" \
  -H "password: $BB_PASS" | python3 -c '
import sys, json
d = json.load(sys.stdin)
pa = d.get("data",{}).get("private_api",False)
print(f"private_api enabled: {pa}")
sys.exit(0 if pa else 1)
'
```

### Phase E — launchd watchdog

```bash
cat > /tmp/com.symphony.bluebubbles-watchdog.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.symphony.bluebubbles-watchdog</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>pgrep -xq BlueBubbles || /usr/bin/open -a BlueBubbles</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/Users/bob/AI-Server/logs/bluebubbles-watchdog.out.log</string>
  <key>StandardErrorPath</key><string>/Users/bob/AI-Server/logs/bluebubbles-watchdog.err.log</string>
</dict>
</plist>
EOF

mkdir -p /Users/bob/AI-Server/logs
cp /tmp/com.symphony.bluebubbles-watchdog.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.symphony.bluebubbles-watchdog.plist 2>/dev/null || true
launchctl load -w  ~/Library/LaunchAgents/com.symphony.bluebubbles-watchdog.plist

# Commit template into repo
cp /tmp/com.symphony.bluebubbles-watchdog.plist /Users/bob/AI-Server/ops/launchd/
```

### Phase F — Bert Desktop client (remote step over Tailscale SSH)

```bash
# F1. Copy the passphrase securely to Bert via Tailscale SSH
#     (Tailscale SSH encrypts end-to-end on the tailnet)
ssh "$BERT_TAILNET_NAME" 'mkdir -p ~/.config/bluebubbles && chmod 700 ~/.config/bluebubbles'
scp "$BB_PASS_FILE" "$BERT_TAILNET_NAME:~/.config/bluebubbles/credentials"
ssh "$BERT_TAILNET_NAME" 'chmod 600 ~/.config/bluebubbles/credentials'

# F2. Install BlueBubbles Desktop on Bert
ssh "$BERT_TAILNET_NAME" 'brew install --cask bluebubbles'

# F3. GUI step on Bert — print instructions
cat <<EOF

┌─ MANUAL STEP (Bert) ──────────────────────────────────────────────┐
│ 1. Open BlueBubbles Desktop on Bert                               │
│ 2. Choose "Manual Entry"                                          │
│ 3. Server URL: https://$BOB_TAILNET_NAME                          │
│ 4. Password:   (in ~/.config/bluebubbles/credentials on Bert)     │
│ 5. Click Connect                                                  │
│ 6. Verify chats load, send a test message to $OWNER_PHONE_NUMBER  │
│    and reply to it from your phone                                │
└───────────────────────────────────────────────────────────────────┘

EOF
read -p "Press Enter once Bert client connected and test message round-trip succeeded..."
```

### Phase G — Cortex dashboard tile

**G1.** Add the proxy endpoint to `cortex/dashboard.py`. Insert after `symphony_portal_health` (around line 1090):

```python
    BLUEBUBBLES_URL = os.environ.get("BLUEBUBBLES_SERVER_URL", "")
    BLUEBUBBLES_PASSWORD = os.environ.get("BLUEBUBBLES_API_PASSWORD", "")

    @app.get("/api/symphony/bluebubbles/health")
    async def symphony_bluebubbles_health():
        if not BLUEBUBBLES_URL or not BLUEBUBBLES_PASSWORD:
            return {"status": "offline", "error": "BLUEBUBBLES_SERVER_URL / BLUEBUBBLES_API_PASSWORD not configured"}
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=True) as client:
                resp = await client.get(
                    f"{BLUEBUBBLES_URL}/api/v1/server/info",
                    headers={"password": BLUEBUBBLES_PASSWORD},
                )
                if resp.status_code != 200:
                    return {"status": "offline", "http_status": resp.status_code}
                data = resp.json().get("data", {})
                return {
                    "status": "online",
                    "server_url": BLUEBUBBLES_URL,
                    "private_api": data.get("private_api", False),
                    "server_version": data.get("server_version"),
                    "os_version": data.get("os_version"),
                }
        except Exception as exc:
            return {"status": "offline", "error": str(exc)}
```

**G2.** Add the tile to `cortex/static/index.html`. Find the Markup Tool tile (lines ~475–494) and add a new BlueBubbles tile **below the Proposals card** in the left column (see structure comment around line 496). Use the Markup tile as the visual template — same card shell, same status badge pattern, no iframe:

```html
      <!-- BlueBubbles -->
      <div class="card">
        <h2>BlueBubbles</h2>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div class="small muted">STATUS</div>
            <div><span id="bb-status">checking...</span></div>
          </div>
          <div>
            <div class="small muted">PRIVATE API</div>
            <div><span id="bb-private-api">—</span></div>
          </div>
          <div>
            <div class="small muted">VERSION</div>
            <div><span id="bb-version">—</span></div>
          </div>
        </div>
        <div class="small" style="margin-top:8px;">
          <span id="bb-url" class="muted"></span>
        </div>
      </div>
```

**G3.** Add the `checkBlueBubblesHealth()` function next to `checkMarkupHealth()` (~line 1362), and call it from the symphony tab activation block (~line 689):

```js
  async function checkBlueBubblesHealth() {
    try {
      const r = await fetch('/api/symphony/bluebubbles/health');
      const d = await r.json();
      const el = $('bb-status');
      if (d.status === 'online') {
        el.textContent = 'online';
        el.style.color = 'var(--green)';
        $('bb-private-api').textContent = d.private_api ? '✓ installed' : '✗ missing';
        $('bb-private-api').style.color = d.private_api ? 'var(--green)' : 'var(--red)';
        $('bb-version').textContent = d.server_version || '—';
        $('bb-url').innerHTML = d.server_url ? `<a href="${esc(d.server_url)}" target="_blank">${esc(d.server_url)}</a>` : '';
      } else {
        el.textContent = 'offline';
        el.style.color = 'var(--red)';
        $('bb-private-api').textContent = '—';
        $('bb-version').textContent = '—';
        $('bb-url').textContent = d.error || '';
      }
    } catch {
      $('bb-status').textContent = 'offline';
      $('bb-status').style.color = 'var(--red)';
    }
  }
```

And in the symphony tab activation (same block that calls `checkMarkupHealth()`):

```js
      checkMarkupHealth();
      checkBlueBubblesHealth();                             // <-- ADD
      if (!_markupCheckInterval) {
        _markupCheckInterval = setInterval(() => {
          if ($('tab-symphony') && $('tab-symphony').classList.contains('active')) {
            checkMarkupHealth();
            checkBlueBubblesHealth();                       // <-- ADD
          }
        }, 30000);
      }
```

**G4.** Add to `.env.example` (template — blank value, do NOT paste real password):

```bash
# BlueBubbles — Tailscale-only iMessage bridge (runs alongside imessage-server.py on :8199)
# Populated automatically by .cursor/prompts/cline-prompt-bluebubbles-install.md
BLUEBUBBLES_SERVER_URL=https://<bob-hostname>.<tailnet>.ts.net
BLUEBUBBLES_API_PASSWORD=
```

**G5.** Recompose cortex and verify:

```bash
cd /Users/bob/AI-Server
docker compose up -d --no-deps cortex
sleep 5
curl -s http://127.0.0.1:8102/api/symphony/bluebubbles/health | python3 -m json.tool
```

Expect `status: online`, `private_api: true`, real version string.

### Phase H — Commit + STATUS_REPORT update

```bash
cd /Users/bob/AI-Server

# H1. Update STATUS_REPORT.md — add one entry under "Recently deployed"
python3 - <<'PY'
from pathlib import Path
from datetime import date
sr = Path("STATUS_REPORT.md")
txt = sr.read_text()
entry = f"- **{date.today().isoformat()}** — BlueBubbles server live on Bob at `https://<tailnet>` via Tailscale serve (HTTPS, no Funnel). Private API installed. Desktop client on Bert verified. Dashboard tile added. Existing `imessage-server.py` on :8199 untouched and operational."
# Insert under "Recently deployed" heading, or append if section doesn't exist
if "## Recently deployed" in txt:
    txt = txt.replace("## Recently deployed\n", f"## Recently deployed\n{entry}\n", 1)
else:
    txt += f"\n\n## Recently deployed\n{entry}\n"
sr.write_text(txt)
print("STATUS_REPORT.md updated")
PY

# H2. Commit — TWO commits (code + ops) for clean history
git add cortex/dashboard.py cortex/static/index.html .env.example STATUS_REPORT.md
git -c user.email="$(git config user.email)" -c user.name="$(git config user.name)" \
  commit -m "feat(cortex): BlueBubbles health tile on Symphony Ops + env template"

git add ops/launchd/com.symphony.bluebubbles-watchdog.plist
git commit -m "ops(launchd): watchdog that relaunches BlueBubbles.app if it quits"

git push origin main
```

## 5. Deliverables

1. `BlueBubbles.app` + Private API running on Bob, reachable at `https://<bob>.<tailnet>.ts.net/` via Tailscale serve (HTTPS, no Funnel)
2. Passphrase stored in `~/.config/bluebubbles/credentials` (600) on both Bob and Bert, mirrored into `/Users/bob/AI-Server/.env`
3. `~/Library/LaunchAgents/com.symphony.bluebubbles-watchdog.plist` loaded on Bob; template at `ops/launchd/`
4. `BlueBubbles Desktop` installed + connected + round-trip test completed on Bert
5. Cortex dashboard Symphony Ops tab shows **BlueBubbles** tile with `online`, Private API `✓ installed`, version, clickable Tailscale URL
6. Two commits on `main`: one `feat(cortex):…`, one `ops(launchd):…`
7. `STATUS_REPORT.md` entry added

## 6. Acceptance Criteria

- [ ] `curl -sf "https://$BOB_TAILNET_NAME/api/v1/server/info" -H "password: $BB_PASS"` returns 200 with `"private_api": true`
- [ ] `sudo tailscale serve status` shows `443 → http://localhost:1234`, **Funnel=false**
- [ ] `launchctl list | grep bluebubbles-watchdog` shows the job loaded
- [ ] Quitting BlueBubbles manually (`osascript -e 'tell application "BlueBubbles" to quit'`) relaunches within 90s
- [ ] From Bert: BlueBubbles Desktop connected, test iMessage sent to `OWNER_PHONE_NUMBER`, reply received back in the client
- [ ] `curl http://127.0.0.1:8102/api/symphony/bluebubbles/health` returns `status: online` with populated version + private_api fields
- [ ] Symphony Ops tab shows the new tile rendering correctly (screenshot in Final Report)
- [ ] `curl -sf http://127.0.0.1:8199/health` STILL returns 200 (existing path preserved)
- [ ] `.env` has `BLUEBUBBLES_API_PASSWORD` and `BLUEBUBBLES_SERVER_URL`, but these are NOT committed (gitignored)
- [ ] `git status` clean; two commits pushed; no dangling changes

## 7. Guardrails — STOP if any of these trigger

- **Do not** enable Tailscale Funnel. Tailnet-only is the whole point. If the user later wants public exposure, that's a separate prompt.
- **Do not** modify `scripts/imessage-server.py`, `markup-tool`, `client-portal`, `polymarket-bot`, or `email-monitor`. BlueBubbles runs alongside, not instead of, the existing iMessage bridge on :8199.
- **Do not** commit `.env`, the raw passphrase, or any `credentials` file. Only `.env.example` and the launchd plist template go into git.
- **Do not** install ngrok, Cloudflare Tunnel, or any third-party tunnel. Tailscale serve only.
- If `osascript -e 'tell application "Messages" to return name of first account'` fails (iMessage not signed in), **stop** — prompt the user to sign in manually and re-run.
- If Phase D (Private API install) cannot be clicked through interactively, pause and hand off. Do not attempt to inject the dylib manually.
- If Bert is unreachable via Tailscale SSH, complete Phases A–E + G on Bob only, document Phase F as "pending manual run on Bert", and still push the commits. Do not block the rest.
- If `tailscale serve` is already bound to :443 by another service, `tailscale serve status` will show it — stop and report. Do not clobber it.

## 8. Final Report Format (produce when done)

Markdown, ≤ 60 lines:

1. **Phases completed** — check each (A through H)
2. **Commit SHAs** — both, with github blob URLs
3. **Verification evidence** — paste the actual JSON / curl output for every acceptance criterion (one short block per). In particular:
   - `tailscale serve status` output
   - `api/v1/server/info` JSON (redact the password header in the echo)
   - `api/symphony/bluebubbles/health` JSON
   - Confirmation that `:8199` still responds
4. **Bert status** — connected vs deferred, with the test message evidence (or explicit "deferred to manual run")
5. **Remaining concerns** — anything that surfaced (e.g., Messages permission prompts the user still needs to click, Tailscale cert propagation delay, etc.)
6. **Suggested follow-ups** — only if meaningful (e.g., "wire BlueBubbles into notification-hub as a secondary channel once stable")
