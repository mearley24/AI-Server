# Symphony Markup Tools

Custom AV markup system with standardized symbols for accurate automated detection.

## Components

### 1. iPad Markup App (`web/`)
Web-based markup tool optimized for iPad/tablet use.

**Start Server:**
```bash
python3 /Users/bob/AI-Server/tools/markup_app/server.py
```

**Access:**
- iPad: `http://192.168.1.109:8091` (or your Mac's local IP)
- **HTTPS (for Share → Save to Files):** Run `tailscale serve 8091`, set `MARKUP_HTTPS_URL` in `.env` — see `setup/markup/TAILSCALE_HTTPS.md`
- Add to Home Screen for app-like experience

### Optional Secure Access (Trades)

You can lock down API write access without breaking local workflow.

- `MARKUP_REQUIRE_AUTH=1` to require auth on `/api/*` endpoints.
- `MARKUP_API_TOKEN=...` shared token (sent as `Authorization: Bearer ...` or `X-Markup-Token`).
- `MARKUP_ALLOW_LOCAL=1` keeps local/LAN editing available while you roll out remote auth.

If you pass `?token=...` once in the URL, the web app stores it locally and removes it from the URL.

Project-level permissions and invite links:
- Each project now has ACL roles (`owner`, `editor`, `viewer`).
- Trades only see projects they are assigned to (when auth is enabled).
- File modal includes **Create Invite Link** to generate time-limited invites.
- File modal includes **Project Access Manager** to review members/invites, change roles, and revoke links.
- Access Manager includes a project switcher with **New** and **Rename** controls for project-level administration.
- Access Manager includes filter/search and a project audit feed showing who changed what and when.
- Session tracking is active via heartbeat (`/api/session/ping`) and Access Manager shows per-user time spent per project.
- Invite links are accepted with `?invite=<token>` and membership is assigned to the authenticated user.
- Every save writes an audit event in `Project/.audit.jsonl` with user attribution + summary counts.

**Features:**
- Load floor plan images (PNG, JPG)
- Tap to place symbols
- Real-time counts
- Save options: Server (iCloud + Bob), Download (choose folder), Export as image

**Save locations (Save to Server):**
- iCloud: `~/Library/Mobile Documents/.../Symphony SH/Markup_Exports/ProjectName/`
- Local: `~/AI-Server/knowledge/markup_exports/ProjectName/`

### 2. Symbol Detector (`../symbol_detector.py`)
Color-based detection for existing Clawd/Symphony markups.

**Usage:**
```bash
source /Users/bob/AI-Server/.venv/bin/activate
python3 /Users/bob/AI-Server/tools/symbol_detector.py "/path/to/markup.png"
```

**Accuracy (Mitchell test):**
| Device | Manual Count | Detector | Accuracy |
|--------|-------------|----------|----------|
| Shades | 57 | 61 | 107% |
| Keypads | 42 | 42 | 100% |
| Speakers | 52 | 15 | 29% (needs tuning) |

### 3. Training Data Generator (`train/`)
Generates synthetic training images for ML model training.

```bash
python3 train/generate_training_data.py --samples 1000 --output /path/to/dataset
```

## Symbol Library

All symbols are defined in:
- `symbols/symbols.svg` - Vector source
- `/Users/bob/AI-Server/knowledge/symbols/SYMBOL_SPEC.md` - Full specification

### Key Symbols

| Symbol | Color | Shape | D-Tools SKU |
|--------|-------|-------|-------------|
| Shade | Yellow | Circle | PREWIRE-SHADE |
| Keypad | Purple | Rectangle | C4-KPZ-B-W |
| Speaker | Blue/Orange/Green | Rounded Rect | TS-IC62 |
| TV | Green | Rectangle | C4-TV-HDMI-CTRL-B |
| AP | Red | Rectangle | AN-510-AP-I-AC |
| Camera | Orange | Circle | CAM-DOME |

## Workflow

1. **New Project Markup:**
   - Open iPad app
   - Load floor plan
   - Place symbols using toolbar
   - Export JSON

2. **Analyze Existing Markup:**
   - Run `symbol_detector.py` on Clawd export
   - Review counts
   - Import to D-Tools

3. **Improve Detection:**
   - Generate training data
   - Train YOLO model
   - Deploy to `symbol_detector.py`

## Files

```
markup_app/
├── server.py           # Web server
├── web/
│   └── index.html      # iPad markup app
├── symbols/
│   └── symbols.svg     # Symbol library
├── train/
│   └── generate_training_data.py
└── README.md
```
