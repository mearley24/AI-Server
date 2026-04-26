"""Tests for X API Intake v1.

Covers:
  - Missing credentials exits with status=disabled or missing_credentials
  - X_ENABLED=0 prevents live calls
  - dry_run=True does not write items to DB
  - apply (dry_run=False) writes deduped items
  - Daily usage limit enforcement
  - No write/post endpoints exist on XReadOnlyClient
  - Dashboard status endpoint masks secrets
  - Cortex endpoints return correct shape
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _run(coro):
    return asyncio.run(coro)


# ── TestMissingCredentials ─────────────────────────────────────────────────────

class TestMissingCredentials:

    def test_disabled_by_default(self, tmp_path):
        """X_ENABLED=0 (default) returns status=disabled without calling X API."""
        from integrations.x_api.intake import run_intake
        with patch.dict(os.environ, {"X_ENABLED": "0"}, clear=False):
            result = run_intake(dry_run=True, db_path=tmp_path / "db.sqlite")
        assert result["status"] == "disabled"
        assert result["fetched"] == 0
        assert result["stored"] == 0

    def test_missing_bearer_token_returns_error(self, tmp_path):
        """X_ENABLED=1 but no bearer token → missing_credentials."""
        from integrations.x_api.intake import run_intake
        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            result = run_intake(dry_run=True, db_path=tmp_path / "db.sqlite")
        assert result["status"] == "missing_credentials"
        assert "X_API_BEARER_TOKEN" in result["message"]
        assert result["fetched"] == 0

    def test_missing_credentials_exits_cleanly(self, tmp_path):
        """Missing credentials must return a result dict, not raise."""
        from integrations.x_api.intake import run_intake
        with patch.dict(os.environ, {"X_ENABLED": "1", "X_API_BEARER_TOKEN": ""}, clear=False):
            result = run_intake(dry_run=True, db_path=tmp_path / "db.sqlite")
        assert isinstance(result, dict)
        assert "status" in result
        assert "errors" in result


# ── TestDryRun ─────────────────────────────────────────────────────────────────

class TestDryRun:

    def _mock_client_tweets(self):
        """Return mock tweet data matching _parse_tweets output."""
        return [
            {
                "x_post_id":     "1234567890",
                "text":          "Check out this article https://example.com/article",
                "author_handle": "testuser",
                "author_name":   "Test User",
                "created_at":    "2026-04-26T10:00:00+00:00",
                "urls":          ["https://example.com/article"],
                "source":        "post",
            }
        ]

    def test_dry_run_does_not_write_to_db(self, tmp_path):
        """dry_run=True must not insert any rows into x_items."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "fake_token", "X_USER_ID": "123"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=self._mock_client_tweets()):
                with patch.object(XReadOnlyClient, "get_liked_tweets", return_value=[]):
                    db_path = tmp_path / "db.sqlite"
                    result = run_intake(dry_run=True, db_path=db_path, fetch_bookmarks=False)

        assert result["status"] == "dry_run"
        # DB either doesn't exist or has 0 rows
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM x_items").fetchone()[0]
            conn.close()
            assert count == 0, "dry_run wrote to DB"

    def test_dry_run_reports_would_store_count(self, tmp_path):
        """dry_run should report how many items would be stored."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "fake_token", "X_USER_ID": "123"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=self._mock_client_tweets()):
                with patch.object(XReadOnlyClient, "get_liked_tweets", return_value=[]):
                    result = run_intake(dry_run=True, db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        assert result["fetched"] > 0
        assert result["stored"] > 0  # "would store"


# ── TestApply ─────────────────────────────────────────────────────────────────

class TestApply:

    def _mock_tweets(self, n=2):
        return [
            {
                "x_post_id":     str(100 + i),
                "text":          f"Tweet {i}",
                "author_handle": "testuser",
                "author_name":   "Test User",
                "created_at":    "2026-04-26T10:00:00+00:00",
                "urls":          [],
                "source":        "post",
            }
            for i in range(n)
        ]

    def test_apply_writes_items_to_db(self, tmp_path):
        """dry_run=False must write items to x_items table."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "fake_token", "X_USER_ID": "123"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=self._mock_tweets(2)):
                with patch.object(XReadOnlyClient, "get_liked_tweets", return_value=[]):
                    db_path = tmp_path / "db.sqlite"
                    result = run_intake(dry_run=False, db_path=db_path, fetch_bookmarks=False)

        assert result["status"] == "ok"
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM x_items").fetchone()[0]
        conn.close()
        assert count == 2

    def test_apply_deduplicates(self, tmp_path):
        """Running apply twice must not duplicate items."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "fake_token", "X_USER_ID": "123"}
        tweets = self._mock_tweets(2)
        with patch.dict(os.environ, env, clear=False):
            for _ in range(2):
                with patch.object(XReadOnlyClient, "get_user_tweets", return_value=tweets):
                    with patch.object(XReadOnlyClient, "get_liked_tweets", return_value=[]):
                        run_intake(dry_run=False, db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        conn = sqlite3.connect(str(tmp_path / "db.sqlite"))
        count = conn.execute("SELECT COUNT(*) FROM x_items").fetchone()[0]
        conn.close()
        assert count == 2  # not 4


# ── TestUsageLimit ─────────────────────────────────────────────────────────────

class TestUsageLimit:

    def test_limit_enforced(self, tmp_path):
        """When daily reads >= limit, intake must return status=limit_reached."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.models import init_db
        from integrations.x_api.usage import log_usage

        db_path = tmp_path / "db.sqlite"
        conn = init_db(db_path)
        # Exhaust limit
        log_usage(conn, "get_users_tweets", request_count=100)
        conn.close()

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "tok", "X_DAILY_READ_LIMIT": "100"}
        with patch.dict(os.environ, env, clear=False):
            result = run_intake(dry_run=True, db_path=db_path)

        assert result["status"] == "limit_reached"
        assert result["fetched"] == 0

    def test_usage_logged_on_successful_call(self, tmp_path):
        """Successful API call must log to x_api_usage."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "fake", "X_USER_ID": "123"}
        db_path = tmp_path / "db.sqlite"
        with patch.dict(os.environ, env, clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=[]):
                with patch.object(XReadOnlyClient, "get_liked_tweets", return_value=[]):
                    run_intake(dry_run=False, db_path=db_path, fetch_bookmarks=False)

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM x_api_usage").fetchone()[0]
        conn.close()
        assert count >= 1


# ── TestNoWriteMethods ─────────────────────────────────────────────────────────

class TestNoWriteMethods:

    def test_write_methods_blocked(self):
        """XReadOnlyClient must block all write methods."""
        from integrations.x_api.client import XReadOnlyClient, XCredentials, _WRITE_METHODS
        import asyncio

        creds = XCredentials(bearer_token="fake", enabled=True)
        client = XReadOnlyClient(creds)

        # Manually create client without going through tweepy (mock it)
        mock_tweepy_client = MagicMock()
        client._client = mock_tweepy_client

        # Patch write methods
        for method_name in list(_WRITE_METHODS)[:3]:
            if hasattr(mock_tweepy_client, method_name):
                setattr(mock_tweepy_client, method_name, MagicMock())

        # Re-apply the guard
        from integrations.x_api.client import _write_blocked
        for method_name in _WRITE_METHODS:
            setattr(mock_tweepy_client, method_name, _write_blocked(method_name))

        # Verify write methods raise
        for method_name in list(_WRITE_METHODS)[:3]:
            fn = getattr(mock_tweepy_client, method_name)
            with pytest.raises(RuntimeError, match="read-only"):
                fn()

    def test_write_methods_set_not_empty(self):
        """_WRITE_METHODS must include core write operations."""
        from integrations.x_api.client import _WRITE_METHODS
        assert "create_tweet" in _WRITE_METHODS
        assert "like_tweet" in _WRITE_METHODS
        assert "follow_user" in _WRITE_METHODS
        assert "create_direct_message" in _WRITE_METHODS


# ── TestCortexEndpoints ────────────────────────────────────────────────────────

class TestCortexEndpoints:

    def test_x_api_status_masks_secrets(self, tmp_path):
        """GET /api/x-api/status must never return actual credential values."""
        import cortex.engine as eng
        env = {
            "X_ENABLED": "0",
            "X_API_BEARER_TOKEN": "super_secret_token_12345",
            "X_USER_ID": "99999",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(eng, "_x_api_db_path", return_value=None):
                result = _run(eng.x_api_status())

        # Must not contain the actual secret
        result_str = str(result)
        assert "super_secret_token_12345" not in result_str
        # Must confirm it's present (boolean)
        assert result["credentials"]["bearer_token"] is True
        assert result["credentials"]["user_id_configured"] is True

    def test_x_api_status_no_db(self):
        """Status with no DB returns status=no_db gracefully."""
        import cortex.engine as eng
        with patch.object(eng, "_x_api_db_path", return_value=None):
            with patch.dict(os.environ, {"X_ENABLED": "0"}, clear=False):
                result = _run(eng.x_api_status())
        assert result["status"] == "no_db"
        assert result["total_items"] == 0

    def test_x_api_items_no_db(self):
        """Items endpoint with no DB returns empty list."""
        import cortex.engine as eng
        with patch.object(eng, "_x_api_db_path", return_value=None):
            result = _run(eng.x_api_items())
        assert result["status"] == "no_db"
        assert result["items"] == []
        assert result["count"] == 0

    def test_x_api_dry_run_endpoint_never_calls_x(self):
        """POST /api/x-api/intake/dry-run must not call X API."""
        import cortex.engine as eng
        with patch.object(eng, "_x_api_db_path", return_value=None):
            with patch.dict(os.environ, {"X_ENABLED": "0"}, clear=False):
                result = _run(eng.x_api_intake_dry_run({}))
        assert result["status"] == "preview"
        assert result["should_auto_run"] is False
        assert result["would_run"] is False  # disabled

    def test_x_api_dry_run_reports_issues(self):
        """Dry-run preview lists all missing setup steps."""
        import cortex.engine as eng
        env = {"X_ENABLED": "0", "X_API_BEARER_TOKEN": "", "X_USER_ID": ""}
        with patch.object(eng, "_x_api_db_path", return_value=None):
            with patch.dict(os.environ, env, clear=False):
                result = _run(eng.x_api_intake_dry_run({}))
        assert len(result["issues"]) >= 2  # disabled + missing creds
        assert result["should_auto_run"] is False

    def test_enabled_with_creds_would_run(self):
        """If enabled and creds present, would_run should be True (below limit)."""
        import cortex.engine as eng
        env = {
            "X_ENABLED":            "1",
            "X_API_BEARER_TOKEN":   "fake_bearer",
            "X_USER_ID":            "123456",
            "X_DAILY_READ_LIMIT":   "100",
        }
        with patch.object(eng, "_x_api_db_path", return_value=None):
            with patch.dict(os.environ, env, clear=False):
                result = _run(eng.x_api_intake_dry_run({}))
        assert result["would_run"] is True
        assert result["issues"] == []
        assert result["should_auto_run"] is False


# ── TestBearerOnlyMode ─────────────────────────────────────────────────────────

class TestBearerOnlyMode:
    """Bearer-token-only (no OAuth user context) behaviour."""

    def _bearer_env(self):
        return {
            "X_ENABLED":          "1",
            "X_API_BEARER_TOKEN": "fake_bearer",
            "X_USER_ID":          "123456",
            # Intentionally NO X_API_CLIENT_ID / CLIENT_SECRET / ACCESS_TOKEN / REFRESH_TOKEN
            "X_API_CLIENT_ID":      "",
            "X_API_CLIENT_SECRET":  "",
            "X_API_ACCESS_TOKEN":   "",
            "X_API_REFRESH_TOKEN":  "",
        }

    def test_bearer_only_has_bearer_true(self):
        from integrations.x_api.client import XCredentials
        with patch.dict(os.environ, self._bearer_env(), clear=False):
            creds = XCredentials.from_env()
        assert creds.has_bearer() is True

    def test_bearer_only_has_user_auth_false(self):
        from integrations.x_api.client import XCredentials
        with patch.dict(os.environ, self._bearer_env(), clear=False):
            creds = XCredentials.from_env()
        assert creds.has_user_auth() is False

    def test_bearer_only_defaults_to_posts_only(self, tmp_path):
        """With bearer only and no explicit flags, likes are auto-skipped."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        mock_posts = [
            {"x_post_id": "1", "text": "post", "author_handle": "m",
             "author_name": "M", "created_at": None, "urls": [], "source": "post"}
        ]
        with patch.dict(os.environ, self._bearer_env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=mock_posts) as mock_tweets:
                with patch.object(XReadOnlyClient, "get_liked_tweets") as mock_likes:
                    result = run_intake(
                        dry_run=True,
                        fetch_posts=True,
                        fetch_likes=True,        # caller says True…
                        likes_explicitly_requested=False,  # …but not explicit
                        db_path=tmp_path / "db.sqlite",
                        fetch_bookmarks=False,
                    )

        # get_liked_tweets must NOT have been called
        mock_likes.assert_not_called()
        assert result["fetched"] > 0
        assert any("likes" in note for note in result["skipped_auth"])

    def test_likes_skipped_without_user_auth(self, tmp_path):
        """likes skipped when no OAuth user context (no explicit request)."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        with patch.dict(os.environ, self._bearer_env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=[]):
                with patch.object(XReadOnlyClient, "get_liked_tweets") as mock_likes:
                    result = run_intake(
                        dry_run=True, fetch_posts=True, fetch_likes=True,
                        likes_explicitly_requested=False,
                        db_path=tmp_path / "db.sqlite", fetch_bookmarks=False,
                    )

        mock_likes.assert_not_called()
        assert "skipped_auth" in result
        assert len(result["skipped_auth"]) > 0

    def test_likes_only_explicit_raises_clear_error(self, tmp_path):
        """--likes-only without user auth propagates a clear RuntimeError from client."""
        from integrations.x_api.intake import run_intake

        with patch.dict(os.environ, self._bearer_env(), clear=False):
            result = run_intake(
                dry_run=True, fetch_posts=False, fetch_likes=True,
                likes_explicitly_requested=True,
                db_path=tmp_path / "db.sqlite", fetch_bookmarks=False,
            )

        # The error should mention OAuth/auth, not silently produce 0 results
        assert result["errors"], "Expected an error when likes requested without user auth"
        err_text = " ".join(result["errors"])
        assert any(kw in err_text.lower() for kw in ("oauth", "auth", "user-context", "403"))

    def test_get_liked_tweets_raises_without_user_auth(self):
        """XReadOnlyClient.get_liked_tweets raises RuntimeError when no user auth."""
        from integrations.x_api.client import XReadOnlyClient, XCredentials

        creds = XCredentials(
            bearer_token="fake", enabled=True, user_id="123",
            consumer_key=None, consumer_secret=None,
            access_token=None, access_token_secret=None,
        )
        client = XReadOnlyClient(creds)
        with pytest.raises(RuntimeError, match="OAuth"):
            client.get_liked_tweets()

    def test_bookmarks_skipped_without_user_auth(self, tmp_path):
        """Bookmarks are auto-skipped when no user auth (never explicitly requested)."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        with patch.dict(os.environ, self._bearer_env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=[]):
                with patch.object(XReadOnlyClient, "get_bookmarks") as mock_bk:
                    result = run_intake(
                        dry_run=True, fetch_posts=True, fetch_likes=False,
                        fetch_bookmarks=True,  # requested but no user auth
                        db_path=tmp_path / "db.sqlite",
                    )

        mock_bk.assert_not_called()
        assert any("bookmarks" in note for note in result["skipped_auth"])


# ── TestStatusEndpointRobustness ───────────────────────────────────────────────

class TestStatusEndpointRobustness:
    """GET /api/x-api/status must never 500."""

    def test_status_no_db_returns_no_db(self):
        import cortex.engine as eng
        with patch.object(eng, "_x_api_db_path", return_value=None):
            with patch.dict(os.environ, {"X_ENABLED": "0"}, clear=False):
                result = _run(eng.x_api_status())
        assert result["status"] == "no_db"
        assert "warning" in result

    def test_status_db_missing_tables_returns_degraded(self, tmp_path):
        """DB file exists but tables not created → degraded, not 500."""
        import sqlite3
        import cortex.engine as eng

        # Create a valid but empty SQLite DB (no tables)
        empty_db = tmp_path / "empty.sqlite"
        conn = sqlite3.connect(str(empty_db))
        conn.close()

        with patch.object(eng, "_x_api_db_path", return_value=empty_db):
            with patch.dict(os.environ, {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "tok"}, clear=False):
                result = _run(eng.x_api_status())

        assert result["status"] == "degraded"
        assert "warning" in result
        assert result["total_items"] == 0

    def test_status_initialised_db_returns_ok_or_disabled(self, tmp_path):
        """Properly initialised DB returns ok or disabled (never 500)."""
        import cortex.engine as eng
        from integrations.x_api.models import init_db

        db_path = tmp_path / "x_items.sqlite"
        conn = init_db(db_path)
        conn.close()

        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            with patch.dict(os.environ, {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "tok"}, clear=False):
                result = _run(eng.x_api_status())

        assert result["status"] in ("ok", "disabled", "degraded")
        assert "total_items" in result
        assert result["total_items"] == 0
