#!/usr/bin/env python3
"""
client_relationship.py
======================
Client relationship management and retention engine for Bob's ClawWork operation.

Tracks client history, scores client quality, manages review acquisition,
and surfaces upsell opportunities. Designed to maximize repeat business
and referral revenue from high-value clients.

Key capabilities:
  - Client scoring (likelihood to pay, review, repeat)
  - Review request generation (platform-appropriate, personalized)
  - Upsell opportunity detection
  - Communication history logging
  - Client tier classification (Gold / Silver / Bronze)

Usage:
    from client_relationship import ClientManager
    clients = ClientManager("/data/clients.db")
    clients.log_project(client_id, task_id, value, quality)
    should_request, reason = clients.should_request_review(client_id, task_id)
"""

import json
import logging
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("clawwork.clients")

# ── Tier thresholds ───────────────────────────────────────────────────────────────────
TIER_GOLD_MIN_VALUE   = 500.0   # $500+ lifetime value
TIER_GOLD_MIN_TASKS   = 3       # 3+ completed projects
TIER_SILVER_MIN_VALUE = 100.0
TIER_SILVER_MIN_TASKS = 1

# Review request timing
REVIEW_COOLDOWN_DAYS = 30      # Don’t ask more than once per 30 days

# Upsell opportunity triggers
UPSELL_TRIGGERS = {
    "research_reports":   ["content_writing", "technical_writing", "bookkeeping"],
    "content_writing":    ["research_reports", "real_estate"],
    "real_estate":        ["bookkeeping", "content_writing", "research_reports"],
    "bookkeeping":        ["research_reports", "real_estate"],
    "code_review":        ["technical_writing", "research_reports"],
    "technical_writing":  ["code_review", "research_reports"],
    "customer_support":   ["content_writing"],
    "data_entry":         ["bookkeeping", "research_reports"],
}


# ── Data classes ───────────────────────────────────────────────────────────────────────

@dataclass
class ClientRecord:
    client_id:         str
    platform:          str
    first_seen:        str          # ISO date
    total_tasks:       int   = 0
    total_value:       float = 0.0
    avg_rating:        float = 0.0
    last_project:      Optional[str] = None
    last_review_req:   Optional[str] = None
    left_reviews:      int   = 0
    sectors:           str   = "[]"  # JSON list of sectors worked for this client
    notes:             str   = ""
    # Computed fields (not stored)
    tier:              str   = field(default="bronze", compare=False)
    score:             float = field(default=0.0, compare=False)


@dataclass
class ProjectRecord:
    project_id:    str
    client_id:     str
    task_id:       str
    platform:      str
    sector:        str
    gross_value:   float
    net_value:     float
    quality_score: float
    rating:        Optional[float]  = None   # Client-given rating (1–5)
    review_text:   Optional[str]   = None
    completed_at:  str             = ""
    review_req_at: Optional[str]   = None


# ── Database layer ────────────────────────────────────────────────────────────────────

class ClientDB:
    """SQLite-backed store for client and project records."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                client_id       TEXT PRIMARY KEY,
                platform        TEXT NOT NULL,
                first_seen      TEXT NOT NULL,
                total_tasks     INTEGER DEFAULT 0,
                total_value     REAL    DEFAULT 0.0,
                avg_rating      REAL    DEFAULT 0.0,
                last_project    TEXT,
                last_review_req TEXT,
                left_reviews    INTEGER DEFAULT 0,
                sectors         TEXT    DEFAULT '[]',
                notes           TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS projects (
                project_id    TEXT PRIMARY KEY,
                client_id     TEXT NOT NULL,
                task_id       TEXT NOT NULL,
                platform      TEXT NOT NULL,
                sector        TEXT NOT NULL,
                gross_value   REAL NOT NULL,
                net_value     REAL NOT NULL,
                quality_score REAL NOT NULL,
                rating        REAL,
                review_text   TEXT,
                completed_at  TEXT NOT NULL,
                review_req_at TEXT,
                FOREIGN KEY(client_id) REFERENCES clients(client_id)
            );

            CREATE INDEX IF NOT EXISTS idx_projects_client
            ON projects(client_id);
        """)
        self.conn.commit()

    # ─ Client CRUD ───────────────────────────────────────────────────────────────────────

    def upsert_client(self, client: ClientRecord):
        self.conn.execute("""
            INSERT INTO clients
            (client_id, platform, first_seen, total_tasks, total_value,
             avg_rating, last_project, last_review_req, left_reviews, sectors, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(client_id) DO UPDATE SET
                total_tasks     = excluded.total_tasks,
                total_value     = excluded.total_value,
                avg_rating      = excluded.avg_rating,
                last_project    = excluded.last_project,
                last_review_req = excluded.last_review_req,
                left_reviews    = excluded.left_reviews,
                sectors         = excluded.sectors,
                notes           = excluded.notes
        """, (
            client.client_id, client.platform, client.first_seen,
            client.total_tasks, client.total_value, client.avg_rating,
            client.last_project, client.last_review_req, client.left_reviews,
            client.sectors, client.notes
        ))
        self.conn.commit()

    def get_client(self, client_id: str) -> Optional[ClientRecord]:
        row = self.conn.execute(
            "SELECT * FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone()
        if not row:
            return None
        return ClientRecord(**dict(row))

    def all_clients(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM clients ORDER BY total_value DESC"
        ).fetchall()
        return [ClientRecord(**dict(r)) for r in rows]

    # ─ Project CRUD ─────────────────────────────────────────────────────────────────────

    def insert_project(self, proj: ProjectRecord):
        self.conn.execute("""
            INSERT OR IGNORE INTO projects
            (project_id, client_id, task_id, platform, sector,
             gross_value, net_value, quality_score, rating,
             review_text, completed_at, review_req_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            proj.project_id, proj.client_id, proj.task_id,
            proj.platform, proj.sector, proj.gross_value, proj.net_value,
            proj.quality_score, proj.rating, proj.review_text,
            proj.completed_at, proj.review_req_at
        ))
        self.conn.commit()

    def get_projects_for_client(self, client_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM projects WHERE client_id = ? ORDER BY completed_at",
            (client_id,)
        ).fetchall()
        return [ProjectRecord(**dict(r)) for r in rows]

    def update_project_review(self, project_id: str, rating: float, review_text: str):
        self.conn.execute("""
            UPDATE projects SET rating=?, review_text=? WHERE project_id=?
        """, (rating, review_text, project_id))
        self.conn.commit()

    def mark_review_requested(self, project_id: str, when: str):
        self.conn.execute(
            "UPDATE projects SET review_req_at=? WHERE project_id=?",
            (when, project_id)
        )
        self.conn.commit()


# ── ClientManager ────────────────────────────────────────────────────────────────────────

class ClientManager:
    """
    High-level interface for managing ClawWork client relationships.

    Wraps ClientDB with business logic for scoring, review requests,
    upsell detection, and tier classification.
    """

    def __init__(self, db_path: str = "/data/clients.db"):
        self.db = ClientDB(db_path)

    # ─ Core logging ──────────────────────────────────────────────────────────────────────

    def log_project(
        self,
        client_id:    str,
        task_id:      str,
        platform:     str,
        sector:       str,
        gross_value:  float,
        net_value:    float,
        quality_score:float,
        rating:       Optional[float] = None,
        review_text:  Optional[str]  = None,
    ) -> ProjectRecord:
        """
        Record a completed project and update the client's aggregate stats.

        Returns the newly created ProjectRecord.
        """
        now = datetime.utcnow().isoformat()
        project_id = f"{client_id}_{task_id}_{now[:10]}"

        proj = ProjectRecord(
            project_id    = project_id,
            client_id     = client_id,
            task_id       = task_id,
            platform      = platform,
            sector        = sector,
            gross_value   = gross_value,
            net_value     = net_value,
            quality_score = quality_score,
            rating        = rating,
            review_text   = review_text,
            completed_at  = now,
        )
        self.db.insert_project(proj)
        self._update_client_aggregate(client_id, platform, sector, net_value, rating)

        log.info("Logged project %s for client %s (net $%.2f)",
                 project_id, client_id, net_value)
        return proj

    def _update_client_aggregate(
        self, client_id: str, platform: str,
        sector: str, net_value: float, rating: Optional[float]
    ):
        """Create or update the ClientRecord aggregate."""
        client = self.db.get_client(client_id)
        today  = date.today().isoformat()

        if client is None:
            # New client
            client = ClientRecord(
                client_id   = client_id,
                platform    = platform,
                first_seen  = today,
                total_tasks = 1,
                total_value = net_value,
                avg_rating  = rating or 0.0,
                last_project= today,
                sectors     = json.dumps([sector]),
            )
        else:
            # Update existing
            sectors = json.loads(client.sectors or "[]")
            if sector not in sectors:
                sectors.append(sector)
            new_task_count = client.total_tasks + 1
            new_total      = client.total_value + net_value
            if rating:
                # Running average of ratings
                old_avg = client.avg_rating or 0.0
                old_n   = client.left_reviews if client.left_reviews > 0 else client.total_tasks
                new_avg = (old_avg * old_n + rating) / (old_n + 1)
            else:
                new_avg = client.avg_rating

            client.total_tasks  = new_task_count
            client.total_value  = new_total
            client.avg_rating   = round(new_avg, 3)
            client.last_project = today
            client.sectors      = json.dumps(sectors)

        self.db.upsert_client(client)

    # ─ Review management ───────────────────────────────────────────────────────────

    def should_request_review(
        self, client_id: str, project_id: str
    ) -> tuple:
        """
        Returns (should_request: bool, reason: str).

        Rules:
          1. Never request if already reviewed this project
          2. Never request if last review request was <30 days ago
          3. Always request if first project with this client (building history)
          4. Request if client has left reviews before (high yield)
          5. Request if project value > $100 (high-value clients worth the ask)
        """
        client = self.db.get_client(client_id)
        if client is None:
            return False, "Unknown client"

        # Check cooldown
        if client.last_review_req:
            last_req = datetime.fromisoformat(client.last_review_req).date()
            days_since = (date.today() - last_req).days
            if days_since < REVIEW_COOLDOWN_DAYS:
                return False, f"Review cooldown ({days_since}/{REVIEW_COOLDOWN_DAYS} days)"

        # First project: always ask
        if client.total_tasks == 1:
            return True, "First project with client — establish review relationship"

        # Client has left reviews before: high yield
        if client.left_reviews > 0:
            return True, f"Client has left {client.left_reviews} reviews before"

        # High-value project
        projects = self.db.get_projects_for_client(client_id)
        recent = next((p for p in reversed(projects) if p.project_id == project_id), None)
        if recent and recent.net_value >= 100.0:
            return True, f"High-value project (${recent.net_value:.0f})"

        # Gold-tier client: always maintain relationship
        tier = self._calculate_tier(client)
        if tier == "gold":
            return True, "Gold-tier client — proactive engagement"

        return False, "No compelling review trigger"

    def generate_review_request(
        self, client_id: str, project_id: str, platform: str = "generic"
    ) -> str:
        """
        Generate a personalized, platform-appropriate review request message.
        """
        client   = self.db.get_client(client_id)
        projects = self.db.get_projects_for_client(client_id)
        recent   = next((p for p in reversed(projects) if p.project_id == project_id), None)

        if not recent:
            project_desc = "our recent project"
        else:
            sector_labels = {
                "research_reports": "the research report",
                "content_writing": "the content piece",
                "bookkeeping": "the bookkeeping work",
                "technical_writing": "the technical documentation",
                "real_estate": "the real estate materials",
                "code_review": "the code review",
                "customer_support": "the support materials",
                "data_entry": "the data processing work",
            }
            project_desc = sector_labels.get(recent.sector, "our recent project")

        is_repeat = (client and client.total_tasks and client.total_tasks > 1)
        repeat_line = (
            " As always, it’s been a pleasure working with you."
            if is_repeat else ""
        )

        if platform == "upwork":
            return (
                f"Thank you for the opportunity to work on {project_desc}.{repeat_line} "
                f"If you’re happy with the deliverables, a quick review on Upwork would "
                f"mean a great deal — it helps me continue providing quality work for "
                f"clients like you. No pressure at all if you’re short on time!"
            )
        elif platform == "fiverr":
            return (
                f"Thanks for ordering!{repeat_line} If {project_desc} met your expectations, "
                f"I’d really appreciate a brief Fiverr review. It takes less than 30 seconds "
                f"and helps other clients find quality freelancers."
            )
        else:
            return (
                f"Thank you for the opportunity to deliver {project_desc}.{repeat_line} "
                f"If you were satisfied with the results, a brief review or testimonial "
                f"would be greatly appreciated. I’m always looking to improve, so honest "
                f"feedback is welcome too."
            )

    def record_review_received(
        self, client_id: str, project_id: str, rating: float, review_text: str = ""
    ):
        """Record that a client left a review. Updates client aggregate stats."""
        self.db.update_project_review(project_id, rating, review_text)
        client = self.db.get_client(client_id)
        if client:
            client.left_reviews += 1
            self.db.upsert_client(client)
        log.info("Review received from %s: %.1f stars", client_id, rating)

    # ─ Scoring and tiers ───────────────────────────────────────────────────────────

    def get_client_score(self, client_id: str) -> float:
        """
        Returns a 0–1.0 quality score for a client.

        Used by TaskScorer to prioritise tasks from known good clients.
        """
        client = self.db.get_client(client_id)
        if not client:
            return 0.3   # unknown client: moderate

        score  = 0.2     # baseline

        # Repeat client bonus
        if client.total_tasks >= 3:
            score += 0.3
        elif client.total_tasks >= 1:
            score += 0.1

        # Review history bonus
        if client.left_reviews >= 2:
            score += 0.2
        elif client.left_reviews == 1:
            score += 0.1

        # High avg rating
        if client.avg_rating >= 4.8:
            score += 0.2
        elif client.avg_rating >= 4.0:
            score += 0.1

        # Lifetime value bonus
        if client.total_value >= TIER_GOLD_MIN_VALUE:
            score += 0.1

        return min(1.0, score)

    def _calculate_tier(self, client: ClientRecord) -> str:
        """Classify client as gold / silver / bronze."""
        if (client.total_value >= TIER_GOLD_MIN_VALUE and
                client.total_tasks >= TIER_GOLD_MIN_TASKS):
            return "gold"
        elif (client.total_value >= TIER_SILVER_MIN_VALUE and
              client.total_tasks >= TIER_SILVER_MIN_TASKS):
            return "silver"
        return "bronze"

    # ─ Upsell detection ──────────────────────────────────────────────────────────────

    def detect_upsell_opportunities(self, client_id: str) -> list:
        """
        Identify adjacent services this client hasn’t used yet.

        Returns list of {"sector": str, "reason": str} dicts.
        """
        client = self.db.get_client(client_id)
        if not client or client.total_tasks < 1:
            return []

        used_sectors = set(json.loads(client.sectors or "[]"))
        opportunities = []

        for sector in used_sectors:
            adjacent = UPSELL_TRIGGERS.get(sector, [])
            for adj in adjacent:
                if adj not in used_sectors:
                    opportunities.append({
                        "sector": adj,
                        "reason": f"Client uses {sector}; {adj} is a natural complement",
                    })

        # Deduplicate by sector
        seen = set()
        unique = []
        for op in opportunities:
            if op["sector"] not in seen:
                seen.add(op["sector"])
                unique.append(op)

        return unique

    # ─ Reporting ────────────────────────────────────────────────────────────────────────────

    def client_summary_report(self) -> dict:
        """
        Returns a structured summary of all clients for dashboard display.
        """
        clients  = self.db.all_clients()
        gold     = []
        silver   = []
        bronze   = []

        for c in clients:
            tier    = self._calculate_tier(c)
            score   = self.get_client_score(c.client_id)
            upsells = self.detect_upsell_opportunities(c.client_id)
            record  = {
                "client_id":    c.client_id,
                "platform":     c.platform,
                "tier":         tier,
                "score":        round(score, 3),
                "total_value":  round(c.total_value, 2),
                "total_tasks":  c.total_tasks,
                "avg_rating":   round(c.avg_rating, 2),
                "left_reviews": c.left_reviews,
                "sectors":      json.loads(c.sectors or "[]"),
                "upsells":      upsells,
                "last_project": c.last_project,
            }
            if tier == "gold":
                gold.append(record)
            elif tier == "silver":
                silver.append(record)
            else:
                bronze.append(record)

        return {
            "total_clients": len(clients),
            "gold":   gold,
            "silver": silver,
            "bronze": bronze[:20],   # cap bronze list for readability
        }

    def top_clients_by_value(self, n: int = 10) -> list:
        """Return top N clients sorted by total lifetime value."""
        clients = self.db.all_clients()
        return sorted(clients, key=lambda c: c.total_value, reverse=True)[:n]


# ── CLI demo ──────────────────────────────────────────────────────────────────────────────────

def main():
    import tempfile
    import os

    # Use a temp DB for the demo
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    mgr = ClientManager(db_path)

    # Simulate some completed projects
    mgr.log_project("CLIENT-001", "TASK-001", "upwork",   "research_reports", 320.0, 256.0, 0.91)
    mgr.log_project("CLIENT-001", "TASK-002", "upwork",   "research_reports", 280.0, 224.0, 0.89)
    mgr.log_project("CLIENT-002", "TASK-003", "fiverr",   "content_writing",   45.0,  36.0, 0.85)
    mgr.log_project("CLIENT-003", "TASK-004", "gdpval",   "bookkeeping",       150.0, 150.0, 0.93)
    mgr.log_project("CLIENT-001", "TASK-005", "upwork",   "technical_writing", 190.0, 152.0, 0.90)
    mgr.log_project("CLIENT-004", "TASK-006", "codementor","code_review",        80.0,  64.0, 0.88)

    # Simulate a review received
    mgr.record_review_received("CLIENT-001", "CLIENT-001_TASK-001_2026-02-27", 5.0, "Excellent work!")

    # Review request check
    for cid in ["CLIENT-001", "CLIENT-002", "CLIENT-003"]:
        should, reason = mgr.should_request_review(cid, f"{cid}_last_project")
        print(f"Review request for {cid}: {should} — {reason}")

    # Upsell opportunities
    for cid in ["CLIENT-001", "CLIENT-003"]:
        ups = mgr.detect_upsell_opportunities(cid)
        if ups:
            print(f"\nUpsell opportunities for {cid}:")
            for u in ups:
                print(f"  • {u['sector']}: {u['reason']}")

    # Full report
    print("\n── Client Summary Report ──")
    print(json.dumps(mgr.client_summary_report(), indent=2))

    os.unlink(db_path)


if __name__ == "__main__":
    main()
