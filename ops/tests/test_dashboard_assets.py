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
