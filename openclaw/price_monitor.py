"""
Snap One Supplier Price Monitor
================================
Monitors Snap One (snapone.com) for price changes on items in active proposals.

- Maintains a watchlist of SKUs in SQLite `price_watchlist`.
- On each daily_tick(), checks prices and alerts on changes > 2%.
- Falls back to Google Shopping search if Snap One portal requires auth.
- Pre-populates the watchlist with Symphony Smart Homes standard SKUs on first run.

Usage
-----
    monitor = PriceMonitor(db_path="/data/prices.db", http=httpx_client)
    changes = await monitor.daily_tick()
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger("openclaw.price_monitor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = os.getenv("PRICE_MONITOR_DB_PATH", "/data/prices.db")
PRICE_CHANGE_THRESHOLD = 0.02  # 2%

# Pre-populated initial watchlist (job_id=0 = general watchlist)
INITIAL_WATCHLIST: list[dict] = [
    {"sku": "RR-PROC3-KIT1",      "product_name": "Lutron RadioRA 3 Processor",          "job_id": 0},
    {"sku": "RRST-PRO-N-WH",      "product_name": "Sunnata PRO RF Dimmer",               "job_id": 0},
    {"sku": "CORE3",               "product_name": "Control4 CORE3 Controller",           "job_id": 0},
    {"sku": "UDM-SE",              "product_name": "UniFi Dream Machine SE",              "job_id": 0},
    {"sku": "TS-PAMP8-125-V2",     "product_name": "Triad TS-PAMP8-125-V2",              "job_id": 0},
    {"sku": "WATTBOX-POWER",       "product_name": "WattBox Power Conditioner",           "job_id": 0},
]

# Snap One product page URL template
SNAPONE_PRODUCT_URL = "https://www.snapone.com/products/{sku}"
SNAPONE_API_URL     = "https://api.snapone.com"

# Google Shopping fallback search URL
GOOGLE_SHOPPING_URL = (
    "https://www.google.com/search?tbm=shop&q={query}"
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_watchlist (
                sku           TEXT    NOT NULL,
                product_name  TEXT    NOT NULL,
                last_price    REAL,
                last_checked  TEXT,
                job_id        INT     NOT NULL DEFAULT 0,
                PRIMARY KEY (sku, job_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sku          TEXT    NOT NULL,
                price        REAL    NOT NULL,
                checked_at   TEXT    NOT NULL
            )
        """)
        conn.commit()


def _seed_watchlist(db_path: str) -> None:
    """Insert the initial Symphony watchlist if not already present."""
    with sqlite3.connect(db_path) as conn:
        for item in INITIAL_WATCHLIST:
            conn.execute(
                """INSERT OR IGNORE INTO price_watchlist (sku, product_name, job_id)
                   VALUES (:sku, :product_name, :job_id)""",
                item,
            )
        conn.commit()


def _get_watchlist(db_path: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM price_watchlist ORDER BY sku"
        ).fetchall()
    return [dict(r) for r in rows]


def _update_price(db_path: str, sku: str, job_id: int, price: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """UPDATE price_watchlist
               SET last_price = ?, last_checked = ?
               WHERE sku = ? AND job_id = ?""",
            (price, now, sku, job_id),
        )
        conn.execute(
            "INSERT INTO price_history (sku, price, checked_at) VALUES (?, ?, ?)",
            (sku, price, now),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Price extraction helpers
# ---------------------------------------------------------------------------

# Common patterns for prices on product pages
_PRICE_RE = re.compile(
    r"""(?:
        \$\s*(?P<a>[\d,]+(?:\.\d{1,2})?)   # $1,234.56
        |
        (?P<b>[\d,]+(?:\.\d{1,2})?)\s*USD  # 1234.56 USD
    )""",
    re.VERBOSE,
)


def _extract_price_from_text(text: str) -> Optional[float]:
    """Pull the first plausible price from a block of HTML/text."""
    for match in _PRICE_RE.finditer(text):
        raw = match.group("a") or match.group("b")
        if raw:
            try:
                val = float(raw.replace(",", ""))
                # Sanity check: prices between $1 and $100,000
                if 1.0 <= val <= 100_000.0:
                    return val
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# PriceMonitor
# ---------------------------------------------------------------------------


class PriceMonitor:
    """
    Daily price monitor for Snap One products.

    Parameters
    ----------
    db_path : str
        SQLite database path.
    http : httpx.AsyncClient
        Shared async HTTP client.
    notify_fn : optional
        Async callable(message: str) for iMessage/notification.
    linear_sync : optional
        LinearSync instance for creating issues.
    """

    def __init__(
        self,
        db_path: str,
        http: httpx.AsyncClient,
        notify_fn: Optional[Callable] = None,
        linear_sync: Any = None,
    ) -> None:
        self._db_path = db_path
        self._http = http
        self._notify_fn = notify_fn
        self._linear = linear_sync
        self._last_run_date: Optional[date] = None

        _init_db(self._db_path)
        _seed_watchlist(self._db_path)
        logger.info("PriceMonitor initialised | db=%s", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def daily_tick(self) -> int:
        """
        Run price checks. Executes once per calendar day.

        Returns
        -------
        int
            Number of price changes detected.
        """
        today = date.today()
        if self._last_run_date == today:
            logger.debug("PriceMonitor already ran today (%s) — skipping", today)
            return 0

        self._last_run_date = today
        logger.info("PriceMonitor daily_tick starting — date=%s", today)

        watchlist = _get_watchlist(self._db_path)
        changes_found = 0

        for item in watchlist:
            sku = item["sku"]
            product_name = item["product_name"]
            last_price: Optional[float] = item.get("last_price")
            job_id: int = item.get("job_id", 0)

            current_price = await self.check_price(sku, product_name)
            if current_price is None:
                logger.info("Could not determine price for %s (%s)", sku, product_name)
                continue

            _update_price(self._db_path, sku, job_id, current_price)

            if last_price is None:
                logger.info("First price recorded for %s: $%.2f", sku, current_price)
                continue

            pct_change = (current_price - last_price) / last_price
            if abs(pct_change) > PRICE_CHANGE_THRESHOLD:
                changes_found += 1
                direction = "increased" if pct_change > 0 else "decreased"
                pct_str = f"{abs(pct_change) * 100:.1f}%"
                logger.info(
                    "Price change: %s %s %s ($%.2f → $%.2f)",
                    sku, direction, pct_str, last_price, current_price,
                )
                await self._handle_price_change(
                    item=item,
                    old_price=last_price,
                    new_price=current_price,
                    pct_change=pct_change,
                )

        logger.info("PriceMonitor tick complete — %d changes found", changes_found)
        return changes_found

    async def add_to_watchlist(
        self, sku: str, product_name: str, job_id: int
    ) -> None:
        """Add a SKU to the price watchlist for a given job."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO price_watchlist (sku, product_name, job_id)
                   VALUES (?, ?, ?)""",
                (sku, product_name, job_id),
            )
            conn.commit()
        logger.info("Added to watchlist: %s (%s) job_id=%d", sku, product_name, job_id)

    async def check_price(
        self, sku: str, product_name: str
    ) -> Optional[float]:
        """
        Return current price for a SKU.
        Tries Snap One product page first, then falls back to Google Shopping.
        """
        price = await self._fetch_snapone_price(sku)
        if price is not None:
            return price

        logger.debug("Snap One price unavailable for %s — trying fallback", sku)
        price = await self._fallback_price_search(product_name)
        return price

    # ------------------------------------------------------------------
    # Private fetch methods
    # ------------------------------------------------------------------

    async def _fetch_snapone_price(self, sku: str) -> Optional[float]:
        """
        Attempt to fetch the current price from the Snap One product page.
        Returns None if the page requires authentication or price is not found.
        """
        url = SNAPONE_PRODUCT_URL.format(sku=sku)
        try:
            resp = await self._http.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    )
                },
                timeout=15.0,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            logger.debug("Snap One request error for %s: %s", sku, exc)
            return None

        if resp.status_code in (401, 403):
            logger.debug("Snap One auth required for SKU %s — will use fallback", sku)
            return None

        if resp.status_code != 200:
            logger.debug("Snap One returned %d for SKU %s", resp.status_code, sku)
            return None

        # Check for login wall indicators
        page_text = resp.text
        if any(kw in page_text.lower() for kw in ("sign in", "log in", "dealer login")):
            # Check if actual price data is still present
            price = _extract_price_from_text(page_text)
            if price is None:
                logger.debug("Snap One login wall detected for SKU %s", sku)
                return None
            return price

        return _extract_price_from_text(page_text)

    async def _fallback_price_search(self, product_name: str) -> Optional[float]:
        """
        Fallback: search Google Shopping for the product name + "price".
        Extracts the first plausible price from the results page.
        """
        query = f"{product_name} price"
        url = GOOGLE_SHOPPING_URL.format(
            query=query.replace(" ", "+")
        )
        try:
            resp = await self._http.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15.0,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            logger.debug("Google Shopping request error for '%s': %s", product_name, exc)
            return None

        if resp.status_code != 200:
            logger.debug(
                "Google Shopping returned %d for '%s'", resp.status_code, product_name
            )
            return None

        return _extract_price_from_text(resp.text)

    # ------------------------------------------------------------------
    # Alert / issue creation
    # ------------------------------------------------------------------

    async def _handle_price_change(
        self,
        item: dict,
        old_price: float,
        new_price: float,
        pct_change: float,
    ) -> None:
        """Create a Linear issue and send an iMessage alert on price change."""
        sku = item["sku"]
        product_name = item["product_name"]
        job_id = item.get("job_id", 0)
        direction = "increased" if pct_change > 0 else "decreased"
        pct_str = f"{abs(pct_change) * 100:.1f}%"

        action_note = ""
        if pct_change > 0 and job_id != 0:
            action_note = "\n\n⚠️ **Action required:** This item is in an active proposal. Update the quote before sending."

        # Create Linear issue
        if self._linear is not None:
            title = f"[Price Alert] {product_name} ({sku}) {direction} {pct_str}"
            description = (
                f"**Product:** {product_name}\n"
                f"**SKU:** `{sku}`\n"
                f"**Previous price:** ${old_price:.2f}\n"
                f"**New price:** ${new_price:.2f}\n"
                f"**Change:** {'+' if pct_change > 0 else ''}{pct_change * 100:.1f}%\n"
                f"**Detected:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"**Job ID:** {job_id if job_id else 'General watchlist'}"
                f"{action_note}"
            )
            try:
                create_fn = getattr(self._linear, "create_issue", None)
                if callable(create_fn):
                    await create_fn(title=title, description=description)
                    logger.info("Linear issue created: %s", title)
            except Exception as exc:
                logger.error("Failed to create Linear price alert issue: %s", exc)

        # Send iMessage
        if self._notify_fn is not None:
            msg = (
                f"Bob: Price alert — {product_name} ({sku}) {direction} {pct_str} "
                f"(${old_price:.2f} → ${new_price:.2f})."
            )
            if pct_change > 0 and job_id != 0:
                msg += " Update quote — active proposal affected."
            try:
                await self._notify_fn(msg)
            except Exception as exc:
                logger.warning("notify_fn failed for price alert: %s", exc)
