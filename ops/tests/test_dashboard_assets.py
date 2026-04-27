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
