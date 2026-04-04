#!/usr/bin/env python3
"""
Task board — simple SQLite queue for agent tasks.

Usage:
  python3 openclaw/task_board.py add "Fix VPN routing" --type ops --priority high
  python3 openclaw/task_board.py list
  python3 openclaw/task_board.py complete 3
  python3 openclaw/task_board.py status
"""

import argparse
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "data"), "task_board.db")


def init_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT DEFAULT 'general',
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            worker TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
    """)
    conn.commit()
    return conn


def add_task(title: str, task_type: str = "general", priority: str = "medium") -> None:
    conn = init_db()
    conn.execute(
        "INSERT INTO tasks (title, type, priority) VALUES (?, ?, ?)",
        (title, task_type, priority),
    )
    conn.commit()
    print(f"Added: {title} [{task_type}, {priority}]")


def list_tasks(status: str = "pending") -> None:
    conn = init_db()
    rows = conn.execute(
        "SELECT id, title, type, priority, created_at FROM tasks WHERE status = ? "
        "ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at",
        (status,),
    ).fetchall()
    if not rows:
        print(f"No {status} tasks.")
        return
    for r in rows:
        print(f"  [{r[0]}] {r[3].upper():6s} {r[2]:12s} {r[1]}")


def complete_task(task_id: int, notes: str = "") -> None:
    conn = init_db()
    conn.execute(
        "UPDATE tasks SET status = 'complete', completed_at = ?, notes = ? WHERE id = ?",
        (datetime.now().isoformat(), notes, task_id),
    )
    conn.commit()
    print(f"Completed task {task_id}")


def status() -> None:
    conn = init_db()
    for st in ("pending", "in_progress", "complete"):
        count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = ?", (st,)
        ).fetchone()[0]
        print(f"  {st:12s} {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Symphony task board")
    sub = parser.add_subparsers(dest="cmd")

    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--type", default="general")
    a.add_argument("--priority", default="medium", choices=["high", "medium", "low"])

    sub.add_parser("list")

    c = sub.add_parser("complete")
    c.add_argument("id", type=int)
    c.add_argument("--notes", default="")

    sub.add_parser("status")

    args = parser.parse_args()
    if args.cmd == "add":
        add_task(args.title, args.type, args.priority)
    elif args.cmd == "list":
        list_tasks()
    elif args.cmd == "complete":
        complete_task(args.id, args.notes)
    elif args.cmd == "status":
        status()
    else:
        parser.print_help()
