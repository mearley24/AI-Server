"""Tests for GET /api/watchdog/status endpoint.

Covers:
  - Returns status=ok and empty services with warning when state dir is missing
  - Returns correct service records from uh_* files
  - Recent events (< 3h) are marked degraded; old ones are ok
  - required_source file is skipped
  - Malformed file content does not crash endpoint
  - degraded_count matches degraded services count
  - No raw phone numbers exposed
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _no_raw_phone(obj: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, str):
        if re.search(r"\d{7,}", obj):
            hits.append(f"{path}={obj!r}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(_no_raw_phone(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(_no_raw_phone(v, f"{path}[{i}]"))
    return hits


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestWatchdogMissingDir:

    def test_missing_state_dir_returns_ok_with_warning(self, tmp_path):
        import cortex.engine as eng
        nonexistent = tmp_path / "nonexistent-watchdog"
        with patch.object(eng, "_WATCHDOG_STATE_DIR", nonexistent):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        assert result["status"] == "ok"
        assert result["degraded_count"] == 0
        assert result["services"] == []
        assert result["warning"] is not None
        assert "watchdog" in result["warning"].lower()

    def test_empty_state_dir_returns_warning(self, tmp_path):
        import cortex.engine as eng
        state_dir = tmp_path / "bob-watchdog-state"
        state_dir.mkdir()
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        assert result["status"] == "ok"
        assert result["warning"] is not None


class TestWatchdogStateFiles:

    def _make_state_dir(self, tmp_path, files: dict[str, Any]) -> Path:
        state_dir = tmp_path / "bob-watchdog-state"
        state_dir.mkdir()
        for name, ts in files.items():
            (state_dir / name).write_text(str(ts))
        return state_dir

    def test_old_events_are_ok(self, tmp_path):
        """Events older than 1h should have state=ok (service recovered)."""
        import cortex.engine as eng
        old_ts = time.time() - 2 * 3600  # 2h ago — beyond 1h threshold
        state_dir = self._make_state_dir(tmp_path, {"uh_openclaw": old_ts})
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        assert result["status"] == "ok"
        assert result["degraded_count"] == 0
        svc = result["services"][0]
        assert svc["state"] == "ok"
        assert svc["name"] == "OpenClaw"

    def test_event_between_1h_and_3h_is_ok(self, tmp_path):
        """Events 1–3h old are ok (recovered), not degraded — the OpenClaw case."""
        import cortex.engine as eng
        mid_ts = time.time() - 2.6 * 3600  # 2.6h ago — was 3h window, now 1h
        state_dir = self._make_state_dir(tmp_path, {"uh_openclaw": mid_ts})
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        assert result["status"] == "ok"
        assert result["degraded_count"] == 0

    def test_recent_event_is_degraded(self, tmp_path):
        """Events within 1h should have state=degraded and bump degraded_count."""
        import cortex.engine as eng
        recent_ts = time.time() - 30 * 60  # 30 min ago
        state_dir = self._make_state_dir(tmp_path, {"uh_vpn": recent_ts})
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        assert result["status"] == "degraded"
        assert result["degraded_count"] == 1
        svc = result["services"][0]
        assert svc["state"] == "degraded"
        assert svc["name"] == "VPN"

    def test_required_source_is_skipped(self, tmp_path):
        """required_source file must not appear in services list."""
        import cortex.engine as eng
        state_dir = self._make_state_dir(tmp_path, {
            "required_source": "override:/some/path",
        })
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        assert all(s["key"] != "required_source" for s in result["services"])
        assert result["services"] == []

    def test_malformed_file_does_not_crash(self, tmp_path):
        """Non-numeric content in a state file must be silently skipped."""
        import cortex.engine as eng
        state_dir = self._make_state_dir(tmp_path, {
            "uh_openclaw": "not-a-timestamp",
        })
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        # should not raise, should return ok
        assert result["status"] == "ok"
        assert result["services"] == []

    def test_degraded_count_matches_degraded_services(self, tmp_path):
        """degraded_count must equal the number of services with state=degraded."""
        import cortex.engine as eng
        now = time.time()
        state_dir = self._make_state_dir(tmp_path, {
            "uh_openclaw":    now - 30 * 60,    # recent → degraded
            "uh_vpn":         now - 45 * 60,    # recent → degraded
            "uh_x-alpha-collector": now - 6 * 3600,  # old → ok
        })
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        degraded_svcs = [s for s in result["services"] if s["state"] == "degraded"]
        assert result["degraded_count"] == len(degraded_svcs)
        assert result["degraded_count"] == 2

    def test_non_uh_files_have_recovery_event_type(self, tmp_path):
        """Files not prefixed uh_ should have event_type=recovery."""
        import cortex.engine as eng
        state_dir = self._make_state_dir(tmp_path, {
            "docker": time.time() - 2 * 3600,
        })
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        svc = result["services"][0]
        assert svc["event_type"] == "recovery"
        assert svc["name"] == "Docker engine"

    def test_no_raw_phone_in_response(self, tmp_path):
        """Response must never contain raw phone numbers."""
        import cortex.engine as eng
        state_dir = self._make_state_dir(tmp_path, {
            "uh_openclaw": time.time() - 5 * 3600,
        })
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", tmp_path / "hb.txt"):
                result = _run(eng.watchdog_status())
        hits = _no_raw_phone(result)
        assert hits == [], f"Raw phone found: {hits}"

    def test_heartbeat_used_as_updated_at(self, tmp_path):
        """updated_at should come from the heartbeat file."""
        import cortex.engine as eng
        # Need at least one valid file so we get past the empty-dir early return
        state_dir = self._make_state_dir(tmp_path, {
            "uh_openclaw": time.time() - 5 * 3600,
        })
        hb = tmp_path / "bob_watchdog_heartbeat.txt"
        hb.write_text("2026-04-26T13:00:22-0600")
        with patch.object(eng, "_WATCHDOG_STATE_DIR", state_dir):
            with patch.object(eng, "_WATCHDOG_HEARTBEAT", hb):
                result = _run(eng.watchdog_status())
        assert result["updated_at"] == "2026-04-26T13:00:22-0600"
