"""
tools/x_auto_scheduler.py — Auto-posting scheduler for @symphonysmart
Runs every 2 hours via launchd. Checks queue, posts if conditions met,
and generates new content when queue is running low.
"""

import os
import sys
import datetime
import sqlite3
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

AI_SERVER_DIR = Path(__file__).parent.parent
DATA_DIR = AI_SERVER_DIR / "data" / "x_posts"
DB_PATH = DATA_DIR / "queue.db"
LOG_PATH = DATA_DIR / "scheduler.log"

MOUNTAIN_TZ = ZoneInfo("America/Denver")
LOW_QUEUE_THRESHOLD = 3


def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [x-scheduler] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH)),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_env():
    dotenv_path = AI_SERVER_DIR / ".env"
    if dotenv_path.exists():
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def now_mountain():
    return datetime.datetime.now(MOUNTAIN_TZ)


def within_posting_hours():
    now = now_mountain()
    return 7 <= now.hour < 22


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


def count_pending(conn):
    row = conn.execute(
        "SELECT COUNT(*) FROM post_queue WHERE status IN ('pending', 'approved')"
    ).fetchone()
    return row[0] if row else 0


def get_content_type_for_today():
    """Content calendar: return (content_type, category) based on day of week."""
    day = now_mountain().weekday()
    calendar = {
        0: ("tip", None),
        1: ("engagement", None),
        2: ("story", None),
        3: ("tip", "general"),
        4: ("local", None),
        5: ("tip", None),
        6: ("tip", None),
    }
    return calendar.get(day, ("tip", None))


def generate_content_for_day(content_type, category=None):
    """Call social_content.py to generate and queue content."""
    import subprocess

    script = AI_SERVER_DIR / "tools" / "social_content.py"

    flag_map = {
        "tip": "--tip",
        "story": "--story",
        "engagement": "--tip",
        "local": "--tip",
        "video": "--video-prompt",
    }

    flag = flag_map.get(content_type, "--tip")
    cmd = [sys.executable, str(script), flag, "--queue"]
    if category:
        cmd += ["--category", category]

    logging.info(f"Generating content: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(AI_SERVER_DIR))
    if result.returncode == 0:
        logging.info(f"Content generated: {result.stdout.strip()[:120]}")
    else:
        logging.warning(f"Content generation failed: {result.stderr.strip()[:200]}")


def run_auto_post():
    """Invoke x_poster.py --auto to post the next item."""
    import subprocess

    script = AI_SERVER_DIR / "tools" / "x_poster.py"
    cmd = [sys.executable, str(script), "--auto"]

    logging.info("Running auto-post...")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(AI_SERVER_DIR))
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        logging.info(f"Auto-post result: {output[:200]}")
    else:
        logging.warning(f"Auto-post error: {output[:200]}")


def main():
    setup_logging()
    load_env()

    now = now_mountain()
    logging.info(f"Scheduler run at {now.strftime('%Y-%m-%d %H:%M MDT')}")

    if not within_posting_hours():
        logging.info("Outside posting hours (7am-10pm MT). Skipping.")
        return

    if not os.environ.get("X_API_KEY"):
        logging.warning("X_API_KEY not set. Skipping post step. Will still generate content.")
        post_enabled = False
    else:
        post_enabled = True

    conn = get_db()
    pending = count_pending(conn)
    logging.info(f"Pending posts in queue: {pending}")

    if pending < LOW_QUEUE_THRESHOLD:
        logging.info(f"Queue low ({pending} < {LOW_QUEUE_THRESHOLD}). Generating new content.")
        content_type, category = get_content_type_for_today()
        generate_content_for_day(content_type, category)
        pending = count_pending(conn)
        logging.info(f"Queue after generation: {pending}")

    conn.close()

    if post_enabled and pending > 0:
        run_auto_post()
    elif not post_enabled:
        logging.info("Posting disabled (no X credentials). Content queued for when credentials are set.")
    else:
        logging.info("No posts to send.")

    logging.info("Scheduler run complete.")


if __name__ == "__main__":
    main()
