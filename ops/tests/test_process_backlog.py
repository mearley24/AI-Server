"""Smoke + contract tests for the /api/process/* read-only endpoints.

The endpoints surface ops/BACKLOG.md (engineering process backlog) and
pointers to HANDOFF.md / ops/PROCESS_POLICY.md so the Cortex dashboard
can show the engineering workstreams without anyone opening the file.

These tests guard:
  - The canonical files exist and contain the expected scaffolding.
  - The parser extracts each ``### N. Title`` block with status/owner/lane/risk.
  - Counts are coherent (total == sum(by_status)).
  - The handoff endpoint returns paths for all three docs.

Heavy: this test boots a bare FastAPI app and registers the process
routes only. It does NOT instantiate CortexEngine — the engine has DB /
embedding side-effects we don't need here.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKLOG_PATH = REPO_ROOT / "ops" / "BACKLOG.md"
HANDOFF_PATH = REPO_ROOT / "HANDOFF.md"
POLICY_PATH = REPO_ROOT / "ops" / "PROCESS_POLICY.md"


# ── File-level contracts ─────────────────────────────────────────────────────


def test_canonical_process_files_exist():
    assert HANDOFF_PATH.is_file(), "HANDOFF.md must exist at repo root"
    assert BACKLOG_PATH.is_file(), "ops/BACKLOG.md must exist"
    assert POLICY_PATH.is_file(), "ops/PROCESS_POLICY.md must exist"


def test_backlog_has_expected_workstreams():
    """The 9 approved workstreams from the 2026-04-25 dedupe must be present.

    These titles come straight from the dedupe facts. If a future edit
    drops one without recording it under "Skipped / done", this test
    fails so the change becomes a deliberate decision.
    """
    text = BACKLOG_PATH.read_text(encoding="utf-8")
    expected_titles = [
        "Voice Receptionist",  # recent calls
        "Proposals",            # Zoho live send
        "Follow-Up Engine",
        "D-Tools",              # liveness
        "Client Intelligence",  # backfill + review queue
        "x-intake",             # live ACK smoke
        "Daily Briefing",       # v2 decision
        "Notification Hub",     # README + cortex surfacing
        "Mobile Gateway",       # unified action queue
    ]
    for title in expected_titles:
        assert title in text, f"backlog missing workstream containing {title!r}"


def test_backlog_marks_skipped_items():
    """Skipped/done items must remain documented so they don't get refiled."""
    text = BACKLOG_PATH.read_text(encoding="utf-8")
    # Phase 1 reply-actions, BB webhook leg, network monitoring, markup detector
    for marker in ("Reply-Actions Phase 1", "BlueBubbles webhook leg",
                   "Network monitoring", "Markup detector"):
        assert marker in text, f"missing skip-marker for {marker!r}"


def test_handoff_points_to_policy_and_backlog():
    text = HANDOFF_PATH.read_text(encoding="utf-8")
    assert "ops/BACKLOG.md" in text
    assert "ops/PROCESS_POLICY.md" in text
    assert "STATUS_REPORT.md" in text


def test_policy_split_is_explicit():
    text = POLICY_PATH.read_text(encoding="utf-8")
    # The whole point of the file is the split — guard it stays explicit.
    assert "Linear" in text and "Repo" in text and "Cortex" in text
    assert "live client" in text.lower() or "client / business" in text.lower()


# ── Parser contract (unit) ──────────────────────────────────────────────────


def test_parse_backlog_extracts_items_and_counts():
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from cortex.dashboard import _parse_backlog

    parsed = _parse_backlog(BACKLOG_PATH.read_text(encoding="utf-8"))
    items = parsed["items"]
    counts = parsed["counts"]

    # 9 active items expected
    active_items = [it for it in items if it["status"] != "skip" and it["id"] <= 9]
    assert len(active_items) == 9, (
        f"expected 9 active workstream entries, got {len(active_items)}: "
        f"{[it['title'] for it in active_items]}"
    )

    # Each parsed item must have the keys the frontend will consume.
    required_keys = {"id", "title", "status", "owner", "lane", "risk", "anchor"}
    for it in items:
        assert required_keys.issubset(it.keys()), f"missing keys on {it}"
        assert isinstance(it["id"], int)
        assert it["title"]
        # Status must be one of the documented values.
        assert it["status"] in {
            "todo", "in-progress", "blocked", "done", "skip", "unknown",
        }, f"unexpected status {it['status']!r} on item {it['id']}"

    # Counts coherent: sum(by_status) == total
    assert sum(counts["by_status"].values()) == counts["total"]
    # We have at least one blocked (Daily Briefing v2) and several todos.
    assert counts["by_status"].get("todo", 0) >= 5
    assert counts["by_status"].get("blocked", 0) >= 1


# ── Route-level smoke ───────────────────────────────────────────────────────


def _wire_bare_app():
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cortex.dashboard import register_process_routes
    app = FastAPI()
    register_process_routes(app)
    return TestClient(app)


def test_process_backlog_endpoint():
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi/httpx not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/process/backlog")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["source_label"] == "ops/BACKLOG.md"
    assert isinstance(data["items"], list)
    assert data["counts"]["total"] == len(data["items"])
    # At least the 9 active items show up.
    assert data["counts"]["total"] >= 9
    titles = [it["title"] for it in data["items"]]
    assert any("Voice Receptionist" in t for t in titles)
    assert any("Mobile Gateway" in t for t in titles)


def test_process_handoff_endpoint():
    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("fastapi/httpx not installed in this env")
        return
    client = _wire_bare_app()
    r = client.get("/api/process/handoff")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    docs = data["documents"]
    for key in ("handoff", "backlog", "policy"):
        assert docs[key]["exists"] is True, f"{key} doc missing in env"
        assert docs[key]["path"], f"{key} doc path missing"
    # Policy summary mentions all three surfaces so anyone hitting the
    # endpoint understands the split without reading the full file.
    summary = data["policy_summary"].lower()
    assert "linear" in summary and "repo" in summary and "cortex" in summary
