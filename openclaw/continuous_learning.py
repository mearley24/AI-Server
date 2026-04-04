#!/usr/bin/env python3
"""
Continuous learner — mines decision journal and operational data
to build knowledge/cortex/ with new facts.

Run on schedule (launchd) or manually:
  python3 openclaw/continuous_learning.py

Sources:
  1. Decision journal — extract patterns from scored outcomes
  2. Cost tracker — trading outcomes by category
  3. Jobs DB — client/project patterns

Output:
  - Append new learnings to knowledge/cortex/learnings.md
  - Print summary for log capture
"""

import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
REPO_ROOT = os.environ.get("SYMPHONY_ROOT", "/Users/bob/AI-Server")


def mine_decision_journal() -> list[str]:
    """Extract patterns from recent decisions with outcomes."""
    db_path = os.path.join(DATA_DIR, "decision_journal.db")
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT category, action, outcome, outcome_score FROM decisions "
        "WHERE outcome IS NOT NULL AND timestamp > ? ORDER BY timestamp DESC LIMIT 50",
        (cutoff,),
    ).fetchall()
    conn.close()

    cat_scores: dict[str, list[float]] = defaultdict(list)
    for cat, _action, _outcome, score in rows:
        if score is not None:
            cat_scores[cat].append(float(score))

    learnings = []
    for cat, scores in sorted(cat_scores.items()):
        avg = sum(scores) / len(scores) if scores else 0
        learnings.append(f"- {cat}: {len(scores)} decisions, avg score {avg:.2f}")
    return learnings


def mine_trading_outcomes() -> list[str]:
    """Extract trading patterns from cost tracker."""
    db_path = os.path.join(DATA_DIR, "cost_tracker.db")
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT category, description, amount FROM costs "
            "WHERE category LIKE 'trading%' ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        conn.close()
        if rows:
            total = sum(r[2] for r in rows)
            return [f"- Trading: {len(rows)} recent entries, net ${total:.2f}"]
    except Exception:
        conn.close()
    return []


def mine_jobs() -> list[str]:
    """Summarise active jobs from jobs DB."""
    for candidate in (
        os.path.join(DATA_DIR, "jobs.db"),
        os.path.join(DATA_DIR, "openclaw", "jobs.db"),
    ):
        if os.path.exists(candidate):
            break
    else:
        return []
    conn = sqlite3.connect(candidate)
    try:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'active'"
        ).fetchone()[0]
        conn.close()
        if total:
            return [f"- Jobs: {active} active / {total} total"]
    except Exception:
        conn.close()
    return []


def write_learnings(learnings: list[str]) -> None:
    """Append learnings to cortex file."""
    if not learnings:
        return

    cortex_dir = os.path.join(REPO_ROOT, "knowledge", "cortex")
    os.makedirs(cortex_dir, exist_ok=True)

    filepath = os.path.join(cortex_dir, "learnings.md")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry = f"\n## {timestamp}\n" + "\n".join(learnings) + "\n"

    with open(filepath, "a") as f:
        f.write(entry)

    print(f"Wrote {len(learnings)} learnings to {filepath}")


def main() -> list[str]:
    learnings: list[str] = []
    learnings.extend(mine_decision_journal())
    learnings.extend(mine_trading_outcomes())
    learnings.extend(mine_jobs())
    write_learnings(learnings)
    return learnings


if __name__ == "__main__":
    results = main()
    for r in results:
        print(r)
    if not results:
        print("No learnings to extract (DBs empty or missing).")
