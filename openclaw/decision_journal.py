"""SQLite decision log — outcomes feed pattern engine and weekly learning."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("openclaw.decision_journal")


@dataclass
class Decision:
    timestamp: str
    category: str
    action: str
    context: dict[str, Any]
    outcome: str
    outcome_score: float
    employee: str
    confidence: float = 55.0


class DecisionJournal:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._init_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(decisions)").fetchall()
        cols = {r[1] for r in rows}
        if "outcome_at" not in cols:
            conn.execute("ALTER TABLE decisions ADD COLUMN outcome_at TEXT DEFAULT ''")
            logger.info("decision_journal migrated: outcome_at column")

    def _init_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                action TEXT NOT NULL,
                context_json TEXT NOT NULL,
                outcome TEXT DEFAULT '',
                outcome_score REAL DEFAULT 0.0,
                employee TEXT NOT NULL,
                confidence REAL DEFAULT 55.0,
                outcome_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_cat ON decisions(category)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_decision ON pending_approvals(decision_id)"
        )
        self._migrate(conn)
        conn.commit()
        conn.close()

    def log(
        self,
        category: str,
        action: str,
        context: dict[str, Any],
        employee: str = "bob",
        confidence: float = 55.0,
        outcome: str = "",
        outcome_score: float = 0.0,
    ) -> int:
        return self.log_decision(category, employee, action, context, confidence, outcome, outcome_score)

    def log_decision(
        self,
        category: str,
        employee: str,
        action: str,
        context: dict[str, Any],
        confidence: float = 55.0,
        outcome: str = "",
        outcome_score: float = 0.0,
    ) -> int:
        ts = datetime.utcnow().isoformat() + "Z"
        cur = self._conn.execute(
            """
            INSERT INTO decisions (timestamp, category, action, context_json, outcome, outcome_score, employee, confidence, outcome_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                category,
                action,
                json.dumps(context, default=str),
                outcome,
                outcome_score,
                employee,
                confidence,
                "" if not outcome else ts,
            ),
        )
        self._conn.commit()
        rid = int(cur.lastrowid)
        logger.info("decision_logged id=%s category=%s confidence=%s", rid, category, confidence)
        return rid

    def update_outcome(self, decision_id: int, outcome: str, outcome_score: float) -> None:
        ts = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            "UPDATE decisions SET outcome = ?, outcome_score = ?, outcome_at = ? WHERE id = ?",
            (outcome, outcome_score, ts, decision_id),
        )
        self._conn.commit()

    def get_recent(self, hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        rows = self._conn.execute(
            """
            SELECT id, timestamp, category, action, context_json, outcome, outcome_score, employee, confidence, outcome_at
            FROM decisions WHERE timestamp >= ? ORDER BY id DESC LIMIT ?
            """,
            (since, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["context"] = json.loads(d.pop("context_json", "{}"))
            except json.JSONDecodeError:
                d["context"] = {}
            out.append(d)
        return out

    def get_accuracy(self, category: Optional[str] = None, days: int = 7) -> dict[str, Any]:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        base = "FROM decisions WHERE timestamp >= ? AND outcome != '' AND outcome IS NOT NULL"
        params: list[Any] = [since]
        if category:
            base += " AND category = ?"
            params.append(category)
        total = self._conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        good = self._conn.execute(
            f"SELECT COUNT(*) {base} AND outcome_score > 0", params
        ).fetchone()[0]
        bad = self._conn.execute(
            f"SELECT COUNT(*) {base} AND outcome_score < 0", params
        ).fetchone()[0]
        rate = (float(good) / float(total)) if total else 0.0
        return {
            "window_days": days,
            "category": category,
            "with_outcome": int(total),
            "positive_outcomes": int(good),
            "negative_outcomes": int(bad),
            "positive_rate": round(rate, 3),
        }

    def get_weekly_summary(self) -> dict[str, Any]:
        since = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        by_cat = self._conn.execute(
            """
            SELECT category,
                   COUNT(*) as n,
                   SUM(CASE WHEN outcome != '' THEN 1 ELSE 0 END) as with_out,
                   SUM(CASE WHEN outcome_score > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(confidence) as avgc
            FROM decisions WHERE timestamp >= ?
            GROUP BY category
            """,
            (since,),
        ).fetchall()
        acc = self.get_accuracy(category=None, days=7)
        return {
            "window_days": 7,
            "accuracy": acc,
            "by_category": [
                {
                    "category": r[0],
                    "decisions": int(r[1]),
                    "with_outcome": int(r[2] or 0),
                    "positive_outcomes": int(r[3] or 0),
                    "avg_confidence": round(float(r[4] or 0), 1),
                }
                for r in by_cat
            ],
        }

    def avg_confidence_24h(self) -> float:
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"
        row = self._conn.execute(
            "SELECT AVG(confidence) FROM decisions WHERE timestamp >= ?",
            (since,),
        ).fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return 0.0

    def _positive_rate_in_range(
        self, since_iso: str, until_iso: Optional[str] = None
    ) -> tuple[int, int, Optional[float]]:
        """Count decisions with outcomes in [since_iso, until_iso); until None = no upper bound."""
        if until_iso:
            base = "timestamp >= ? AND timestamp < ?"
            params: tuple = (since_iso, until_iso)
        else:
            base = "timestamp >= ?"
            params = (since_iso,)
        total = self._conn.execute(
            f"SELECT COUNT(*) FROM decisions WHERE {base} AND outcome != '' AND outcome IS NOT NULL",
            params,
        ).fetchone()[0]
        good = self._conn.execute(
            f"SELECT COUNT(*) FROM decisions WHERE {base} AND outcome != '' AND outcome IS NOT NULL AND outcome_score > 0",
            params,
        ).fetchone()[0]
        rate = (float(good) / float(total)) if total else None
        return int(total), int(good), rate

    def weekly_digest_text(self, patterns: Optional[dict[str, Any]] = None) -> str:
        """Rich 'What I learned' block for daily briefing (close-the-loop §3b)."""
        summary = self.get_weekly_summary()
        since_7d = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        since_14d = (datetime.utcnow() - timedelta(days=14)).isoformat() + "Z"
        total_logged = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE timestamp >= ?", (since_7d,)
            ).fetchone()[0]
        )
        scored, _pos, rate_7 = self._positive_rate_in_range(since_7d, None)
        _pw, _pw_good, rate_prior = self._positive_rate_in_range(since_14d, since_7d)
        pct_scored = int(round(100 * scored / total_logged)) if total_logged else 0
        acc_pct = int(round(100 * rate_7)) if rate_7 is not None else None
        prior_pct = int(round(100 * rate_prior)) if rate_prior is not None else None
        mis_email = int(
            self._conn.execute(
                """
                SELECT COUNT(*) FROM decisions
                WHERE timestamp >= ? AND category = 'email'
                  AND LOWER(COALESCE(outcome, '')) LIKE '%misclassif%'
                """,
                (since_7d,),
            ).fetchone()[0]
        )
        now = datetime.utcnow()
        wk_start = now - timedelta(days=7)
        header = (
            f"This week ({wk_start.strftime('%b %d')}–{now.strftime('%b %d, %Y')}):"
        )
        sep = "━━━━━━━━━━━━━━━━━━"
        lines = [
            header,
            sep,
            f"Decisions: {total_logged} logged, {scored} scored ({pct_scored}%)",
        ]
        if acc_pct is not None:
            acc_line = f"Accuracy: {acc_pct}% positive outcomes (of scored)"
            if prior_pct is not None:
                delta = acc_pct - prior_pct
                acc_line += f" — prior week {prior_pct}% ({delta:+d} pp)"
            lines.append(acc_line)
        else:
            lines.append("Accuracy: not enough scored outcomes yet this week.")
        lines.append("")
        lines.append("By category:")
        for row in sorted(
            summary.get("by_category", []),
            key=lambda r: -int(r.get("decisions", 0)),
        )[:8]:
            wo = int(row.get("with_outcome", 0) or 0)
            po = int(row.get("positive_outcomes", 0) or 0)
            cat_acc = int(round(100 * po / wo)) if wo else None
            extra = ""
            if row.get("category") == "email" and mis_email and wo:
                extra = f" — {mis_email} misclassification(s) noted"
            if cat_acc is not None:
                lines.append(
                    f"  {row['category']}: {row['decisions']} decisions, ~{cat_acc}% positive (scored) "
                    f"(avg conf {row.get('avg_confidence', 0)}){extra}"
                )
            else:
                lines.append(
                    f"  {row['category']}: {row['decisions']} decisions (no scores yet) "
                    f"(avg conf {row.get('avg_confidence', 0)}){extra}"
                )
        hints = (patterns or {}).get("hints") or []
        clients = (patterns or {}).get("clients") or {}
        if hints or clients:
            lines.append("")
            lines.append("Patterns / timing:")
            for h in hints[:5]:
                lines.append(f"  • {h}")
            top_clients = sorted(
                clients.items(),
                key=lambda x: -int((x[1] or {}).get("samples") or 0),
            )[:3]
            for name, d in top_clients:
                if not isinstance(d, dict):
                    continue
                bh = d.get("best_hour_local_mdt")
                bd = d.get("best_weekday")
                if bh is not None and bd:
                    lines.append(
                        f"  • {name}: often active ~{bh}:00 local ({bd}, n={d.get('samples', '?')})"
                    )
        lines.append("")
        lines.append(
            "Tip: more outcomes flow when trades redeem and clients reply — calibration tightens."
        )
        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        since7 = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        week = self._conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE timestamp >= ?", (since7,)
        ).fetchone()[0]
        return {
            "total_decisions": int(total),
            "decisions_last_7_days": int(week),
            "avg_confidence_24h": round(self.avg_confidence_24h(), 1),
        }

    def decisions_since(self, since_iso: str) -> list[tuple]:
        return self._conn.execute(
            "SELECT category, action, confidence FROM decisions WHERE timestamp >= ?",
            (since_iso,),
        ).fetchall()

    def search_recent(
        self,
        category: str,
        context_contains: str,
        hours: int = 168,
        limit: int = 5,
        only_unscored: bool = True,
    ) -> list[dict[str, Any]]:
        """Find recent decisions matching category and optional context substring (for outcome wiring)."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        needle = context_contains.strip() if context_contains else ""
        like = f"%{needle}%" if needle else "%"
        unscored = " AND (outcome IS NULL OR outcome = '')" if only_unscored else ""
        rows = self._conn.execute(
            f"""
            SELECT id, timestamp, category, action, context_json, outcome, outcome_score, employee, confidence, outcome_at
            FROM decisions
            WHERE category = ? AND context_json LIKE ? AND timestamp >= ?{unscored}
            ORDER BY timestamp DESC LIMIT ?
            """,
            (category, like, since, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["context"] = json.loads(d.pop("context_json", "{}"))
            except json.JSONDecodeError:
                d["context"] = {}
            out.append(d)
        return out

    def add_pending(self, decision_id: int, kind: str, context: dict[str, Any]) -> None:
        ts = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            """
            INSERT INTO pending_approvals (decision_id, kind, context_json, created_at, status)
            VALUES (?, ?, ?, ?, 'pending')
            ON CONFLICT(decision_id) DO UPDATE SET
                kind = excluded.kind,
                context_json = excluded.context_json,
                created_at = excluded.created_at,
                status = 'pending'
            """,
            (decision_id, kind, json.dumps(context, default=str), ts),
        )
        self._conn.commit()

    def get_pending(self, decision_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT id, decision_id, kind, context_json, created_at, status FROM pending_approvals WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["context"] = json.loads(d.pop("context_json", "{}"))
        except json.JSONDecodeError:
            d["context"] = {}
        return d

    def close_pending(self, decision_id: int, status: str) -> None:
        """status: granted | denied"""
        self._conn.execute(
            "UPDATE pending_approvals SET status = ? WHERE decision_id = ?",
            (status, decision_id),
        )
        self._conn.commit()


_journal: Optional[DecisionJournal] = None


def get_journal(data_dir: Path) -> DecisionJournal:
    global _journal
    if _journal is None:
        _journal = DecisionJournal(data_dir / "decision_journal.db")
    return _journal
