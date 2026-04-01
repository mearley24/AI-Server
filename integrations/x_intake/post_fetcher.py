"""
post_fetcher.py
---------------
Fetches post content from X/Twitter URLs.

Strategy (in order):
  1. Nitter public instances (no API key, no JS rendering needed)
  2. Direct x.com/twitter.com with parse fallback
  3. vxtwitter.com / fxtwitter.com embed APIs

Returns a structured PostData object.
"""

import re
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public Nitter instances — rotated in order; skip if one fails.
# These are community-hosted and availability varies; keep the list updated.
# ---------------------------------------------------------------------------
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.net",
    "https://nitter.cz",
    "https://nitter.unixfox.eu",
    "https://nitter.nl",
    "https://nitter.it",
    "https://tweet.lambda.dance",
]

# fxtwitter / vxtwitter provide clean embed JSON without auth
FXTWITTER_API = "https://api.fxtwitter.com/{author}/status/{post_id}"
VXTWITTER_API = "https://api.vxtwitter.com/{author}/status/{post_id}"

# Regex patterns for extracting tweet IDs from URLs
TWEET_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)",
    re.IGNORECASE,
)

REQUEST_TIMEOUT = 10  # seconds
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BobBot/1.0; +https://github.com/bob)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PostData:
    """Structured representation of a fetched X/Twitter post."""
    post_id: str
    author: str
    text: str
    timestamp: Optional[str] = None
    media_urls: list = field(default_factory=list)
    reply_count: Optional[int] = None
    retweet_count: Optional[int] = None
    like_count: Optional[int] = None
    view_count: Optional[int] = None
    quote_count: Optional[int] = None
    url: str = ""
    is_reply: bool = False
    replied_to_author: Optional[str] = None
    replied_to_post_id: Optional[str] = None
    thread_context: Optional["PostData"] = None
    fetch_method: str = "unknown"
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "post_id": self.post_id,
            "author": self.author,
            "text": self.text,
            "timestamp": self.timestamp,
            "media_urls": self.media_urls,
            "reply_count": self.reply_count,
            "retweet_count": self.retweet_count,
            "like_count": self.like_count,
            "view_count": self.view_count,
            "quote_count": self.quote_count,
            "url": self.url,
            "is_reply": self.is_reply,
            "replied_to_author": self.replied_to_author,
            "replied_to_post_id": self.replied_to_post_id,
            "thread_context": self.thread_context.to_dict() if self.thread_context else None,
            "fetch_method": self.fetch_method,
        }
        return d

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"@{self.author} [{self.post_id}]: "
            f"{self.text[:80]}{'...' if len(self.text) > 80 else ''}"
        )


class FetchError(Exception):
    """Raised when a post cannot be fetched by any method."""
    pass


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def extract_post_id(url: str) -> tuple[str, str]:
    """
    Parse a Twitter/X URL and return (author, post_id).
    Raises ValueError if the URL doesn't match.
    """
    m = TWEET_URL_PATTERN.search(url)
    if not m:
        raise ValueError(f"Not a recognised X/Twitter URL: {url}")
    author = m.group(1)
    post_id = m.group(2)
    return author, post_id


def _http_get(url: str, timeout: int = REQUEST_TIMEOUT, headers: dict = None) -> str:
    """Perform a simple HTTP GET and return the response body as text."""
    req_headers = dict(DEFAULT_HEADERS)
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _http_get_json(url: str, timeout: int = REQUEST_TIMEOUT) -> dict:
    """Perform HTTP GET and parse JSON response."""
    headers = {"Accept": "application/json"}
    body = _http_get(url, timeout=timeout, headers=headers)
    return json.loads(body)


# ---------------------------------------------------------------------------
# Fetch strategies
# ---------------------------------------------------------------------------

def _fetch_via_fxtwitter(author: str, post_id: str) -> PostData:
    """
    Use fxtwitter.com's undocumented but stable embed API.
    Returns rich JSON including media, stats, and reply chain.
    """
    api_url = FXTWITTER_API.format(author=author, post_id=post_id)
    data = _http_get_json(api_url)

    tweet = data.get("tweet") or data.get("data")
    if not tweet:
        raise FetchError("fxtwitter returned no tweet data")

    media_urls = []
    media = tweet.get("media") or {}
    for photo in media.get("photos", []):
        if photo.get("url"):
            media_urls.append(photo["url"])
    for video in media.get("videos", []):
        if video.get("url"):
            media_urls.append(video["url"])
        elif video.get("thumbnail_url"):
            media_urls.append(video["thumbnail_url"])

    author_obj = tweet.get("author", {})
    author_handle = author_obj.get("screen_name") or author

    reply_info = tweet.get("reply", {})
    is_reply = bool(reply_info)
    replied_to_author = reply_info.get("screen_name") if reply_info else None
    replied_to_id = str(reply_info.get("post_id", "")) if reply_info else None

    post = PostData(
        post_id=str(tweet.get("id", post_id)),
        author=author_handle,
        text=tweet.get("text", ""),
        timestamp=tweet.get("created_at") or tweet.get("date"),
        media_urls=media_urls,
        reply_count=tweet.get("replies"),
        retweet_count=tweet.get("retweets"),
        like_count=tweet.get("likes"),
        view_count=tweet.get("views"),
        quote_count=tweet.get("quotes"),
        url=tweet.get("url", f"https://x.com/{author}/status/{post_id}"),
        is_reply=is_reply,
        replied_to_author=replied_to_author,
        replied_to_post_id=replied_to_id,
        fetch_method="fxtwitter",
        raw=tweet,
    )
    return post


def _fetch_via_vxtwitter(author: str, post_id: str) -> PostData:
    """
    Fallback to vxtwitter.com API (similar structure to fxtwitter).
    """
    api_url = VXTWITTER_API.format(author=author, post_id=post_id)
    data = _http_get_json(api_url)

    tweet = data.get("tweet") or data.get("data")
    if not tweet:
        raise FetchError("vxtwitter returned no tweet data")

    media_urls = []
    for m in tweet.get("mediaURLs", []):
        if m:
            media_urls.append(m)

    post = PostData(
        post_id=str(tweet.get("tweetID", post_id)),
        author=tweet.get("user_screen_name", author),
        text=tweet.get("text", ""),
        timestamp=tweet.get("date"),
        media_urls=media_urls,
        reply_count=tweet.get("replies"),
        retweet_count=tweet.get("retweets"),
        like_count=tweet.get("likes"),
        url=tweet.get("tweetURL", f"https://x.com/{author}/status/{post_id}"),
        fetch_method="vxtwitter",
        raw=tweet,
    )
    return post


def _fetch_via_nitter(author: str, post_id: str) -> PostData:
    """
    Try each Nitter instance in turn and parse the HTML response.
    Nitter renders tweet content server-side with no JS requirement.
    """
    last_error = None
    for base in NITTER_INSTANCES:
        url = f"{base}/{author}/status/{post_id}"
        try:
            html = _http_get(url, timeout=REQUEST_TIMEOUT)
        except (URLError, HTTPError, OSError) as e:
            logger.debug(f"Nitter instance {base} failed: {e}")
            last_error = e
            continue

        # Check for not-found / unavailable signals
        if "Tweet not found" in html or "User not found" in html:
            raise FetchError("Post or user not found (Nitter)")

        if "instance is currently unavailable" in html.lower():
            logger.debug(f"Nitter {base} unavailable, trying next")
            continue

        post = _parse_nitter_html(html, author, post_id, base)
        if post:
            return post

        logger.debug(f"Nitter {base} returned unparseable HTML, trying next")

    raise FetchError(
        f"All Nitter instances failed. Last error: {last_error}"
    )


def _parse_nitter_html(html: str, author: str, post_id: str, base_url: str) -> Optional[PostData]:
    """
    Minimal HTML parser for Nitter tweet pages.
    Avoids BeautifulSoup dependency — uses targeted regex patterns.
    """
    # Extract main tweet text
    text_match = re.search(
        r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not text_match:
        return None

    raw_text = text_match.group(1)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", raw_text).strip()
    # Decode common HTML entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return None

    # Stats
    def _stat(label: str) -> Optional[int]:
        m = re.search(
            rf'<span class="tweet-stat"[^>]*>.*?{label}.*?<b>([\d,]+)</b>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            return int(m.group(1).replace(",", ""))
        # Alternative pattern
        m2 = re.search(
            rf'<span[^>]*title="{label}"[^>]*>([\d,]+)</span>',
            html,
            re.IGNORECASE,
        )
        if m2:
            return int(m2.group(1).replace(",", ""))
        return None

    # Timestamp
    ts_match = re.search(
        r'<span class="tweet-date"[^>]*><a[^>]+title="([^"]+)"',
        html,
        re.IGNORECASE,
    )
    timestamp = ts_match.group(1) if ts_match else None

    # Media images
    media_urls = []
    for img_m in re.finditer(r'<a class="still-image"[^>]+href="([^"]+)"', html, re.IGNORECASE):
        href = img_m.group(1)
        if href.startswith("/"):
            href = base_url + href
        media_urls.append(href)

    # Detect if it's a reply
    reply_context_match = re.search(
        r'Replying to\s*<a[^>]+>@([^<]+)</a>',
        html,
        re.IGNORECASE,
    )
    is_reply = bool(reply_context_match)
    replied_to_author = reply_context_match.group(1).strip() if reply_context_match else None

    post = PostData(
        post_id=post_id,
        author=author,
        text=text,
        timestamp=timestamp,
        media_urls=media_urls,
        reply_count=_stat("Replies"),
        retweet_count=_stat("Retweets"),
        like_count=_stat("Likes"),
        url=f"https://x.com/{author}/status/{post_id}",
        is_reply=is_reply,
        replied_to_author=replied_to_author,
        fetch_method="nitter",
    )
    return post


def _fetch_via_direct(author: str, post_id: str) -> PostData:
    """
    Last-resort: fetch x.com directly and do best-effort HTML parsing.
    X heavily uses JS rendering, so we may only get meta tags.
    """
    url = f"https://x.com/{author}/status/{post_id}"
    try:
        html = _http_get(url)
    except (URLError, HTTPError) as e:
        raise FetchError(f"Direct x.com fetch failed: {e}")

    # Try og:description (often contains tweet text in meta)
    og_match = re.search(
        r'<meta[^>]+(?:name="description"|property="og:description")[^>]+content="([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if og_match:
        text = og_match.group(1)
        text = (
            text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        return PostData(
            post_id=post_id,
            author=author,
            text=text,
            url=url,
            fetch_method="direct_meta",
        )

    raise FetchError("x.com returned no parseable content (JS-rendered page)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PostFetcher:
    """
    Fetches X/Twitter posts using a multi-method fallback chain.

    Usage:
        fetcher = PostFetcher()
        post = fetcher.fetch("https://x.com/user/status/123456789")
    """

    def __init__(self, fetch_thread_context: bool = True):
        self.fetch_thread_context = fetch_thread_context

    def fetch(self, url: str) -> PostData:
        """
        Fetch a post from a Twitter/X URL.

        Tries methods in order:
          1. fxtwitter API
          2. vxtwitter API
          3. Nitter instances
          4. Direct x.com (meta tags only)

        Raises FetchError if all methods fail.
        """
        try:
            author, post_id = extract_post_id(url)
        except ValueError as e:
            raise FetchError(str(e))

        logger.info(f"Fetching post {post_id} by @{author}")

        methods = [
            ("fxtwitter", lambda: _fetch_via_fxtwitter(author, post_id)),
            ("vxtwitter", lambda: _fetch_via_vxtwitter(author, post_id)),
            ("nitter",    lambda: _fetch_via_nitter(author, post_id)),
            ("direct",    lambda: _fetch_via_direct(author, post_id)),
        ]

        last_error = None
        for method_name, method_fn in methods:
            try:
                logger.debug(f"Trying method: {method_name}")
                post = method_fn()
                logger.info(f"Fetched via {method_name}: {post.summary()}")

                # Optionally fetch thread context (parent post if this is a reply)
                if self.fetch_thread_context and post.is_reply and post.replied_to_post_id:
                    post.thread_context = self._fetch_parent(
                        post.replied_to_author or author,
                        post.replied_to_post_id,
                    )

                return post

            except FetchError as e:
                logger.warning(f"Method {method_name} failed: {e}")
                last_error = e
            except Exception as e:
                logger.warning(f"Method {method_name} raised unexpected error: {e}")
                last_error = FetchError(str(e))

        raise FetchError(
            f"All fetch methods failed for {url}. Last error: {last_error}"
        )

    def _fetch_parent(self, author: str, post_id: str) -> Optional[PostData]:
        """Fetch parent post for thread context (best-effort, no recursion)."""
        try:
            parent_url = f"https://x.com/{author}/status/{post_id}"
            # Use a new fetcher with context disabled to avoid recursion
            fetcher = PostFetcher(fetch_thread_context=False)
            return fetcher.fetch(parent_url)
        except FetchError as e:
            logger.debug(f"Could not fetch parent post {post_id}: {e}")
            return None


def find_tweet_urls(text: str) -> list[str]:
    """
    Extract all X/Twitter URLs from a block of text.
    Returns a deduplicated list in order of first appearance.
    """
    pattern = re.compile(
        r"https?://(?:www\.)?(?:twitter\.com|x\.com)/\S+/status/\d+\S*",
        re.IGNORECASE,
    )
    seen = set()
    results = []
    for m in pattern.finditer(text):
        url = m.group(0).rstrip(".,;:!?\"'")
        if url not in seen:
            seen.add(url)
            results.append(url)
    return results


# ---------------------------------------------------------------------------
# CLI test helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python post_fetcher.py <tweet_url>")
        sys.exit(1)

    url = sys.argv[1]
    fetcher = PostFetcher()
    try:
        post = fetcher.fetch(url)
        print(json.dumps(post.to_dict(), indent=2, default=str))
    except FetchError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
