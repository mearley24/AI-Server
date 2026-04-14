# Cline Prompt: Symphony Ops Tab on Cortex Dashboard

## Objective

Add a "Symphony Ops" tab to the Cortex dashboard (`cortex/static/index.html`) that gives Matt a single pane of glass for all Symphony Smart Homes business tools. Many of these tools exist in the codebase but have no UI entry point — they ran on Lovable or were CLI-only. This tab makes them all accessible from the Cortex dashboard at `http://localhost:8102`.

---

## Current Dashboard State

The dashboard (`cortex/static/index.html`) has three tabs:
1. **Overview** — services health, wallet, positions, PnL, emails, calendar, follow-ups, X intake summary
2. **X Intake** — full X link analysis queue with approve/reject
3. **Transcripts & Gems** — video transcripts and extracted insights

The tab system uses `data-tab` attributes on `<button class="tab-btn">` elements and `<div id="panel-{name}" class="tab-panel">` panels, switched via `window.switchTab(name)`.

---

## What to Build

### New Tab: "Symphony Ops"

Add a fourth tab button after "Transcripts & Gems":
```html
<button class="tab-btn" data-tab="symphony" role="tab">Symphony Ops</button>
```

Add a new panel `<div id="panel-symphony" class="tab-panel">` with these sections:

---

### Section 1: Markup Tool (iframe)

The markup app runs as a standalone server at `http://localhost:8091` (or `http://192.168.1.199:8091` on LAN). It is NOT in Docker — it runs on the host via `python3 tools/markup_app/server.py`.

**But the proposals service already occupies port 8091 in Docker Compose.** The markup app defaults to 8091 but can be changed. We need to:
1. **Change the markup app default port to 8088** — update `tools/markup_app/server.py` default from 8091 to 8088
2. Add a launchd-style note in the dashboard that the markup server needs to be running on the host

Dashboard section:
```html
<div class="card" style="padding:0; overflow:hidden;">
  <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 14px; border-bottom:1px solid var(--border);">
    <h2 style="margin:0; padding:0; border:0;">Markup Tool</h2>
    <div style="display:flex;gap:8px;align-items:center;">
      <span class="small" id="markup-status">checking...</span>
      <a href="http://192.168.1.199:8088" target="_blank" class="btn">Open Full ↗</a>
    </div>
  </div>
  <iframe id="markup-frame" src="http://localhost:8088" 
    style="width:100%;height:600px;border:none;background:var(--surface);"
    sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
    loading="lazy"></iframe>
  <div id="markup-offline" style="display:none; padding:30px; text-align:center;">
    <p style="color:var(--muted);">Markup server offline</p>
    <p class="small">Start it on Bob: <code style="color:var(--gold);">python3 ~/AI-Server/tools/markup_app/server.py --port 8088</code></p>
  </div>
</div>
```

Add JS to check markup health and toggle iframe vs offline message:
```javascript
async function checkMarkupHealth() {
  try {
    const r = await fetch('http://localhost:8088/health', {signal: AbortSignal.timeout(3000)});
    if (r.ok) {
      document.getElementById('markup-frame').style.display = 'block';
      document.getElementById('markup-offline').style.display = 'none';
      document.getElementById('markup-status').textContent = 'online';
      document.getElementById('markup-status').style.color = 'var(--green)';
    } else throw new Error();
  } catch {
    document.getElementById('markup-frame').style.display = 'none';
    document.getElementById('markup-offline').style.display = 'block';
    document.getElementById('markup-status').textContent = 'offline';
    document.getElementById('markup-status').style.color = 'var(--red)';
  }
}
```

Call `checkMarkupHealth()` when switching to the Symphony tab, and every 30s while visible.

---

### Section 2: Proposals

The proposals service runs in Docker on port 8091 with endpoints:
- `POST /proposals/generate` — generate a new proposal
- `POST /proposals/revise` — revise existing
- `GET /proposals/{id}` — fetch one
- `GET /proposals/templates/list` — list templates
- `POST /proposals/send-email` — email to client

Build a proposals card with:

```html
<div class="card">
  <h2>Proposals</h2>
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
    <div>
      <div class="stat-label">Templates</div>
      <div id="proposal-templates-count" class="stat-big">—</div>
    </div>
    <div>
      <div class="stat-label">Service</div>
      <div id="proposal-service-status" class="small">checking...</div>
    </div>
  </div>
  
  <div style="margin-bottom:10px;">
    <label class="small" style="display:block;margin-bottom:4px;">Quick Generate</label>
    <select id="proposal-template" style="background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:6px 10px;width:100%;font-size:12px;">
      <option value="">Select template...</option>
    </select>
  </div>
  
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
    <input id="proposal-client" placeholder="Client name" style="background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:6px 10px;font-size:12px;" />
    <input id="proposal-project" placeholder="Project name" style="background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:6px 10px;font-size:12px;" />
  </div>
  
  <button class="btn" onclick="generateProposal()" id="proposal-gen-btn">Generate Proposal</button>
  <div id="proposal-result" style="margin-top:10px;display:none;" class="small"></div>
</div>
```

Add JS:
```javascript
async function loadProposalTemplates() {
  try {
    const r = await fetch('/api/symphony/proposals/templates');
    if (!r.ok) throw new Error();
    const data = await r.json();
    const sel = document.getElementById('proposal-template');
    sel.innerHTML = '<option value="">Select template...</option>';
    (data.templates || []).forEach(t => {
      sel.innerHTML += `<option value="${t}">${t.replace(/_/g,' ')}</option>`;
    });
    document.getElementById('proposal-templates-count').textContent = (data.templates || []).length;
    document.getElementById('proposal-service-status').textContent = 'online';
    document.getElementById('proposal-service-status').style.color = 'var(--green)';
  } catch {
    document.getElementById('proposal-service-status').textContent = 'offline';
    document.getElementById('proposal-service-status').style.color = 'var(--red)';
  }
}

async function generateProposal() {
  const template = document.getElementById('proposal-template').value;
  const client = document.getElementById('proposal-client').value;
  const project = document.getElementById('proposal-project').value;
  if (!template || !client) { alert('Select a template and enter client name'); return; }
  
  document.getElementById('proposal-gen-btn').disabled = true;
  document.getElementById('proposal-gen-btn').textContent = 'Generating...';
  
  try {
    const r = await fetch('/api/symphony/proposals/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({template, client_name: client, project_name: project || client + ' Project'})
    });
    const data = await r.json();
    const resultEl = document.getElementById('proposal-result');
    resultEl.style.display = 'block';
    if (data.proposal_id) {
      resultEl.innerHTML = `<span style="color:var(--green)">Generated: ${data.proposal_id}</span>`;
    } else {
      resultEl.innerHTML = `<span style="color:var(--red)">Error: ${data.detail || 'unknown'}</span>`;
    }
  } catch(e) {
    document.getElementById('proposal-result').style.display = 'block';
    document.getElementById('proposal-result').innerHTML = `<span style="color:var(--red)">Failed to connect</span>`;
  }
  document.getElementById('proposal-gen-btn').disabled = false;
  document.getElementById('proposal-gen-btn').textContent = 'Generate Proposal';
}
```

---

### Section 3: Client Portal

The client portal runs in Docker (port 8096 internal, no host port). Shows portal status and recent submissions.

```html
<div class="card">
  <h2>Client Portal</h2>
  <div id="portal-status" class="small" style="margin-bottom:8px;">checking...</div>
  <div id="portal-submissions" class="small" style="color:var(--muted);">No recent submissions</div>
</div>
```

---

### Section 4: Agreement Generator

`tools/generate_agreement.py` generates .docx addendum files. Build a form:

```html
<div class="card">
  <h2>Agreement Generator</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">
    <input id="agree-client" placeholder="Client name" style="background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:6px 10px;font-size:12px;" />
    <input id="agree-project" placeholder="Project name" style="background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:6px 10px;font-size:12px;" />
  </div>
  <textarea id="agree-items" placeholder="Equipment items (comma-separated)" rows="2" style="width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:6px 10px;font-size:12px;resize:vertical;"></textarea>
  <div style="margin-top:8px;">
    <button class="btn" onclick="generateAgreement()">Generate .docx</button>
  </div>
  <div id="agree-result" style="margin-top:8px;display:none;" class="small"></div>
</div>
```

---

### Section 5: Quick Tools Grid

A grid of quick-access tool buttons that trigger existing tools:

```html
<div class="card">
  <h2>Quick Tools</h2>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
    <button class="btn" onclick="runTool('room_mapper')" title="Analyze project room layouts">Room Mapper</button>
    <button class="btn" onclick="runTool('project_analyzer')" title="Analyze project SKU coverage">Project Analyzer</button>
    <button class="btn" onclick="runTool('proposal_to_dtools')" title="Export proposal to D-Tools CSV">Proposal → D-Tools</button>
    <button class="btn" onclick="runTool('build_inventory')" title="Build inventory from D-Tools">Build Inventory</button>
    <button class="btn" onclick="runTool('fetch_manuals')" title="Fetch product manuals">Fetch Manuals</button>
    <button class="btn" onclick="runTool('cortex_curator')" title="Run Cortex knowledge curation">Cortex Curator</button>
    <button class="btn" onclick="runTool('knowledge_graph')" title="View knowledge graph">Knowledge Graph</button>
    <button class="btn" onclick="runTool('maintenance')" title="Run Bob maintenance (cleanup)">Maintenance</button>
  </div>
  <div id="tool-output" style="margin-top:10px;display:none;max-height:200px;overflow-y:auto;padding:8px;background:var(--surface-2);border-radius:4px;font-family:var(--mono);font-size:11px;white-space:pre-wrap;"></div>
</div>
```

---

### Section 6: Cortex Knowledge Stats

Pull from existing Cortex endpoints and show memory stats:

```html
<div class="card">
  <h2>Cortex Knowledge</h2>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
    <div><div class="stat-big" id="cortex-total">—</div><div class="stat-label">Total Memories</div></div>
    <div><div class="stat-big" id="cortex-goals">—</div><div class="stat-label">Active Goals</div></div>
    <div><div class="stat-big" id="cortex-rules">—</div><div class="stat-label">Trading Rules</div></div>
  </div>
  <div style="margin-top:10px;">
    <button class="btn" onclick="triggerImprovement()">Run Improvement Cycle</button>
    <button class="btn" onclick="loadDigest()">Today's Digest</button>
  </div>
  <div id="cortex-digest" style="margin-top:10px;display:none;max-height:300px;overflow-y:auto;padding:10px;background:var(--surface-2);border-radius:4px;font-size:12px;"></div>
</div>
```

---

## Backend API Routes

Add a new section to `cortex/dashboard.py` inside `register_dashboard_routes()` with Symphony Ops proxy endpoints:

```python
# ── Symphony Ops proxies ────────────────────────────────────────────────

PROPOSALS_URL = os.environ.get("PROPOSALS_URL", "http://proposals:8091")
CLIENT_PORTAL_URL = os.environ.get("CLIENT_PORTAL_URL", "http://client-portal:8096")
MARKUP_URL = os.environ.get("MARKUP_URL", "http://host.docker.internal:8088")

@app.get("/api/symphony/proposals/templates")
async def symphony_proposals_templates():
    data = await _safe_get(f"{PROPOSALS_URL}/proposals/templates/list")
    return data or {"templates": [], "error": "proposals service unavailable"}

@app.post("/api/symphony/proposals/generate")
async def symphony_proposals_generate(request: dict):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{PROPOSALS_URL}/proposals/generate", json=request)
            return resp.json()
    except Exception as exc:
        return {"error": str(exc)}

@app.get("/api/symphony/portal/health")
async def symphony_portal_health():
    data = await _safe_get(f"{CLIENT_PORTAL_URL}/health")
    return data or {"status": "offline"}

@app.post("/api/symphony/agreement/generate")
async def symphony_generate_agreement(request: dict):
    """Run generate_agreement.py and return the .docx path."""
    import subprocess
    cmd = [
        "python3", "/app/tools/generate_agreement.py",
        "--client", request.get("client", ""),
        "--project", request.get("project", ""),
        "--items", request.get("items", ""),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"output": result.stdout.strip(), "error": result.stderr.strip() if result.returncode != 0 else None}
    except Exception as exc:
        return {"error": str(exc)}

@app.post("/api/symphony/tools/{tool_name}")
async def symphony_run_tool(tool_name: str, request: dict = {}):
    """Run a Symphony business tool by name."""
    tool_map = {
        "room_mapper": "python3 /app/tools/bob_room_mapper.py",
        "project_analyzer": "python3 /app/tools/bob_project_analyzer.py",
        "proposal_to_dtools": "python3 /app/tools/bob_proposal_to_dtools.py",
        "build_inventory": "python3 /app/tools/bob_build_inventory.py",
        "fetch_manuals": "python3 /app/tools/bob_fetch_manuals.py",
        "cortex_curator": "python3 /app/tools/cortex_curator.py --run --json",
        "knowledge_graph": "python3 /app/tools/knowledge_graph.py --status",
        "maintenance": "python3 /app/tools/bob_maintenance.py --dry",
    }
    cmd = tool_map.get(tool_name)
    if not cmd:
        return {"error": f"Unknown tool: {tool_name}"}
    
    args = request.get("args", "")
    if args:
        cmd += f" {args}"
    
    import subprocess
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
            cwd="/app"
        )
        return {
            "tool": tool_name,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Tool timed out (60s limit)"}
    except Exception as exc:
        return {"error": str(exc)}

@app.get("/api/symphony/cortex/stats")
async def symphony_cortex_stats():
    """Get cortex memory/goal/rule stats for the Symphony Ops panel."""
    eng = engine_ref()
    if eng is None:
        return {"total": 0, "active_goals": 0, "rules": 0}
    stats = eng.memory.get_stats()
    rules = eng.memory.get_rules(category="trading_rule", min_confidence=0.6)
    return {
        "total": stats.get("total", 0),
        "active_goals": stats.get("active_goals", 0),
        "rules": len(rules),
    }
```

---

## Layout

The Symphony Ops panel uses a 2-column grid on desktop, 1-column on mobile:

```html
<div id="panel-symphony" class="tab-panel" style="padding:16px 22px 80px;">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <!-- Left column -->
    <div style="display:flex;flex-direction:column;gap:14px;grid-column:1 / -1;">
      <!-- Markup Tool (full width) -->
    </div>
    <div style="display:flex;flex-direction:column;gap:14px;">
      <!-- Proposals -->
      <!-- Agreement Generator -->
      <!-- Cortex Knowledge -->
    </div>
    <div style="display:flex;flex-direction:column;gap:14px;">
      <!-- Client Portal -->
      <!-- Quick Tools -->
    </div>
  </div>
</div>
```

Add responsive CSS:
```css
@media (max-width: 900px) {
  #panel-symphony > div { grid-template-columns: 1fr; }
}
```

---

## Docker Volume Mount

The tools directory needs to be accessible from within the cortex container. Add to `docker-compose.yml` under the `cortex` service volumes:

```yaml
    volumes:
      - ./cortex:/app/cortex
      - ./data/cortex:/data/cortex
      - ./tools:/app/tools          # ADD THIS - for Symphony Ops tool execution
      - ./knowledge:/app/knowledge  # ADD THIS - tools need knowledge base access
```

---

## Markup Port Change

In `tools/markup_app/server.py`, change the default port:
- Find: `parser.add_argument("--port", type=int, default=8091`
- Replace: `parser.add_argument("--port", type=int, default=8088`
- Also update the docstring at the top of the file from 8091 to 8088
- Update the README.md references from 8091 to 8088

---

## Implementation Order

1. Update `tools/markup_app/server.py` default port to 8088 and update its README
2. Add Symphony Ops proxy endpoints to `cortex/dashboard.py`
3. Add the `tools` and `knowledge` volume mounts to `docker-compose.yml` cortex service
4. Add the Symphony Ops tab button and panel to `cortex/static/index.html`
5. Add all JavaScript for: markup health check, proposal loading, tool execution, cortex stats
6. Add `PROPOSALS_URL`, `CLIENT_PORTAL_URL`, `MARKUP_URL` environment variables to cortex service in `docker-compose.yml`
7. Test: switch to Symphony Ops tab, verify markup iframe loads (or shows offline gracefully), verify proposals templates load, verify tool buttons return output
8. Commit and push

---

## Key Constraints

- **No bare `git pull`** — use `bash scripts/pull.sh` for AI-Server repo
- **No `#` characters in bash scripts** — replace with alternatives
- **All new API routes go inside `register_dashboard_routes()`** to keep the pattern consistent
- **All proxy calls use `_safe_get()` or `httpx.AsyncClient(timeout=...)` with try/except** — a downstream failure must never crash Cortex
- **Match the existing dashboard design system** — use the same CSS variables (var(--bg), var(--surface), var(--gold), etc.), card styles, stat atoms, and button classes
- **The markup app runs on HOST, not Docker** — it needs macOS filesystem access for iCloud sync. The iframe connects to `localhost:8088` (or LAN IP)
- **Proposals service is in Docker** — proxy through Cortex API, not direct browser connection
