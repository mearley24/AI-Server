# API-15: Symphony Ops Web Dashboard — Business Operations GUI

## The Vision

An intuitive web dashboard that Matt — or anyone covering for him — can open and immediately understand and operate the entire Symphony business. Browse products, build SOWs, track projects, run pre-flight checks. Not a developer tool. Not a terminal. A real GUI. The proposal engine and pricing calculator exist. Build the web UI that drives them.

Read the existing code first.

## Context Files to Read First

- `proposals/proposal_engine.py`
- `proposals/pricing_calculator.py`
- `proposals/scope_builder.py`
- `proposals/api_server.py`
- `proposals/dtool_cloud_client.py`
- `apps/vault-pwa/serve.py`

## Prompt

### 1. Understand the Existing Backend

Read all `proposals/*.py` files carefully:

- `proposal_engine.py`: What does it take as input? How does it generate proposals? What's the output format?
- `pricing_calculator.py`: What pricing logic exists? Margin rules? Labor rates? What inputs does it expect?
- `scope_builder.py`: How does it build scope from products and rooms? What's the scope object structure?
- `dtool_cloud_client.py`: How does it authenticate with D-Tools? What endpoints does it call? What does it return?
- `api_server.py`: What routes already exist? What port does it run on? Can this be extended or does the dashboard need its own server?

Read `apps/vault-pwa/serve.py`: What does it serve? What's the file structure? Can the dashboard be served from here on a new route, or should it be a separate server?

Map every existing function you will call. Do not duplicate logic — call the existing code.

### 2. Dashboard Backend (`proposals/dashboard_server.py` — new file, or extend `api_server.py`)

FastAPI server on port 8101. If `api_server.py` is already on 8101 or can be extended cleanly, extend it. If not, create `dashboard_server.py`.

```python
# Auth middleware — all routes except /health require password
# Password: env var DASHBOARD_PASSWORD
# Simple session cookie (no JWT, no OAuth — this is an internal tool)

GET  /health                 # No auth. Returns {"status": "ok"}
GET  /                       # Redirect to /dashboard
GET  /dashboard              # Main HTML page

# API routes (JSON)
GET  /api/projects           # All projects from D-Tools + client_tracker
GET  /api/projects/{id}      # Single project with full detail
GET  /api/products           # Full product catalog from knowledge/hardware/*.json
GET  /api/products/search    # ?q=samsung&category=video
POST /api/sow/build          # Body: {rooms, products} → scope from scope_builder.py
POST /api/pricing/calculate  # Body: scope → pricing from pricing_calculator.py
POST /api/preflight          # Body: project_id or design → validation report
GET  /api/emails/{project_id} # Recent emails for a project
```

### 3. Product Catalog Page (`/products`)

Parse `knowledge/hardware/*.json` on server startup, cache in memory. Serve as a searchable grid:

**HTML/JS (vanilla — no React/Vue):**
- Grid layout: product cards with name, category badge, price, photo if available
- Filter bar: buttons for each category (lighting, audio, video, networking, surveillance, control, shades)
- Search input: filters the grid in real-time (JS substring match on name + SKU)
- Click card → expand/modal with: full specs, compatible devices, cable requirements, VLAN, labor hours, MSRP, dealer cost
- "Add to Project" button: adds to the active project design context (stored in sessionStorage)

Parse product markdown files from `knowledge/products/*.md` if the JSON files lack product details. Extract: name, SKU, specs table, description, compatibility notes.

### 4. SOW Builder Page (`/sow-builder`)

Visual scope assembly:

**Left panel — Room Templates:**
- List of room types: Theater, Living Room, Bedroom, Kitchen, Office, Outdoor, etc.
- Click to add a room instance to the project
- Each room has a default equipment package (pulled from `knowledge/proposal_library/`)
- Optional upgrades shown as toggle switches

**Right panel — Live SOW Preview:**
- Updates in real-time as rooms/products are added/removed
- Shows scope text (from `scope_builder.py` via `/api/sow/build`)
- Running totals footer: equipment cost, labor cost, total price (from `/api/pricing/calculate`)

**Action buttons:**
- "Run Pre-Flight" → POST to `/api/preflight`, show pass/warn/fail results inline
- "Generate SOW" → download as markdown file
- "Export PDF" → Symphony-branded PDF (if PDF generation exists in the backend — check `proposals/` first)

### 5. Project Tracker Page (`/projects`)

Pull from both D-Tools (via `dtool_cloud_client.py`) and `openclaw/client_tracker.py`:

**Project list view:**
- Status badges: Lead, Proposal, Won, Pre-Wire, Install, Commission, Complete
- Sort by status, then by proposal date (newest first)
- Columns: client name, address, project value, proposal date, phase, next action

**Project detail view** (click a project):
- Timeline: all 22 Linear issues in 4 phases with completion status
- Phase progress bars (% complete)
- Key dates: proposal sent, deposit received, scheduled install, commission date
- Recent activity feed: emails, file uploads, status changes (from Redis comms log)
- Client contact card: name, email, phone, address
- Dropbox folder link (from client_tracker share link field)

### 6. Design Tool Page (`/design`)

Room-by-room system designer that feeds into API-14 design validator:

**Flow:**
1. Add rooms → name each room, select room type
2. For each room: search/browse products from the catalog, add to room
3. "Validate Design" button → POST design to `/api/preflight` → show inline results
   - Green badge: PASS
   - Yellow badge: WARN (with expandable detail)
   - Red badge: FAIL (with expandable detail and suggested fix)
4. Auto-generated wiring diagram (Mermaid rendered in-browser via mermaid.js CDN)
5. "Create Proposal" → takes validated design straight into SOW builder

### 7. Technical Implementation

**Stack:**
- FastAPI backend (Python)
- HTML/CSS/JS frontend — no build step, no bundler, just files served statically
- Tailwind CSS via CDN (dark theme, no config file needed)
- Vanilla JS with `fetch()` for all API calls — no jQuery, no frameworks
- Mermaid.js via CDN for wiring diagrams

**Dark theme colors (match Mission Control):**
- Background: `#0f1117`
- Card/panel: `#1a1d27`
- Border: `#2a2d3d`
- Accent: `#6c63ff` (purple)
- Text: `#e2e8f0`
- Success green: `#48bb78`, Warning yellow: `#ecc94b`, Error red: `#f56565`

**Auth (session cookie):**
```python
# On login: POST /login with {password: "..."}
# If password matches DASHBOARD_PASSWORD env var → set httponly session cookie
# Cookie expires in 24 hours
# All /api/* routes check cookie — 401 if missing/expired
```

**Mobile responsive:** Target iPad Pro (1024px) as primary. Must be usable in portrait mode on-site.

### 8. Docker Service

Add `symphony-ops` to `docker-compose.yml`:

```yaml
symphony-ops:
  build: ./proposals
  command: python dashboard_server.py
  ports:
    - "8101:8101"
  environment:
    - DASHBOARD_PASSWORD=${DASHBOARD_PASSWORD}
    - DTOOLS_API_KEY=${DTOOLS_API_KEY}
    - REDIS_URL=redis://172.18.0.100:6379
  volumes:
    - ./knowledge:/app/knowledge:ro
    - ./openclaw:/app/openclaw:ro
  depends_on:
    - redis
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8101/health"]
```

Also create a `Dockerfile` in `proposals/` if one doesn't exist.

### 9. Test: Verify the Dashboard Loads with Real Data

```bash
# Start the dashboard
docker compose up symphony-ops -d

# Check health
curl http://localhost:8101/health

# Load the product catalog (no auth for this test — use the API directly)
curl http://localhost:8101/api/products | python3 -m json.tool | head -50

# Verify D-Tools projects load
curl -b "session=..." http://localhost:8101/api/projects

# Test SOW build
curl -X POST -H "Content-Type: application/json" \
  -d '{"rooms": [{"name": "Living Room", "products": ["C4-EA5", "EP-SPEAKER-6"]}]}' \
  http://localhost:8101/api/sow/build

# Open in browser
open http://localhost:8101
```

Verify: product catalog shows real products, project list shows real projects, pricing calculator returns real numbers from `pricing_calculator.py`.

Use standard logging. All log messages prefixed with `[symphony-ops]`.
