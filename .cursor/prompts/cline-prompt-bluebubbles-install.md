# BlueBubbles install — Act mode

Execute on Bob (`/Users/bob/AI-Server`). Run commands in order. On first failure, print the failing command + stderr, stop, and wait for me. Do not restate the plan. Do not narrate. Commit at the end of each phase.

**Off-limits:** `scripts/imessage-server.py`, `markup-tool`, `client-portal`, `polymarket-bot`, `email-monitor`. Do not edit or restart any of them.

> **Port note:** BlueBubbles uses **Tailscale serve on :8443** (not :443). Port 443 is already serving the Markup Tool via Tailscale serve; we leave it alone. Client URLs must include `:8443` (mobile apps and desktop clients handle non-443 fine).


---

## Phase 0 — Audit (detect partial state, resume safely)

```bash
cd /Users/bob/AI-Server && git pull --ff-only

# What already exists?
echo "=== audit ==="
ls -la /Applications/BlueBubbles.app 2>/dev/null && echo "BB_APP=installed" || echo "BB_APP=missing"
[ -f ~/.config/bluebubbles/credentials ] && echo "CREDS=present" || echo "CREDS=missing"
[ -f ~/Library/Application\ Support/BlueBubbles/config.json ] && echo "CONFIG=present" || echo "CONFIG=missing"
sudo tailscale serve status 2>&1 | grep -E "8443.*localhost:1234|:8443 .*localhost:1234" >/dev/null && echo "TSERVE=configured" || echo "TSERVE=missing"
launchctl list | grep -q com.symphony.bluebubbles-watchdog && echo "WATCHDOG=loaded" || echo "WATCHDOG=missing"
grep -q '^BLUEBUBBLES_API_PASSWORD=' .env && echo "ENV=set" || echo "ENV=missing"
curl -sf http://127.0.0.1:8199/health >/dev/null && echo "IMSG_BRIDGE=up" || echo "IMSG_BRIDGE=down"
osascript -e 'tell application "Messages" to return name of first account' 2>/dev/null && echo "IMESSAGE=signed_in" || { echo "IMESSAGE=not_signed_in — STOP, ask Matt to sign in"; exit 1; }
```

Skip any sub-step below whose corresponding audit flag is already set correctly.

---

## Phase 1 — Install + configure + tailscale serve + env

```bash
# 1a. Install server app (idempotent)
[ -d /Applications/BlueBubbles.app ] || brew install --cask bluebubbles
open -a BlueBubbles
# give it time to create config
for i in 1 2 3 4 5 6 7 8; do
  [ -f ~/Library/Application\ Support/BlueBubbles/config.json ] && break
  sleep 2
done

# 1b. Generate passphrase (only if not already stored)
mkdir -p ~/.config/bluebubbles && chmod 700 ~/.config/bluebubbles
if [ ! -f ~/.config/bluebubbles/credentials ]; then
  umask 077
  BB_PASS=$(openssl rand -base64 24)
  printf 'BLUEBUBBLES_API_PASSWORD=%s\n' "$BB_PASS" > ~/.config/bluebubbles/credentials
  chmod 600 ~/.config/bluebubbles/credentials
else
  BB_PASS=$(grep '^BLUEBUBBLES_API_PASSWORD=' ~/.config/bluebubbles/credentials | cut -d= -f2-)
fi

# 1c. Tailnet hostname (must resolve or we stop)
BOB_TAILNET=$(tailscale status --json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["Self"]["DNSName"].rstrip("."))')
[ -n "$BOB_TAILNET" ] || { echo "no MagicDNS name — STOP"; exit 1; }
export BB_PASS BOB_TAILNET

# 1d. Patch BlueBubbles config.json (atomic write, no 3rd-party tunnels)
python3 <<'PY'
import json, os, shutil
from pathlib import Path
p = Path(os.path.expanduser("~/Library/Application Support/BlueBubbles/config.json"))
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["password"] = os.environ["BB_PASS"]
cfg["server_port"] = 1234
cfg["use_custom_certificate"] = False
cfg["use_ngrok"] = False
cfg["use_cloudflare"] = False
cfg["use_local_tunnel"] = False
cfg["proxy_service"] = "Dynamic DNS"
cfg["server_address"] = f"https://{os.environ['BOB_TAILNET']}:8443"
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
shutil.move(tmp, p)
print("config.json written")
PY

osascript -e 'tell application "BlueBubbles" to quit' 2>/dev/null; sleep 2; open -a BlueBubbles; sleep 5

# 1e. Tailscale serve — HTTPS on tailnet (NOT Funnel)
if ! sudo tailscale serve status 2>&1 | grep -E "8443.*localhost:1234" >/dev/null; then
  sudo tailscale serve --bg --https=8443 http://localhost:1234
fi
sudo tailscale serve status | grep -qi funnel=true && { echo "Funnel is ON — STOP (tailnet-only required)"; exit 1; }

# 1f. End-to-end API check (query param — Tailscale serve strips custom headers)
curl -sf --max-time 10 "https://$BOB_TAILNET:8443/api/v1/server/info?password=$BB_PASS" \
  | python3 -m json.tool | head -15 \
  || { echo "API verify failed — STOP"; exit 1; }

# 1g. Mirror into .env — always reflect BB config DB truth (overwrite if present)
touch .env
awk -v pw="$BB_PASS" -v url="https://$BOB_TAILNET:8443" '
  BEGIN{seen_pw=0; seen_url=0}
  /^BLUEBUBBLES_API_PASSWORD=/{print "BLUEBUBBLES_API_PASSWORD=" pw; seen_pw=1; next}
  /^BLUEBUBBLES_SERVER_URL=/{print "BLUEBUBBLES_SERVER_URL=" url; seen_url=1; next}
  {print}
  END{
    if(!seen_pw) print "BLUEBUBBLES_API_PASSWORD=" pw
    if(!seen_url) print "BLUEBUBBLES_SERVER_URL=" url
  }' .env > .env.new && mv .env.new .env
grep -q '^\.env$' .gitignore || echo ".env" >> .gitignore

# 1h. launchd watchdog
mkdir -p logs ops/launchd
cat > ops/launchd/com.symphony.bluebubbles-watchdog.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.symphony.bluebubbles-watchdog</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string>
    <string>pgrep -xq BlueBubbles || /usr/bin/open -a BlueBubbles</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/Users/bob/AI-Server/logs/bluebubbles-watchdog.out.log</string>
  <key>StandardErrorPath</key><string>/Users/bob/AI-Server/logs/bluebubbles-watchdog.err.log</string>
</dict></plist>
PLIST
cp ops/launchd/com.symphony.bluebubbles-watchdog.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.symphony.bluebubbles-watchdog.plist 2>/dev/null || true
launchctl load -w ~/Library/LaunchAgents/com.symphony.bluebubbles-watchdog.plist

# 1i. Sanity: existing :8199 bridge still responds
curl -sf http://127.0.0.1:8199/health >/dev/null && echo "imessage-bridge :8199 OK" || echo "WARN: :8199 not responding (not touched by us)"

# 1j. Commit ops plist (no secrets)
git add ops/launchd/com.symphony.bluebubbles-watchdog.plist
git -c user.email="$(git config user.email)" -c user.name="$(git config user.name)" \
  commit -m "ops(launchd): bluebubbles watchdog relaunches app if it quits"
```

**Pause here. Report Phase 1 complete with the JSON from step 1f and the `tailscale serve status` output. Then continue.**

---

## Phase 2 — Private API helper (optional — skip if SIP is on)

BlueBubbles' "Private API" unlocks reply reactions, tapbacks, typing indicators, and send-effects by injecting a dylib into Messages.app. This requires System Integrity Protection (SIP) **disabled**, which permanently lowers Bob's kernel-level protection.

**Decision matrix:**

- **SIP on (recommended for Bob)** — skip helper install. Send/receive, groups, read receipts all still work. Acceptable state: `private_api: false`, `helper_connected: false`. Proceed directly to Phase 3.
- **SIP off** — install helper via GUI using the flow below.

To skip: set `SKIP_PRIVATE_API=1` and jump to Phase 3. To install:

```bash
osascript -e 'tell application "BlueBubbles" to activate'
echo ""
echo "ACTION REQUIRED (Bob):"
echo "  BlueBubbles → Settings → Private API → Install Helper → authorize"
echo "  Messages.app will restart automatically."
echo ""
echo "When the toggle reads 'Installed', reply to this task with the single word: CONTINUE"
```

**Do not use `read -p`. Do not block. Exit the phase cleanly and wait for my next message. When I say CONTINUE, run this verification and proceed:**

```bash
# Verify server healthy (private_api true OR false both acceptable — false = SIP-skipped path)
curl -sf --max-time 10 "https://$BOB_TAILNET:8443/api/v1/server/info?password=$BB_PASS" \
  | python3 -c '
import sys, json
d = json.load(sys.stdin).get("data", {})
pa = d.get("private_api", False)
hc = d.get("helper_connected", False)
sv = d.get("server_version", "?")
print(f"server_version={sv} private_api={pa} helper_connected={hc}")
if pa and not hc:
    print("WARN: helper installed but not connected — check Messages.app restart"); sys.exit(2)
print("OK: server reachable; private_api=" + ("enabled" if pa else "skipped (SIP-on path)"))
' || { echo "Server unreachable — STOP"; exit 1; }
```

---

## Phase 3 — Dashboard tile (code change, two commits)

### 3a. Backend — `cortex/dashboard.py`

Find the block where `PROPOSALS_URL` / `MARKUP_URL` style env-derived constants are defined near the top of the `register_symphony_routes` function (or wherever `symphony_markup_health` lives — use `grep -n "symphony_markup_health\|MARKUP_URL" cortex/dashboard.py`). Insert a new endpoint next to it:

```python
BLUEBUBBLES_URL = os.environ.get("BLUEBUBBLES_SERVER_URL", "")
BLUEBUBBLES_PASSWORD = os.environ.get("BLUEBUBBLES_API_PASSWORD", "")

@app.get("/api/symphony/bluebubbles/health")
async def symphony_bluebubbles_health():
    if not BLUEBUBBLES_URL or not BLUEBUBBLES_PASSWORD:
        return {"status": "offline", "error": "not configured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{BLUEBUBBLES_URL}/api/v1/server/info",
                params={"password": BLUEBUBBLES_PASSWORD},
            )
        if r.status_code != 200:
            return {"status": "offline", "http_status": r.status_code}
        data = r.json().get("data", {})
        return {
            "status": "online",
            "server_url": BLUEBUBBLES_URL,
            "private_api": bool(data.get("private_api")),
            "server_version": data.get("server_version"),
        }
    except Exception as exc:
        return {"status": "offline", "error": str(exc)}
```

If `httpx` isn't already imported at the top of the file, add `import httpx`.

### 3b. Frontend — `cortex/static/index.html`

Find the Markup Tool card (search for `id="markup-status"`). Add a sibling BlueBubbles card right after the Markup card's closing `</div>` (same column, same card pattern):

```html
<!-- BlueBubbles -->
<div class="card">
  <h2>BlueBubbles</h2>
  <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap;">
    <div><div class="small muted">STATUS</div><div><span id="bb-status">checking…</span></div></div>
    <div><div class="small muted">PRIVATE API</div><div><span id="bb-private-api">—</span></div></div>
    <div><div class="small muted">VERSION</div><div><span id="bb-version">—</span></div></div>
  </div>
  <div class="small" style="margin-top:8px;"><span id="bb-url" class="muted"></span></div>
</div>
```

Find `async function checkMarkupHealth()` (around line 1362). Add this function directly after it:

```js
async function checkBlueBubblesHealth() {
  try {
    const r = await fetch('/api/symphony/bluebubbles/health', {signal: AbortSignal.timeout(6000)});
    const d = await r.json();
    const el = document.getElementById('bb-status');
    if (d.status === 'online') {
      el.textContent = 'online'; el.style.color = 'var(--green)';
      const pa = document.getElementById('bb-private-api');
      pa.textContent = d.private_api ? '✓ installed' : '✗ missing';
      pa.style.color = d.private_api ? 'var(--green)' : 'var(--red)';
      document.getElementById('bb-version').textContent = d.server_version || '—';
      const urlEl = document.getElementById('bb-url');
      urlEl.innerHTML = d.server_url ? `<a href="${d.server_url}" target="_blank" rel="noopener">${d.server_url}</a>` : '';
    } else {
      el.textContent = 'offline'; el.style.color = 'var(--red)';
      document.getElementById('bb-private-api').textContent = '—';
      document.getElementById('bb-version').textContent = '—';
      document.getElementById('bb-url').textContent = d.error || '';
    }
  } catch {
    const el = document.getElementById('bb-status');
    if (el) { el.textContent = 'offline'; el.style.color = 'var(--red)'; }
  }
}
```

Find the block that calls `checkMarkupHealth()` (the Symphony tab activation + setInterval — search for `checkMarkupHealth()`). Add a `checkBlueBubblesHealth()` call next to each `checkMarkupHealth()` call (there should be two).

### 3c. `.env.example`

Append (blank value on purpose):

```
# BlueBubbles — Tailscale-only iMessage bridge (runs alongside imessage-server.py on :8199)
BLUEBUBBLES_SERVER_URL=
BLUEBUBBLES_API_PASSWORD=
```

### 3d. Verify + commit

```bash
docker compose up -d --no-deps cortex
for i in 1 2 3 4 5 6 7 8; do
  curl -sf http://127.0.0.1:8102/health >/dev/null && break; sleep 2
done
curl -s http://127.0.0.1:8102/api/symphony/bluebubbles/health | python3 -m json.tool

git add cortex/dashboard.py cortex/static/index.html .env.example
git commit -m "feat(cortex): BlueBubbles health tile on Symphony Ops tab"
git push origin main
```

**Pause here. Report Phase 3 complete with the `/api/symphony/bluebubbles/health` JSON and both commit SHAs. Then continue.**

---

## Phase 4 — Bert Desktop client (only if Bert is reachable)

```bash
# 4a. Find Bert on the tailnet
BERT_TAILNET=$(tailscale status --json | python3 -c '
import sys, json
d = json.load(sys.stdin)
for p in d.get("Peer", {}).values():
    if p.get("HostName","").lower().startswith("bert"):
        print(p["DNSName"].rstrip(".")); break
')
[ -n "$BERT_TAILNET" ] || { echo "Bert not on tailnet — skip Phase 4, document in Final Report"; exit 0; }

# 4b. SSH probe (5s timeout, non-interactive)
ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$BERT_TAILNET" 'echo ok' 2>/dev/null \
  || { echo "Bert SSH not ready — skip Phase 4, document in Final Report"; exit 0; }

# 4c. Ship credentials + install
ssh "$BERT_TAILNET" 'mkdir -p ~/.config/bluebubbles && chmod 700 ~/.config/bluebubbles'
scp ~/.config/bluebubbles/credentials "$BERT_TAILNET:~/.config/bluebubbles/credentials"
ssh "$BERT_TAILNET" 'chmod 600 ~/.config/bluebubbles/credentials && brew install --cask bluebubbles'

echo ""
echo "ACTION REQUIRED (Bert):"
echo "  BlueBubbles Desktop → Manual Entry"
echo "    Server URL: https://$BOB_TAILNET:8443"
echo "    Password:   cat ~/.config/bluebubbles/credentials (on Bert)"
echo "  Send a test iMessage to your own number, reply from phone, verify round-trip."
echo ""
echo "Reply CONTINUE when round-trip verified, or SKIP to finish without Bert."
```

**Wait for my CONTINUE or SKIP. Do not block.**

---

## Phase 5 — STATUS_REPORT + final push

When Phase 2 is verified and either Phase 4 is CONTINUE'd or SKIP'd:

```bash
# Append to STATUS_REPORT.md under ## Done
python3 <<'PY'
from pathlib import Path
from datetime import date
p = Path("STATUS_REPORT.md")
txt = p.read_text()
entry = f"- ✅ **BlueBubbles live ({date.today().isoformat()})** — Server on Bob via Tailscale serve (HTTPS, no Funnel). Private API installed. Dashboard tile on Symphony Ops. launchd watchdog loaded. Existing `imessage-server.py` on :8199 untouched."
if "## Done" in txt and entry not in txt:
    txt = txt.replace("## Done\n", f"## Done\n\n{entry}\n", 1)
    p.write_text(txt)
    print("STATUS_REPORT.md updated")
else:
    print("no-op: entry already present or ## Done not found")
PY

git add STATUS_REPORT.md
git diff --cached --quiet || git commit -m "docs(status): bluebubbles live"
git push origin main
```

---

## Final Report format

One message, ≤ 30 lines:

1. Phase completion: 1 ✅ / 2 ✅ / 3 ✅ / 4 ✅ or SKIPPED / 5 ✅
2. Commit SHAs (all of them) with github blob URLs
3. Paste the `/api/symphony/bluebubbles/health` JSON
4. Paste the `tailscale serve status` output
5. Confirm `:8199` still responds (one line)
6. Anything that surprised you (one bullet per)

---

## Hard rules (non-negotiable)

- No Tailscale Funnel. Ever. Tailnet-only.
- Do not touch Tailscale serve on :443 (that's Markup Tool). BlueBubbles goes on :8443.
- Do not touch `scripts/imessage-server.py`, `markup-tool`, `client-portal`, `polymarket-bot`, `email-monitor`.
- Never commit `.env` or `~/.config/bluebubbles/credentials`.
- No ngrok. No Cloudflare Tunnel. No third-party relays.
- If any command fails, print the failure and stop. Don't invent workarounds.
