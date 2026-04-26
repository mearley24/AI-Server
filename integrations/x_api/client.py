"""X API v2 read-only client.

Uses tweepy.Client for all requests. Supports:
  - Bearer token (app-only) → user timeline, liked tweets
  - OAuth 1.0a user context → bookmarks (requires Basic plan+)

NEVER posts, replies, follows, DMs, or writes to X.
All methods are read-only and raise immediately on any write attempt.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Guard: prevent accidental write operations at import time.
_WRITE_METHODS = frozenset({
    "create_tweet", "delete_tweet", "like_tweet", "unlike_tweet",
    "retweet", "unretweet", "follow_user", "unfollow_user",
    "create_direct_message", "create_list", "delete_list",
    "add_list_member", "remove_list_member", "mute_user", "unmute_user",
    "block_user", "unblock_user", "bookmark_tweet", "remove_bookmark",
})


@dataclass
class XCredentials:
    bearer_token: Optional[str] = None
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = None
    access_token: Optional[str] = None
    access_token_secret: Optional[str] = None
    user_id: Optional[str] = None
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "XCredentials":
        return cls(
            bearer_token=       os.environ.get("X_API_BEARER_TOKEN") or None,
            consumer_key=       os.environ.get("X_API_CLIENT_ID") or None,
            consumer_secret=    os.environ.get("X_API_CLIENT_SECRET") or None,
            access_token=       os.environ.get("X_API_ACCESS_TOKEN") or None,
            access_token_secret=os.environ.get("X_API_REFRESH_TOKEN") or None,
            user_id=            os.environ.get("X_USER_ID") or None,
            enabled=            os.environ.get("X_ENABLED", "0").strip() == "1",
        )

    def has_bearer(self) -> bool:
        return bool(self.bearer_token)

    def has_user_auth(self) -> bool:
        return bool(self.consumer_key and self.consumer_secret
                    and self.access_token and self.access_token_secret)

    def credentials_present(self) -> dict[str, bool]:
        return {
            "bearer_token":        self.has_bearer(),
            "user_auth":           self.has_user_auth(),
            "user_id_configured":  bool(self.user_id),
            "enabled":             self.enabled,
        }


class XReadOnlyClient:
    """Thin wrapper around tweepy.Client — read-only operations only."""

    def __init__(self, creds: XCredentials):
        self._creds = creds
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import tweepy
        except ImportError as exc:
            raise RuntimeError("tweepy is required: pip install tweepy>=4.0") from exc

        if not self._creds.enabled:
            raise RuntimeError("X API disabled (X_ENABLED=0). Set X_ENABLED=1 to enable.")
        if not self._creds.has_bearer():
            raise RuntimeError(
                "X_API_BEARER_TOKEN not set. Add it to .env.\n"
                "Get a Bearer Token at: https://developer.x.com/en/portal/dashboard"
            )

        kwargs: dict = {"bearer_token": self._creds.bearer_token, "wait_on_rate_limit": False}
        if self._creds.has_user_auth():
            kwargs.update({
                "consumer_key":        self._creds.consumer_key,
                "consumer_secret":     self._creds.consumer_secret,
                "access_token":        self._creds.access_token,
                "access_token_secret": self._creds.access_token_secret,
            })

        client = tweepy.Client(**kwargs)

        # Safety guard — monkey-patch write methods to raise immediately.
        for method_name in _WRITE_METHODS:
            if hasattr(client, method_name):
                setattr(client, method_name, _write_blocked(method_name))

        self._client = client
        return client

    def get_user_tweets(self, max_results: int = 10) -> list[dict]:
        """Fetch Matt's own recent posts. Requires bearer token + X_USER_ID."""
        if not self._creds.user_id:
            raise RuntimeError("X_USER_ID not set.")
        client = self._get_client()
        resp = client.get_users_tweets(
            id=self._creds.user_id,
            max_results=min(max_results, 100),
            tweet_fields=["created_at", "entities", "author_id", "text"],
            expansions=["author_id"],
            user_fields=["username", "name"],
        )
        return _parse_tweets(resp, source="post")

    def get_liked_tweets(self, max_results: int = 10) -> list[dict]:
        """Fetch tweets Matt liked. Requires bearer token + X_USER_ID."""
        if not self._creds.user_id:
            raise RuntimeError("X_USER_ID not set.")
        client = self._get_client()
        resp = client.get_liked_tweets(
            id=self._creds.user_id,
            max_results=min(max_results, 100),
            tweet_fields=["created_at", "entities", "author_id", "text"],
            expansions=["author_id"],
            user_fields=["username", "name"],
        )
        return _parse_tweets(resp, source="like")

    def get_bookmarks(self, max_results: int = 10) -> list[dict]:
        """Fetch Matt's bookmarks. Requires OAuth 1.0a user auth + Basic plan."""
        if not self._creds.has_user_auth():
            raise RuntimeError(
                "Bookmarks require OAuth 1.0a user auth (X_API_CLIENT_ID, "
                "X_API_CLIENT_SECRET, X_API_ACCESS_TOKEN, X_API_REFRESH_TOKEN) "
                "and an X Basic plan ($100/mo)."
            )
        if not self._creds.user_id:
            raise RuntimeError("X_USER_ID not set.")
        client = self._get_client()
        resp = client.get_bookmarks(
            id=self._creds.user_id,
            max_results=min(max_results, 100),
            tweet_fields=["created_at", "entities", "author_id", "text"],
            expansions=["author_id"],
            user_fields=["username", "name"],
        )
        return _parse_tweets(resp, source="bookmark")


def _write_blocked(method_name: str):
    def _blocked(*_a, **_kw):
        raise RuntimeError(
            f"XReadOnlyClient: write method '{method_name}' is disabled. "
            "This client is read-only."
        )
    return _blocked


def _parse_tweets(resp, source: str) -> list[dict]:
    """Normalise a tweepy Response into a list of dicts."""
    if resp is None or resp.data is None:
        return []

    user_map: dict[str, dict] = {}
    if resp.includes and "users" in resp.includes:
        for u in resp.includes["users"]:
            user_map[str(u.id)] = {"handle": u.username, "name": u.name}

    results = []
    for tweet in resp.data:
        author_id = str(getattr(tweet, "author_id", "") or "")
        author = user_map.get(author_id, {})
        urls = []
        if tweet.entities and "urls" in tweet.entities:
            urls = [u.get("expanded_url") or u.get("url") for u in tweet.entities["urls"] if u.get("expanded_url") or u.get("url")]
        results.append({
            "x_post_id":     str(tweet.id),
            "text":          tweet.text or "",
            "author_handle": author.get("handle"),
            "author_name":   author.get("name"),
            "created_at":    str(tweet.created_at) if tweet.created_at else None,
            "urls":          [u for u in urls if u],
            "source":        source,
        })
    return results
