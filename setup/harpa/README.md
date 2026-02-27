# HARPA AI Browser Automation — Symphony Smart Homes
**D-Tools Cloud Automation via Intel iMac Browser Nodes**

HARPA AI is a Chrome extension that enables AI-powered browser automation. Symphony Smart Homes uses it to automate D-Tools Cloud tasks that don't have an API — creating projects, importing equipment, and pulling reports.

---

## Architecture

```
[Bob the Conductor]          [64GB iMac]               [D-Tools Cloud]
   Mac Mini M4    ────────  Chrome + HARPA  ────────  portal.d-tools.com
   OpenClaw                  HARPA Grid API
   bob_harpa_bridge.py       Custom commands:
   HTTP API calls              - create_project
                               - import_equipment_csv
                               - get_project_status
                               - export_proposal
                               - update_project_phase
                               - search_projects

[8GB iMac]
   Chrome + HARPA  ────────  same endpoint
   (browser-only node)
```

---

## Files

| File | Purpose |
|---|---|
| `setup_imac_harpa.sh` | Full setup for 64GB iMac (Ollama + HARPA + bridge) |
| `setup_imac_browser_only.sh` | Minimal setup for 8GB iMac (HARPA only) |
| `harpa_dtools_commands.json` | 6 D-Tools HARPA custom commands to import |
| `bob_harpa_bridge.py` | Python bridge API server (runs on Mac Mini M4) |
| `imac_node_config.md` | Chrome and HARPA configuration guide |
| `README.md` | This file |

---

## Setup Order

1. **64GB iMac** (primary automation node):
   ```bash
   chmod +x setup_imac_harpa.sh
   ./setup_imac_harpa.sh
   ```

2. **8GB iMac** (secondary/browser-only node):
   ```bash
   chmod +x setup_imac_browser_only.sh
   ./setup_imac_browser_only.sh
   ```

3. **Mac Mini M4** (Bob — already set up with OpenClaw):
   - The `bob_harpa_bridge.py` runs on Bob as a background service
   - It receives automation requests from OpenClaw and forwards to HARPA

4. **Chrome + HARPA configuration** on each iMac:
   - Follow `imac_node_config.md` for Chrome profile and HARPA Grid setup
   - Import `harpa_dtools_commands.json` into HARPA

---

## How It Works

### Automation Flow

1. User or OpenClaw sends a task to Bob: *"Create a D-Tools project for Smith Residence"*
2. Bob calls `bob_harpa_bridge.py` (HTTP API on Mac Mini)
3. Bridge sends the command to HARPA Grid API on the 64GB iMac
4. HARPA executes the Chrome automation in D-Tools Cloud
5. HARPA returns the result to the bridge
6. Bridge returns the result to Bob
7. Bob reports back to the user

### D-Tools Commands Available

| Command | What It Does |
|---|---|
| `create_project` | Creates a new D-Tools Cloud project |
| `import_equipment_csv` | Imports an equipment CSV into a project |
| `get_project_status` | Fetches current project phase/status |
| `export_proposal` | Triggers proposal export and returns download URL |
| `update_project_phase` | Advances project to a new phase |
| `search_projects` | Searches for projects by client name |

---

## HARPA Grid Setup

HARPA Grid allows external HTTP requests to trigger HARPA commands in Chrome.

1. In Chrome with HARPA installed, open HARPA sidebar
2. Navigate to **Settings → Grid**
3. Enable Grid mode
4. Note your Grid endpoint URL and API key
5. Add these to `bob_harpa_bridge.py` configuration

---

## D-Tools Credentials

HARPA operates as your logged-in Chrome session. You must:
1. Log into D-Tools Cloud in the Chrome profile HARPA uses
2. Keep that Chrome profile logged in (check *Remember me*)
3. HARPA will operate as that user

No API keys required for D-Tools — HARPA uses your browser session.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| HARPA not responding | Check Chrome is open and HARPA extension is active |
| D-Tools session expired | Re-login to D-Tools in Chrome, check *Remember me* |
| Bridge API unreachable | Check `bob_harpa_bridge.py` is running on Mac Mini M4 |
| Command fails in D-Tools | Check HARPA command JSON — D-Tools UI may have changed |
| Grid API returns 401 | Check HARPA Grid API key in bridge config |

---

## Security Notes

- HARPA Grid API is LAN-only — not exposed externally
- D-Tools credentials are your browser session (not stored in files)
- `bob_harpa_bridge.py` runs on localhost only unless configured otherwise
- All automation happens inside your LAN
