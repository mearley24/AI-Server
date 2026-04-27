"""Smoke test for the Cortex dashboard static asset split.

After refactoring cortex/static/index.html from a monolithic single-file
SPA into slim HTML + external CSS + external JS, this test protects the
structural contract so a future edit cannot silently break the dashboard:

  - The three asset files exist on disk.
  - index.html references the external CSS and JS by the exact paths the
    cortex /static mount serves from.
  - index.html no longer carries an inline <style> or <script> block
    (those would silently shadow the external assets and mask breakage).
  - The referenced asset files are non-empty.

Kept intentionally tiny. Does not boot FastAPI — the Cortex engine has
heavy import-time side effects (DB, embeddings). The dashboard route
handler itself is a thin FileResponse + RedirectResponse; its contract
is already covered by the static-file contract below.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = REPO_ROOT / "cortex" / "static"


def test_dashboard_static_files_exist() -> None:
    assert (STATIC_DIR / "index.html").is_file()
    assert (STATIC_DIR / "dashboard.css").is_file()
    assert (STATIC_DIR / "dashboard.js").is_file()


def test_dashboard_static_files_nonempty() -> None:
    assert (STATIC_DIR / "dashboard.css").stat().st_size > 0
    assert (STATIC_DIR / "dashboard.js").stat().st_size > 0


def test_index_html_references_external_assets() -> None:
    html = (STATIC_DIR / "index.html").read_text()
    # Paths must match the FastAPI static mount in cortex/dashboard.py
    # (app.mount("/static", StaticFiles(directory=STATIC_DIR), ...))
    assert '/static/dashboard.css' in html
    assert '/static/dashboard.js' in html


def test_index_html_has_no_inline_style_or_script() -> None:
    html = (STATIC_DIR / "index.html").read_text()
    # The split removed the inline <style>…</style> and inline
    # <script>…</script> blocks. A reintroduced inline block would be a
    # regression: it either duplicates rules and drifts, or silently
    # shadows the external file.
    # We allow <script src="…"> (external ref) but not a bare <script>
    # opening tag. Same for <style>.
    assert '<style>' not in html and '<style ' not in html
    # script with src attribute is fine; a raw "<script>" without src is not
    assert '<script>' not in html


def test_dashboard_js_is_strict_iife() -> None:
    """Cheap sanity check that extraction preserved the IIFE wrapper."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert js.lstrip().startswith("'use strict';")
    assert js.rstrip().endswith("})();")


def test_dashboard_route_serves_html_and_assets() -> None:
    """Route-level smoke: /dashboard returns HTML that references the
    externalized CSS/JS, and /static serves both of them with 200.

    Uses FastAPI's TestClient against a bare app wired only to
    register_dashboard_routes, so the heavy CortexEngine is never
    instantiated.
    """
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        import pytest
        pytest.skip("fastapi/httpx not installed in this env")
        return

    from cortex.dashboard import register_dashboard_routes

    app = FastAPI()
    register_dashboard_routes(app, lambda: None)
    client = TestClient(app)

    r = client.get("/dashboard")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "/static/dashboard.css" in r.text
    assert "/static/dashboard.js" in r.text

    css = client.get("/static/dashboard.css")
    js = client.get("/static/dashboard.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert css.content and js.content


# ── Tool access registry ────────────────────────────────────────────────────
#
# Protects the contract between cortex/dashboard.py's TOOL_REGISTRY and the
# dashboard UI so future edits to the registry don't silently break rendering.


def _wire_bare_app():
    """Spin up a FastAPI app with only dashboard routes — no CortexEngine."""
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cortex.dashboard import register_dashboard_routes
    app = FastAPI()
    register_dashboard_routes(app, lambda: None)
    return TestClient(app)


def test_api_tools_returns_registry():
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/tools")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data and isinstance(data["tools"], list)
    assert data["count"] == len(data["tools"])
    # Tailscale identity is surfaced for the UI to render.
    assert data["tailscale"]["ip"] == "100.89.1.51"
    assert data["tailscale"]["fqdn"] == "bobs-mac-mini.tailbcf3fe.ts.net"
    # Every entry has the keys the frontend renderer reads.
    required = {"name", "tab", "category", "port", "status", "notes",
                "local_url", "tailscale_url", "tailscale_fqdn_url"}
    for tool in data["tools"]:
        assert required.issubset(tool.keys()), f"missing keys on {tool}"
    # Tabs must match the dashboard tab panel ids.
    valid_tabs = {"overview", "xintake", "symphony", "autonomy"}
    assert {t["tab"] for t in data["tools"]} <= valid_tabs


def test_api_tools_filter_by_tab():
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/tools?tab=symphony")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] > 0
    assert all(t["tab"] == "symphony" for t in data["tools"])
    # Markup Tool lives on the symphony tab — regression guard for the
    # primary tool the user called out.
    names = {t["name"] for t in data["tools"]}
    assert "Markup Tool" in names


def test_api_tools_cortex_entry_has_tailscale_urls():
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/tools?tab=overview").json()
    cortex = next((t for t in data["tools"] if t["name"] == "Cortex Dashboard"), None)
    assert cortex is not None, "Cortex Dashboard must be in the registry"
    assert cortex["port"] == 8102
    assert cortex["local_url"] == "http://127.0.0.1:8102/dashboard"
    # URLs are still surfaced so the UI can light up the moment
    # `tailscale serve` publishes 8102, but Cortex is Docker-bound
    # 127.0.0.1:8102 today — flagged lan_only post the 2026-04-24
    # wildcard-listener fix (file-watcher rebound to 127.0.0.1:8103).
    assert cortex["tailscale_url"] == "http://100.89.1.51:8102/dashboard"
    assert (
        cortex["tailscale_fqdn_url"]
        == "http://bobs-mac-mini.tailbcf3fe.ts.net:8102/dashboard"
    )
    assert cortex["status"] == "lan_only"
    # Guard against re-introducing the stale "Currently binds *:8102"
    # claim. The note can still describe the prior wildcard as history,
    # but must not describe it as the current state.
    assert "Currently binds *:8102" not in cortex["notes"], (
        "Cortex note still claims *:8102 wildcard as current; the wildcard "
        "was host file-watcher, rebound to 127.0.0.1:8103 on 2026-04-24."
    )


def test_index_html_has_tool_access_containers():
    """The renderer targets these ids; if they disappear, the UI breaks."""
    html = (STATIC_DIR / "index.html").read_text()
    for tab in ("overview", "xintake", "symphony", "autonomy"):
        assert f'id="tool-access-{tab}"' in html, (
            f"missing tool-access container for tab={tab}"
        )


def test_dashboard_js_wires_tool_access():
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "loadToolAccess" in js
    assert "/api/tools" in js


# ── Voice Receptionist registry + UI contract ────────────────────────────────
#
# Cortex surfaces Bob the Conductor (voice_receptionist/) on the Symphony tab
# and on the Overview "Calls" card. The UI renders the empty state from a
# stable shape returned by /api/symphony/voice-receptionist; protect that
# contract so future edits cannot silently break the calls dashboard.


def test_api_tools_has_voice_receptionist_entry():
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/tools?tab=symphony").json()
    voice = next(
        (t for t in data["tools"] if t["name"] == "Voice Receptionist"),
        None,
    )
    assert voice is not None, "Voice Receptionist must be in the registry"
    # Per PORTS.md: container 3000 → host 127.0.0.1:8093
    assert voice["port"] == 8093
    assert voice["category"] == "Communication"
    assert voice["tab"] == "symphony"
    assert voice["status"] == "lan_only"
    assert voice["local_url"] == "http://127.0.0.1:8093/"
    assert voice["health_url"] == "http://127.0.0.1:8093/health"
    # Notes must reference the planned Twilio/OpenAI ingestion path so
    # future readers know where to wire Cortex ingestion.
    assert "Twilio" in voice["notes"]
    assert "ops:voice_followup" in voice["notes"]


def test_index_html_has_calls_cards():
    """The overview Calls card and the Symphony voice-receptionist card
    are both rendered by dashboard.js — guard their target ids."""
    html = (STATIC_DIR / "index.html").read_text()
    assert 'id="calls-card"' in html, "missing overview Calls card"
    assert 'id="calls"' in html, "missing #calls render target"
    assert 'id="calls-symphony-card"' in html, (
        "missing symphony Voice Receptionist card"
    )
    assert 'id="calls-symphony"' in html, (
        "missing #calls-symphony render target"
    )


def test_dashboard_js_wires_voice_receptionist():
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "renderCalls" in js
    assert "renderCallsSymphony" in js
    assert "/api/symphony/voice-receptionist" in js
    assert "loadVoiceReceptionist" in js


def test_api_voice_receptionist_returns_planned_contract():
    """When the upstream service is offline (it is, in tests), the route
    still returns the stable shape the frontend renders — status block
    plus the `planned` fields/actions contract."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/symphony/voice-receptionist")
    assert r.status_code == 200
    data = r.json()
    # Service block — status + url always present
    assert "service" in data
    svc = data["service"]
    assert svc["status"] in {"online", "degraded", "offline", "unknown"}
    assert "url" in svc and svc["url"]
    assert "checked_at" in svc
    # Empty arrays for the call/voicemail lists — no fake data
    assert data["recent_calls"] == []
    assert data["missed_calls"] == []
    assert data["voicemails"] == []
    # Planned contract — fields + actions + redis channel
    planned = data.get("planned") or {}
    assert planned.get("redis_channel") == "ops:voice_followup"
    fields = set(planned.get("fields") or [])
    # Fields the receptionist integration plan promises the UI
    assert {
        "caller_name", "phone", "started_at", "transcript_excerpt",
        "matched_client", "suggested_followup",
    }.issubset(fields)
    actions = set(planned.get("actions") or [])
    assert {
        "send_text", "send_email", "create_intake", "escalate_to_matt",
    }.issubset(actions)


# ── Dashboard audit-summary endpoint ────────────────────────────────────────


def test_api_dashboard_audit_summary_shape():
    """GET /api/dashboard/audit-summary returns required top-level keys."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/dashboard/audit-summary")
    assert r.status_code == 200
    data = r.json()
    required_keys = {
        "as_of", "live_sections", "failing_sections", "stale_sections",
        "debug_only_sections", "planned_sections",
        "recommendation_count", "fixes_applied_count",
    }
    assert required_keys.issubset(data.keys()), (
        f"missing keys: {required_keys - set(data.keys())}"
    )


def test_api_dashboard_audit_summary_live_sections_nonempty():
    """live_sections must be a non-empty list."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/audit-summary").json()
    assert isinstance(data["live_sections"], list)
    assert len(data["live_sections"]) > 0


def test_api_dashboard_audit_summary_failing_sections_have_priority():
    """Each failing_section entry has section, endpoint, reason, and priority."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/audit-summary").json()
    for entry in data.get("failing_sections", []):
        assert "section" in entry
        assert "endpoint" in entry
        assert "reason" in entry
        assert "priority" in entry


def test_api_dashboard_audit_summary_vault_fix_applied():
    """debug_only_sections must include vault with fix_applied=True."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/audit-summary").json()
    debug_sections = data.get("debug_only_sections", [])
    vault_entry = next((s for s in debug_sections if s.get("section") == "vault"), None)
    assert vault_entry is not None, "vault must appear in debug_only_sections"
    assert vault_entry.get("fix_applied") is True


def test_api_dashboard_audit_summary_counts_are_ints():
    """recommendation_count and fixes_applied_count must be non-negative ints."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/audit-summary").json()
    assert isinstance(data["recommendation_count"], int)
    assert isinstance(data["fixes_applied_count"], int)
    assert data["recommendation_count"] >= 0
    assert data["fixes_applied_count"] >= 0


# ── Dashboard audit card — HTML + JS structural tests ───────────────────────


def test_index_html_has_dashboard_audit_card():
    """Debug tab must contain the dashboard-audit-card element."""
    html = (STATIC_DIR / "index.html").read_text()
    assert 'id="dashboard-audit-card"' in html, "missing #dashboard-audit-card in index.html"
    assert 'id="dashboard-audit"' in html, "missing #dashboard-audit render target in index.html"


def test_dashboard_js_calls_audit_summary_endpoint():
    """dashboard.js must fetch /api/dashboard/audit-summary."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "/api/dashboard/audit-summary" in js, (
        "dashboard.js does not call /api/dashboard/audit-summary"
    )


def test_dashboard_js_has_render_dashboard_audit():
    """dashboard.js must define renderDashboardAudit and call it."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "renderDashboardAudit" in js, "renderDashboardAudit function missing from dashboard.js"


def test_dashboard_js_audit_renders_failing_and_stale():
    """renderDashboardAudit must reference failing_sections and stale_sections."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "failing_sections" in js
    assert "stale_sections" in js


def test_api_dashboard_audit_summary_rendered_on_page():
    """GET /dashboard HTML includes the audit card div (served statically)."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "dashboard-audit-card" in r.text, "audit card not present in served dashboard HTML"
    assert "dashboard-audit" in r.text


# ── Dashboard Cleanup v1 — layout structural tests ──────────────────────────


def test_today_tab_has_needs_attention_card():
    """tab-overview must contain the today-needs-attention card."""
    html = (STATIC_DIR / "index.html").read_text()
    assert 'id="today-needs-attention-card"' in html, (
        "missing #today-needs-attention-card in index.html"
    )
    assert 'id="today-needs-attention"' in html, (
        "missing #today-needs-attention render target"
    )
    # Confirm it's inside tab-overview, not another tab
    tab_overview_start = html.find('id="tab-overview"')
    tab_overview_end = html.find('id="tab-', tab_overview_start + 1)
    overview_html = html[tab_overview_start:tab_overview_end]
    assert 'id="today-needs-attention-card"' in overview_html, (
        "#today-needs-attention-card must be inside tab-overview"
    )


def test_stale_widgets_not_in_today_tab():
    """Stale/noisy sections (decisions, meetings, activity) must not appear in tab-overview."""
    html = (STATIC_DIR / "index.html").read_text()
    tab_overview_start = html.find('id="tab-overview"')
    tab_overview_end = html.find('id="tab-', tab_overview_start + 1)
    overview_html = html[tab_overview_start:tab_overview_end]
    assert 'id="decisions"' not in overview_html, (
        "#decisions (stale) must not be in tab-overview"
    )
    assert 'id="meetings"' not in overview_html, (
        "#meetings (stale) must not be in tab-overview"
    )
    assert 'id="activity"' not in overview_html, (
        "#activity (noisy) must not be in tab-overview"
    )


def test_money_tab_has_exposure_and_safe_to_fund():
    """tab-money must contain both polyexposure and safe-to-fund cards."""
    html = (STATIC_DIR / "index.html").read_text()
    tab_money_start = html.find('id="tab-money"')
    assert tab_money_start != -1, "missing tab-money panel"
    tab_money_end = html.find('id="tab-', tab_money_start + 1)
    money_html = html[tab_money_start:tab_money_end]
    assert 'id="polyexposure"' in money_html, (
        "#polyexposure must be inside tab-money"
    )
    assert 'id="safe-to-fund"' in money_html, (
        "#safe-to-fund must be inside tab-money"
    )


def test_debug_tab_has_dashboard_audit():
    """tab-debug must contain the dashboard-audit card."""
    html = (STATIC_DIR / "index.html").read_text()
    tab_debug_start = html.find('id="tab-debug"')
    assert tab_debug_start != -1, "missing tab-debug panel"
    tab_debug_end = html.find('id="tab-', tab_debug_start + 1)
    # tab-debug may be the last panel, so handle end-of-file
    debug_html = html[tab_debug_start:] if tab_debug_end == -1 else html[tab_debug_start:tab_debug_end]
    assert 'id="dashboard-audit-card"' in debug_html, (
        "#dashboard-audit-card must be inside tab-debug"
    )


def test_dashboard_js_has_today_and_safe_to_fund_renderers():
    """dashboard.js must define renderTodayNeedsAttention and renderSafeToFund."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "renderTodayNeedsAttention" in js, (
        "renderTodayNeedsAttention missing from dashboard.js"
    )
    assert "renderSafeToFund" in js, (
        "renderSafeToFund missing from dashboard.js"
    )


# ── Data Freshness v2 — structural tests ────────────────────────────────────


def test_dashboard_js_freshness_helpers():
    """dashboard.js must define the freshness system helpers."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "freshnessTier" in js, "freshnessTier helper missing from dashboard.js"
    assert "freshnessTag" in js,  "freshnessTag helper missing from dashboard.js"
    assert "ageSeconds" in js,    "ageSeconds helper missing from dashboard.js"
    assert "emptyState" in js,    "emptyState helper missing from dashboard.js"
    assert "_debugMode" in js,    "_debugMode flag missing from dashboard.js"


def test_dashboard_js_activity_capped_at_ten():
    """renderActivity must cap items at 10, not 5."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    # Ensure the function contains slice(0, 10) and NOT slice(0, 5) for activity
    activity_start = js.find("function renderActivity(")
    activity_end   = js.find("\n  function ", activity_start + 1)
    activity_fn    = js[activity_start:activity_end]
    assert "slice(0, 10)" in activity_fn, (
        "renderActivity must cap at 10 items"
    )
    assert "slice(0, 5)" not in activity_fn, (
        "renderActivity still uses old 5-item cap"
    )


def test_dashboard_js_decisions_respects_debug_mode():
    """renderDecisions must check _debugMode before filtering."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    decisions_start = js.find("function renderDecisions(")
    decisions_end   = js.find("\n  function ", decisions_start + 1)
    decisions_fn    = js[decisions_start:decisions_end]
    assert "_debugMode" in decisions_fn, (
        "renderDecisions must check _debugMode to bypass freshness filtering"
    )
    assert "_FRESH_RECENT_SECS" in decisions_fn, (
        "renderDecisions must apply the 24h RECENT threshold"
    )


def test_dashboard_js_meetings_filters_stale():
    """renderMeetings must filter out archive-age rows in normal mode."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    meetings_start = js.find("function renderMeetings(")
    meetings_end   = js.find("\n  function ", meetings_start + 1)
    meetings_fn    = js[meetings_start:meetings_end]
    assert "_FRESH_STALE_SECS" in meetings_fn, (
        "renderMeetings must apply the 7-day STALE threshold"
    )
    assert "_debugMode" in meetings_fn, (
        "renderMeetings must respect _debugMode to bypass filtering"
    )


def test_api_dashboard_config_returns_debug_flag():
    """GET /api/dashboard/config must return debug_mode bool and thresholds."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/dashboard/config")
    assert r.status_code == 200
    data = r.json()
    assert "debug_mode" in data, "debug_mode key missing from /api/dashboard/config"
    assert isinstance(data["debug_mode"], bool), "debug_mode must be a bool"
    thresholds = data.get("freshness_thresholds", {})
    assert thresholds.get("active_secs") == 3_600, "active_secs must be 3600"
    assert thresholds.get("recent_secs") == 86_400, "recent_secs must be 86400"


# ── Data Source Audit v3 — new endpoint + JS fix tests ──────────────────────


def test_api_data_source_audit_shape():
    """GET /api/dashboard/data-source-audit must return sources[] and totals."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/dashboard/data-source-audit")
    assert r.status_code == 200
    data = r.json()
    assert "sources" in data, "sources array missing"
    assert isinstance(data["sources"], list), "sources must be a list"
    assert len(data["sources"]) > 0, "sources must not be empty"
    assert "totals" in data, "totals object missing"
    totals = data["totals"]
    for key in ("live_sources", "stale_sources", "failing_sources"):
        assert key in totals, f"totals.{key} missing"
        assert isinstance(totals[key], int), f"totals.{key} must be int"


def test_api_data_source_audit_source_schema():
    """Each source entry must have card, tab, endpoint, and status fields."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/data-source-audit").json()
    required = {"card", "tab", "endpoint", "status"}
    valid_statuses = {"live", "failing", "stale", "synthetic", "debug_only"}
    for src in data["sources"]:
        assert required.issubset(src.keys()), f"missing keys on source: {src}"
        assert src["status"] in valid_statuses, (
            f"invalid status '{src['status']}' on {src['card']}"
        )


def test_api_data_source_audit_has_failing_sources():
    """Audit must flag wallet and follow-ups as failing (known broken)."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/data-source-audit").json()
    failing = {s["card"] for s in data["sources"] if s["status"] == "failing"}
    assert "Wallet" in failing, "Wallet must be listed as failing"
    assert "Follow-ups" in failing, "Follow-ups must be listed as failing"


def test_api_data_source_audit_has_synthetic_positions():
    """Audit must flag Positions as synthetic (paper trades)."""
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi not installed in this env")
        return
    client = _wire_bare_app()
    data = client.get("/api/dashboard/data-source-audit").json()
    synthetic = {s["card"] for s in data["sources"] if s["status"] == "synthetic"}
    assert "Positions" in synthetic, "Positions must be listed as synthetic"


def test_dashboard_js_positions_paper_badge():
    """renderPositions must check for paper- order_id prefix."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    positions_start = js.find("function renderPositions(")
    positions_end   = js.find("\n  function ", positions_start + 1)
    positions_fn    = js[positions_start:positions_end]
    assert "paper-" in positions_fn, (
        "renderPositions must check for paper- order_id prefix"
    )
    assert "paperBanner" in positions_fn or "sourceBanner" in positions_fn, (
        "renderPositions must render a paper truth-layer banner"
    )


def test_dashboard_js_activity_filters_health_checked():
    """renderActivity must filter health.checked noise in normal mode."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    activity_start = js.find("function renderActivity(")
    activity_end   = js.find("\n  function ", activity_start + 1)
    activity_fn    = js[activity_start:activity_end]
    assert "health.checked" in activity_fn, (
        "renderActivity must filter health.checked events"
    )
    assert "_debugMode" in activity_fn, (
        "renderActivity must respect _debugMode when filtering"
    )


def test_dashboard_js_decisions_filters_automation():
    """renderDecisions must filter category=jobs (D-Tools automation) in normal mode."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    decisions_start = js.find("function renderDecisions(")
    decisions_end   = js.find("\n  function ", decisions_start + 1)
    decisions_fn    = js[decisions_start:decisions_end]
    assert "jobs" in decisions_fn, (
        "renderDecisions must filter category=jobs (D-Tools automation)"
    )
    assert "_isAutomation" in decisions_fn or "isAutomation" in decisions_fn, (
        "renderDecisions must have automation filter helper"
    )


def test_dashboard_js_followups_db_error_state():
    """renderFollowups must show a specific error when DB is unavailable."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    followups_start = js.find("function renderFollowups(")
    followups_end   = js.find("\n  function ", followups_start + 1)
    followups_fn    = js[followups_start:followups_end]
    assert "DB unavailable" in followups_fn or "db not mounted" in followups_fn.lower(), (
        "renderFollowups must show explicit DB unavailable message"
    )
    assert "follow_ups.db" in followups_fn, (
        "renderFollowups must name the missing DB file"
    )


# ---------------------------------------------------------------------------
# v4 — Data Truth Layer tests
# ---------------------------------------------------------------------------

def test_dashboard_js_source_banner_helper():
    """sourceBanner() must be defined and handle real/paper/stale/broken types."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "function sourceBanner(" in js, "sourceBanner() helper must be defined"
    # Must define all four truth-layer classifications
    for label in ("REAL", "SIMULATED", "OUTDATED", "UNAVAILABLE"):
        assert label in js, f"sourceBanner must include label '{label}'"
    # Must reference badge classes
    for badge in ("badge-live", "badge-stale", "badge-debug", "badge-unavail"):
        assert badge in js, f"sourceBanner must reference badge class '{badge}'"


def test_dashboard_js_wallet_broken_detection():
    """renderWallet must classify broken state when Redis key not pushed (all zeros)."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    wallet_start = js.find("function renderWallet(")
    wallet_end   = js.find("\n  function ", wallet_start + 1)
    wallet_fn    = js[wallet_start:wallet_end]
    assert "isBroken" in wallet_fn, (
        "renderWallet must detect broken state (isBroken variable)"
    )
    assert "sourceBanner" in wallet_fn, (
        "renderWallet must use sourceBanner() for broken state"
    )
    assert "portfolio:snapshot" in wallet_fn, (
        "renderWallet broken message must reference Redis key portfolio:snapshot"
    )


def test_dashboard_js_positions_uses_source_banner():
    """renderPositions must use sourceBanner() for paper trade classification."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    positions_start = js.find("function renderPositions(")
    positions_end   = js.find("\n  function ", positions_start + 1)
    positions_fn    = js[positions_start:positions_end]
    assert "sourceBanner" in positions_fn, (
        "renderPositions must use sourceBanner() for paper trade banner"
    )
    assert "paper" in positions_fn, (
        "renderPositions must reference 'paper' type in sourceBanner call"
    )


def test_dashboard_js_pnl_paper_banner():
    """renderPnl must show paper simulation banner for cvd_arb data."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    pnl_start = js.find("function renderPnl(")
    pnl_end   = js.find("\n  function ", pnl_start + 1)
    pnl_fn    = js[pnl_start:pnl_end]
    assert "sourceBanner" in pnl_fn, (
        "renderPnl must use sourceBanner() for paper trade banner"
    )
    assert "paper" in pnl_fn, (
        "renderPnl must classify pnl as paper simulation data"
    )
    assert "cvd_arb" in pnl_fn or "simulation" in pnl_fn, (
        "renderPnl banner must mention simulation/cvd_arb context"
    )


def test_dashboard_js_watchdog_per_service_staleness():
    """renderWatchdog must classify each service by last-seen age, not just overall state."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    wd_start = js.find("function renderWatchdog(")
    wd_end   = js.find("\n  function ", wd_start + 1)
    wd_fn    = js[wd_start:wd_end]
    assert "_svcAge" in wd_fn or "svcAge" in wd_fn, (
        "renderWatchdog must compute per-service age"
    )
    assert "_svcClass" in wd_fn or "svcClass" in wd_fn, (
        "renderWatchdog must classify per-service staleness"
    )
    assert "stale" in wd_fn.lower(), (
        "renderWatchdog must surface stale service warning"
    )


def test_dashboard_js_reply_inbox_broken_on_error():
    """loadReplyInbox must show sourceBanner broken state on HTTP error."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    ri_start = js.find("window.loadReplyInbox")
    ri_end   = js.find("\n  window.", ri_start + 1)
    ri_fn    = js[ri_start:ri_end]
    assert "sourceBanner" in ri_fn, (
        "loadReplyInbox must use sourceBanner() for error state"
    )
    assert "resp.ok" in ri_fn or "resp.status" in ri_fn, (
        "loadReplyInbox must check HTTP response status"
    )


def test_dashboard_js_followups_uses_source_banner():
    """renderFollowups must use sourceBanner() for the broken DB state."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    followups_start = js.find("function renderFollowups(")
    followups_end   = js.find("\n  function ", followups_start + 1)
    followups_fn    = js[followups_start:followups_end]
    assert "sourceBanner" in followups_fn, (
        "renderFollowups must use sourceBanner() for DB error state"
    )
    assert "broken" in followups_fn, (
        "renderFollowups must classify DB unavailability as 'broken'"
    )


# ---------------------------------------------------------------------------
# Broken sources fix — follow-ups, wallet, decisions/activity noise
# ---------------------------------------------------------------------------

def test_followups_db_uses_immutable_mode():
    """follow_ups DB must be opened with immutable=1 URI to work on read-only mounts."""
    py = (REPO_ROOT / "cortex" / "dashboard.py").read_text()
    followups_start = py.find("async def api_followups(")
    followups_end   = py.find("\n    @app.", followups_start + 1)
    followups_fn    = py[followups_start:followups_end]
    assert "immutable=1" in followups_fn, (
        "api_followups must open DB with immutable=1 URI (read-only mount workaround)"
    )
    assert "uri=True" in followups_fn, (
        "api_followups must pass uri=True to sqlite3.connect"
    )


def test_wallet_reads_usdc_from_bot_status():
    """api_wallet must read USDC from strategies.redeemer.usdc_balance in bot status."""
    py = (REPO_ROOT / "cortex" / "dashboard.py").read_text()
    wallet_start = py.find("async def api_wallet(")
    wallet_end   = py.find("\n    @app.", wallet_start + 1)
    wallet_fn    = py[wallet_start:wallet_end]
    assert "redeemer" in wallet_fn, (
        "api_wallet must check strategies.redeemer for USDC balance"
    )
    assert "usdc_balance" in wallet_fn and "source_type" in wallet_fn, (
        "api_wallet must return source_type field for truth layer classification"
    )
    assert "matic_balance" in wallet_fn, (
        "api_wallet must expose matic_balance from redeemer section"
    )


def test_wallet_js_shows_matic_balance():
    """renderWallet must show MATIC/POL gas balance when non-zero."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    wallet_start = js.find("function renderWallet(")
    wallet_end   = js.find("\n  function ", wallet_start + 1)
    wallet_fn    = js[wallet_start:wallet_end]
    assert "matic_balance" in wallet_fn or "matic" in wallet_fn.lower(), (
        "renderWallet must expose MATIC/POL gas balance"
    )


def test_decisions_endpoint_has_exclude_automation_param():
    """api_decisions_recent must support exclude_automation query param."""
    py = (REPO_ROOT / "cortex" / "dashboard.py").read_text()
    decisions_start = py.find("async def api_decisions_recent(")
    decisions_end   = py.find("\n    @app.", decisions_start + 1)
    decisions_fn    = py[decisions_start:decisions_end]
    assert "exclude_automation" in decisions_fn, (
        "api_decisions_recent must accept exclude_automation query param"
    )
    assert "_AUTOMATION_CATEGORIES" in py or "automation_categories" in py.lower(), (
        "dashboard.py must define automation category filter set"
    )


def test_activity_endpoint_has_debug_param():
    """api_activity must support debug query param for noise filtering."""
    py = (REPO_ROOT / "cortex" / "dashboard.py").read_text()
    activity_start = py.find("async def api_activity(")
    activity_end   = py.find("\n    @app.", activity_start + 1)
    activity_fn    = py[activity_start:activity_end]
    assert "debug" in activity_fn, (
        "api_activity must accept debug query param"
    )
    assert "_ACTIVITY_NOISE_TYPES" in py or "noise_types" in py.lower(), (
        "dashboard.py must define activity noise type filter set"
    )


def test_activity_noise_filter_covers_jobs_synced():
    """Activity noise filter must include jobs.synced (D-Tools automation events)."""
    py = (REPO_ROOT / "cortex" / "dashboard.py").read_text()
    assert "jobs.synced" in py, (
        "dashboard.py must filter jobs.synced events in activity feed"
    )
    assert "heartbeat" in py, (
        "dashboard.py must filter heartbeat events in activity feed"
    )


def test_dashboard_js_activity_filters_jobs_synced():
    """renderActivity JS must filter jobs.synced events (D-Tools noise) in normal mode."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    activity_start = js.find("function renderActivity(")
    activity_end   = js.find("\n  function ", activity_start + 1)
    activity_fn    = js[activity_start:activity_end]
    assert "jobs.synced" in activity_fn, (
        "renderActivity must filter jobs.synced noise events in normal mode"
    )


def test_dashboard_js_debug_mode_uses_raw_endpoints():
    """In debug mode, dashboard.js must request unfiltered data from server."""
    js = (STATIC_DIR / "dashboard.js").read_text()
    assert "debug=true" in js or "debug=True" in js, (
        "dashboard.js must pass debug=true to activity endpoint in debug mode"
    )
    assert "exclude_automation=false" in js, (
        "dashboard.js must pass exclude_automation=false in debug mode"
    )
