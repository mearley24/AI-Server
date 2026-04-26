"""X API intake — fetch, dedupe, store, and route to learning pipeline.

Orchestrates calls to XReadOnlyClient, checks usage limits, dedupes by
x_item_id, stores in SQLite, and optionally routes URL items to the
self-improvement inbox for learning card generation.

Never writes to X. All operations are local reads + local DB writes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from integrations.x_api.client import XCredentials, XReadOnlyClient
from integrations.x_api.models import XItem, init_db, insert_item
from integrations.x_api.usage import check_limit, log_usage, usage_summary

logger = logging.getLogger(__name__)

# Self-improvement inbox for routing interesting URLs
_SI_INBOX = Path(__file__).resolve().parent.parent.parent / "ops" / "self_improvement" / "inbox"


def _make_x_item_id(source: str, x_post_id: str) -> str:
    return f"{source}:{x_post_id}"


def _extract_url_items(tweet: dict, source: str) -> list[XItem]:
    """Return XItem records for each meaningful URL in a tweet."""
    items = []
    for url in tweet.get("urls", []):
        if not url:
            continue
        # Skip t.co links and twitter/x.com self-refs
        if "t.co/" in url or "twitter.com/i/" in url or "x.com/i/" in url:
            continue
        item_id = f"url:{tweet['x_post_id']}:{hash(url) & 0xFFFFFF:06x}"
        items.append(XItem(
            x_item_id=     item_id,
            item_type=     "url",
            x_post_id=     tweet["x_post_id"],
            author_handle= tweet.get("author_handle"),
            author_name=   tweet.get("author_name"),
            text=          tweet.get("text"),
            url=           url,
            created_at=    tweet.get("created_at"),
            source=        source,
        ))
    return items


def run_intake(
    limit: int = 25,
    dry_run: bool = True,
    fetch_posts: bool = True,
    fetch_likes: bool = True,
    fetch_bookmarks: bool = False,
    likes_explicitly_requested: bool = False,
    db_path: Optional[Path] = None,
) -> dict:
    """Main intake entry point.

    Returns a result dict with counts and any errors.
    If dry_run=True, nothing is written to the DB.
    """
    creds = XCredentials.from_env()

    if not creds.enabled:
        return {
            "status":  "disabled",
            "message": "X API disabled (X_ENABLED=0). Set X_ENABLED=1 to enable.",
            "fetched": 0, "stored": 0, "skipped": 0, "errors": [],
        }

    if not creds.has_bearer():
        return {
            "status":  "missing_credentials",
            "message": (
                "X_API_BEARER_TOKEN not configured.\n"
                "Steps:\n"
                "  1. Go to https://developer.x.com/en/portal/dashboard\n"
                "  2. Create a Project + App (Free tier is enough for posts/likes)\n"
                "  3. Copy the Bearer Token\n"
                "  4. Add X_API_BEARER_TOKEN=<token> to your .env\n"
                "  5. Add X_USER_ID=<your_numeric_user_id> to your .env\n"
                "  6. Set X_ENABLED=1"
            ),
            "fetched": 0, "stored": 0, "skipped": 0, "errors": [],
        }

    conn = init_db(db_path)
    within_limit, used, lim = check_limit(conn)
    if not within_limit:
        return {
            "status":  "limit_reached",
            "message": f"Daily read limit reached ({used}/{lim}). Resets at midnight UTC.",
            "fetched": 0, "stored": 0, "skipped": 0, "errors": [],
        }

    # Likes and bookmarks require OAuth user-context auth.
    # Auto-skip unless explicitly requested; if explicitly requested without
    # user auth, let the call proceed so the client raises a clear error.
    skipped_auth: list[str] = []
    if fetch_likes and not creds.has_user_auth():
        if likes_explicitly_requested:
            pass  # proceed — client will raise a descriptive RuntimeError
        else:
            fetch_likes = False
            skipped_auth.append(
                "likes: skipped (OAuth user-context not configured; "
                "use --likes-only to attempt anyway)"
            )
    if fetch_bookmarks and not creds.has_user_auth():
        fetch_bookmarks = False
        skipped_auth.append(
            "bookmarks: skipped (OAuth user-context not configured)"
        )

    client = XReadOnlyClient(creds)
    all_tweets: list[dict] = []
    errors: list[str] = []

    if fetch_posts:
        try:
            tweets = client.get_user_tweets(max_results=limit)
            log_usage(conn, "get_users_tweets", item_count=len(tweets))
            all_tweets.extend(tweets)
        except Exception as exc:
            errors.append(f"posts: {exc}")
            log_usage(conn, "get_users_tweets", status=f"error:{exc}")

    if fetch_likes:
        try:
            tweets = client.get_liked_tweets(max_results=limit)
            log_usage(conn, "get_liked_tweets", item_count=len(tweets))
            all_tweets.extend(tweets)
        except Exception as exc:
            errors.append(f"likes: {exc}")
            log_usage(conn, "get_liked_tweets", status=f"error:{exc}")

    if fetch_bookmarks:
        try:
            tweets = client.get_bookmarks(max_results=limit)
            log_usage(conn, "get_bookmarks", item_count=len(tweets))
            all_tweets.extend(tweets)
        except Exception as exc:
            errors.append(f"bookmarks: {exc}")
            log_usage(conn, "get_bookmarks", status=f"error:{exc}")

    fetched = len(all_tweets)
    stored = 0
    skipped = 0

    for tweet in all_tweets:
        source = tweet["source"]
        # Main tweet item
        main_item = XItem(
            x_item_id=     _make_x_item_id(source, tweet["x_post_id"]),
            item_type=     source,
            x_post_id=     tweet["x_post_id"],
            author_handle= tweet.get("author_handle"),
            author_name=   tweet.get("author_name"),
            text=          tweet.get("text"),
            created_at=    tweet.get("created_at"),
            source=        source,
        )
        if not dry_run:
            if insert_item(conn, main_item):
                stored += 1
            else:
                skipped += 1
        else:
            stored += 1  # count as "would store"

        # URL items
        for url_item in _extract_url_items(tweet, source):
            if not dry_run:
                if insert_item(conn, url_item):
                    stored += 1
                    _maybe_route_to_learning(url_item)
                else:
                    skipped += 1
            else:
                stored += 1

    conn.close()

    return {
        "status":       "dry_run" if dry_run else "ok",
        "fetched":      fetched,
        "stored":       stored,
        "skipped":      skipped,
        "errors":       errors,
        "skipped_auth": skipped_auth,
        "dry_run":      dry_run,
    }


def _maybe_route_to_learning(item: XItem) -> None:
    """Write a minimal learning card stub to the self-improvement inbox.

    Only routes items with external URLs. Does not modify X data.
    """
    if not item.url or not _SI_INBOX.is_dir():
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    card_name = f"{ts}-x-api-url-{item.x_item_id[-8:]}.md"
    card_path = _SI_INBOX / card_name
    if card_path.exists():
        return
    body = (
        f"# X API Learning Card\n\n"
        f"**Source:** {item.source} · @{item.author_handle or 'unknown'}\n"
        f"**URL:** {item.url}\n"
        f"**Tweet text:** {(item.text or '')[:280]}\n\n"
        f"*Auto-generated by x_api_intake. Review and categorise.*\n"
    )
    try:
        card_path.write_text(body, encoding="utf-8")
    except OSError:
        pass
