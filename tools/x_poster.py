"""
tools/x_poster.py — X/Twitter poster for @symphonysmart
Posts queued content with safety rails (rate limits, time windows, content checks).
Uses tweepy OAuth 1.0a.
"""

import os
import sys
import re
import json
import sqlite3
import argparse
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AI_SERVER_DIR = Path(__file__).parent.parent
DATA_DIR = AI_SERVER_DIR / "data" / "x_posts"
DB_PATH = DATA_DIR / "queue.db"
POST_LOG = DATA_DIR / "post_log.json"

MOUNTAIN_TZ = ZoneInfo("America/Denver")

BLOCKED_PATTERNS = [
    re.compile(r"\$\d"),
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(St|Ave|Rd|Blvd|Dr|Ln|Way|Ct|Pl|Circle)\b"),
]

POST_TYPE_EMOJI = {
    "tip": "💡",
    "story": "📖",
    "video": "🎬",
    "engagement": "💬",
    "series": "📅",
    "local": "🏔️",
}


def load_env():
    dotenv_path = AI_SERVER_DIR / ".env"
    if dotenv_path.exists():
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def check_credentials():
    if not os.environ.get("X_API_KEY"):
        print("ERROR: X_API_KEY not set in .env. See .env.example section 12.")
        sys.exit(1)
    required = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing X credentials in .env: {', '.join(missing)}")
        sys.exit(1)


def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS post_queue (
            id INTEGER PRIMARY KEY,
            content TEXT,
            post_type TEXT,
            category TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            scheduled_for TEXT,
            posted_at TEXT,
            x_post_id TEXT,
            media_paths TEXT
        )
    """)
    conn.commit()
    return conn


def get_tweepy_client():
    import tweepy
    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return client


def load_post_log():
    if POST_LOG.exists():
        with open(POST_LOG) as f:
            return json.load(f)
    return []


def save_post_log(log):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG, "w") as f:
        json.dump(log, f, indent=2)


def now_mountain():
    return datetime.datetime.now(MOUNTAIN_TZ)


def time_ago(iso_str):
    """Return a human-readable time delta string."""
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        diff = datetime.datetime.now(datetime.timezone.utc) - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        elif secs < 3600:
            return f"{secs // 60}m ago"
        elif secs < 86400:
            return f"{secs // 3600}h ago"
        else:
            return f"{secs // 86400}d ago"
    except Exception:
        return "unknown"


def posts_today(log):
    """Count posts made today in Mountain Time."""
    today = now_mountain().date()
    count = 0
    for entry in log:
        try:
            ts = datetime.datetime.fromisoformat(entry["posted_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            ts_mtn = ts.astimezone(MOUNTAIN_TZ)
            if ts_mtn.date() == today:
                count += 1
        except Exception:
            pass
    return count


def last_post_time(log):
    """Return the datetime of the most recent post, or None."""
    timestamps = []
    for entry in log:
        try:
            ts = datetime.datetime.fromisoformat(entry["posted_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            timestamps.append(ts)
        except Exception:
            pass
    if timestamps:
        return max(timestamps)
    return None


def is_rate_limited(log):
    """Check if we're rate-limited (24h block after API error)."""
    if POST_LOG.parent.exists():
        rate_limit_file = DATA_DIR / "rate_limit_until.txt"
        if rate_limit_file.exists():
            with open(rate_limit_file) as f:
                until_str = f.read().strip()
            try:
                until = datetime.datetime.fromisoformat(until_str)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=datetime.timezone.utc)
                if datetime.datetime.now(datetime.timezone.utc) < until:
                    return True, until
            except Exception:
                pass
    return False, None


def set_rate_limit():
    """Block posting for 24 hours after a rate limit error."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
    rate_limit_file = DATA_DIR / "rate_limit_until.txt"
    with open(rate_limit_file, "w") as f:
        f.write(until.isoformat())


def content_is_safe(text):
    """Check post content against blocked patterns."""
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(text):
            return False, f"Blocked pattern matched: {pattern.pattern}"
    return True, None


def within_posting_hours():
    """Returns True if current Mountain Time is between 7am and 10pm."""
    now = now_mountain()
    return 7 <= now.hour < 22


def can_post(log):
    """
    Returns (ok: bool, reason: str).
    Safety rails: max 1/4hrs, max 3/day, no 10pm-7am MT.
    """
    max_posts_day = int(os.environ.get("X_MAX_POSTS_DAY", "3"))
    interval_hours = float(os.environ.get("X_POST_INTERVAL_HOURS", "4"))

    if not within_posting_hours():
        return False, "Outside posting hours (7am-10pm MT)"

    today_count = posts_today(log)
    if today_count >= max_posts_day:
        return False, f"Daily limit reached ({today_count}/{max_posts_day})"

    last = last_post_time(log)
    if last:
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds() / 3600
        if elapsed < interval_hours:
            next_ok = last + datetime.timedelta(hours=interval_hours)
            next_ok_mtn = next_ok.astimezone(MOUNTAIN_TZ)
            return False, f"Too soon — next allowed at {next_ok_mtn.strftime('%H:%M MDT')}"

    rate_limited, until = is_rate_limited(log)
    if rate_limited:
        until_mtn = until.astimezone(MOUNTAIN_TZ)
        return False, f"Rate limited until {until_mtn.strftime('%Y-%m-%d %H:%M MDT')}"

    return True, None


def cmd_queue():
    """Show pending posts in the queue."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, content, post_type, created_at FROM post_queue WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    conn.close()

    log = load_post_log()
    today_count = posts_today(log)
    max_day = int(os.environ.get("X_MAX_POSTS_DAY", "3"))
    last = last_post_time(log)

    print(f"Pending Posts ({len(rows)}):")
    for row in rows:
        rid, content, post_type, created_at = row
        emoji = POST_TYPE_EMOJI.get(post_type, "📝")
        preview = content[:60] + "..." if len(content) > 60 else content
        ago = time_ago(created_at)
        print(f"  [{rid}] {emoji} {post_type.title()}: \"{preview}\" (created {ago})")

    print(f"\nPosted Today: {today_count}/{max_day}")
    if last:
        last_mtn = last.astimezone(MOUNTAIN_TZ)
        print(f"Last Post: {last_mtn.strftime('%Y-%m-%d %H:%M MDT')}")

        interval_hours = float(os.environ.get("X_POST_INTERVAL_HOURS", "4"))
        next_allowed = last + datetime.timedelta(hours=interval_hours)
        next_mtn = next_allowed.astimezone(MOUNTAIN_TZ)
        print(f"Next Allowed: {next_mtn.strftime('%Y-%m-%d %H:%M MDT')}")
    else:
        print("Last Post: Never")


def cmd_usage():
    """Show X API usage stats."""
    log = load_post_log()
    now = now_mountain()
    today = now.date()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    today_count = 0
    week_count = 0
    month_count = 0
    last = None

    for entry in log:
        try:
            ts = datetime.datetime.fromisoformat(entry["posted_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            ts_mtn = ts.astimezone(MOUNTAIN_TZ)
            d = ts_mtn.date()
            if d == today:
                today_count += 1
            if d >= week_start:
                week_count += 1
            if d >= month_start:
                month_count += 1
            if last is None or ts > last:
                last = ts
        except Exception:
            pass

    max_day = int(os.environ.get("X_MAX_POSTS_DAY", "3"))
    interval_hours = float(os.environ.get("X_POST_INTERVAL_HOURS", "4"))

    print("X API Usage (@symphonysmart):")
    print(f"  Posts today: {today_count}/{max_day}")
    print(f"  Posts this week: {week_count}/21")
    print(f"  Posts this month: {month_count}/500")

    if last:
        last_mtn = last.astimezone(MOUNTAIN_TZ)
        print(f"  Last post: {last_mtn.strftime('%Y-%m-%d %H:%M MDT')}")
        next_allowed = last + datetime.timedelta(hours=interval_hours)
        next_mtn = next_allowed.astimezone(MOUNTAIN_TZ)
        print(f"  Next allowed: {next_mtn.strftime('%Y-%m-%d %H:%M MDT')}")
    else:
        print("  Last post: Never")
        print("  Next allowed: Now")


def do_post(row, conn, log):
    """
    Actually post to X and update DB + log.
    row = (id, content, post_type, category)
    """
    rid, content, post_type, category = row

    safe, reason = content_is_safe(content)
    if not safe:
        print(f"BLOCKED: Post {rid} failed content check — {reason}")
        conn.execute("UPDATE post_queue SET status='skipped' WHERE id=?", (rid,))
        conn.commit()
        return False

    ok, reason = can_post(log)
    if not ok:
        print(f"Cannot post: {reason}")
        return False

    try:
        client = get_tweepy_client()
        response = client.create_tweet(text=content)
        tweet_id = str(response.data["id"])

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            "UPDATE post_queue SET status='posted', posted_at=?, x_post_id=? WHERE id=?",
            (now_iso, tweet_id, rid),
        )
        conn.commit()

        log_entry = {
            "queue_id": rid,
            "content": content,
            "post_type": post_type,
            "posted_at": now_iso,
            "x_post_id": tweet_id,
        }
        log.append(log_entry)
        save_post_log(log)

        now_mtn = datetime.datetime.now(MOUNTAIN_TZ)
        print(f"Posted: {content[:80]}...")
        print(f"Tweet ID: {tweet_id}")
        print(f"Time: {now_mtn.strftime('%Y-%m-%d %H:%M MDT')}")
        return True

    except Exception as e:
        err_str = str(e).lower()
        if "rate limit" in err_str or "429" in err_str:
            print(f"Rate limit hit — blocking posts for 24 hours. ({e})")
            set_rate_limit()
        else:
            print(f"Error posting to X: {e}")
        return False


def cmd_auto():
    """Post the next approved/pending item in the queue."""
    log = load_post_log()
    ok, reason = can_post(log)
    if not ok:
        print(f"Auto-post skipped: {reason}")
        return

    conn = get_db()
    row = conn.execute(
        "SELECT id, content, post_type, category FROM post_queue "
        "WHERE status IN ('approved', 'pending') ORDER BY created_at LIMIT 1"
    ).fetchone()

    if not row:
        print("No pending posts in queue. Run social_content.py to generate content.")
        conn.close()
        return

    do_post(row, conn, log)
    conn.close()


def cmd_post_id(post_id):
    """Post a specific queue item by ID."""
    log = load_post_log()

    conn = get_db()
    row = conn.execute(
        "SELECT id, content, post_type, category FROM post_queue WHERE id=?",
        (post_id,)
    ).fetchone()

    if not row:
        print(f"No post found with ID {post_id}")
        conn.close()
        return

    ok, reason = can_post(log)
    if not ok:
        print(f"Cannot post: {reason}")
        conn.close()
        return

    do_post(row, conn, log)
    conn.close()


def main():
    load_env()
    check_credentials()

    parser = argparse.ArgumentParser(description="X/Twitter poster for @symphonysmart")
    parser.add_argument("--queue", action="store_true", help="Show pending posts")
    parser.add_argument("--auto", action="store_true", help="Post next pending/approved item")
    parser.add_argument("--usage", action="store_true", help="Show API usage stats")
    parser.add_argument("--post-id", type=int, metavar="N", help="Post a specific queue item by ID")
    args = parser.parse_args()

    if args.queue:
        cmd_queue()
    elif args.auto:
        cmd_auto()
    elif args.usage:
        cmd_usage()
    elif args.post_id is not None:
        cmd_post_id(args.post_id)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
