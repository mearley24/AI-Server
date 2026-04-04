# Finish Line — Close Every Remaining Gap

## Status Summary
Cross-checked the handoff doc, status doc, final-wiring-gaps, and actual repo files. Here's the truth:

### Done and Real (code exists, wired, should work in prod)
- Follow-up tracker wired in orchestrator tick
- Payment tracker wired in orchestrator tick
- D-Tools auto-create jobs for Won/On Hold with duplicate check
- Daily briefing `_find_email_db()` path fallback
- Redis persistence via `redis/redis.conf`
- Orchestrator Redis event emissions (email, calendar, jobs, health, briefing)
- Outcome listener started in `main.py`
- Auto-responder behind `AUTO_RESPONDER_ENABLED` flag
- Mission Control: digest markdown (marked.js), sidebar, date guards
- D-Tools Bridge health endpoint fixed (liveness only, `/snapshot` for deep check)
- Smoke test script exists (`scripts/smoke-test.sh`)
- Ship script exists (`scripts/symphony-ship.sh`)
- Approval bridge + iMessage YES/NO/EDIT handling
- Backup script exists (`scripts/backup-data.sh`)
- Decision journal, confidence, pattern engine, cost tracker, intelligence routes

### NOT Done — Files Referenced in AGENTS.md But Don't Exist
These are referenced in documentation but the actual files are missing:

| Missing File | Referenced In | What It Should Do |
|---|---|---|
| `orchestrator/continuous_learning.py` | LEARNER_ROADMAP.md | Mine Cursor transcripts → update AGENTS.md |
| `orchestrator/task_board.py` | AGENTS.md | CLI task queue for agents |
| `orchestrator/WORK_IN_PROGRESS.md` | AGENTS.md | Track current work state |
| `knowledge/agents/ULTRA_RUNBOOK.md` | AGENTS.md | Session start/handoff protocol |
| `setup/nodes/configure_bob_always_on.sh` | AGENTS.md | Prevent sleep, disable auto-update |
| `setup/nodes/BOB_24_7_RUNBOOK.md` | AGENTS.md | Always-on operational docs |
| `.cursor/prompts/close-the-loop-part2.md` | AGENTS.md | Part 2 possibles |
| `tools/bob_export_dtools.py` | PROPOSAL_DTOOLS_NEXT.md | D-Tools export with C4 fallback |
| `knowledge/cortex/` (empty) | LEARNER_ROADMAP.md | Growing knowledge base |
| `tools/bob_maintenance.py` | AGENTS.md | Weekly cleanup script |

### Partially Done — Needs Verification on Host
These need a live smoke test on Bob:
- Does the orchestrator actually tick every 5 min without crashing?
- Do follow-ups and payments DBs populate?
- Does D-Tools sync actually create jobs (or does the API return different status strings)?
- Does Redis `events:log` have entries?
- Does the backup cron run?
- Is `AUTO_RESPONDER_ENABLED` set in `.env`?

---

## TASK: Build Everything That's Missing

### 1. Continuous Learning Script (P0)

Create `openclaw/continuous_learning.py` (~150 lines):

```python
"""
Continuous learner — mines Cursor agent transcripts and operational logs 
to update AGENTS.md and knowledge/cortex/ with new facts.

Run on schedule (launchd) or manually:
  python3 openclaw/continuous_learning.py

Sources:
  1. Cursor transcripts at ~/.cursor/.../agent-transcripts/ (if accessible)
  2. Decision journal — extract patterns from scored outcomes
  3. Email classifications — learn client preferences
  4. Trading outcomes — learn which categories/strategies work
  
Output:
  - Append new learnings to knowledge/cortex/learnings.md
  - Update AGENTS.md "What I Know" section (if section exists)
  - Log what was learned to events:system / knowledge.learned
"""
import os, json, sqlite3, time
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
REPO_ROOT = os.environ.get("SYMPHONY_ROOT", "/Users/bob/AI-Server")

def mine_decision_journal():
    """Extract patterns from recent decisions with outcomes."""
    db_path = os.path.join(DATA_DIR, "decision_journal.db")
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    # Get decisions from last 7 days with outcomes
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT category, action, outcome, outcome_score FROM decisions "
        "WHERE outcome IS NOT NULL AND timestamp > ? ORDER BY timestamp DESC LIMIT 50",
        (cutoff,)
    ).fetchall()
    conn.close()
    
    learnings = []
    # Group by category, compute win rates
    from collections import Counter, defaultdict
    cat_scores = defaultdict(list)
    for cat, action, outcome, score in rows:
        cat_scores[cat].append(score)
    
    for cat, scores in cat_scores.items():
        avg = sum(scores) / len(scores) if scores else 0
        learnings.append(f"- {cat}: {len(scores)} decisions, avg score {avg:.2f}")
    
    return learnings

def mine_trading_outcomes():
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
        pass
    return []

def write_learnings(learnings: list):
    """Append learnings to cortex and log."""
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

def main():
    learnings = []
    learnings.extend(mine_decision_journal())
    learnings.extend(mine_trading_outcomes())
    write_learnings(learnings)
    return learnings

if __name__ == "__main__":
    results = main()
    for r in results:
        print(r)
```

### 2. Task Board (P1)

Create `openclaw/task_board.py` (~100 lines):

```python
"""
Task board — simple SQLite queue for agent tasks.

Usage:
  python3 openclaw/task_board.py add "Fix VPN routing" --type ops --priority high
  python3 openclaw/task_board.py list
  python3 openclaw/task_board.py complete 3
"""
import sqlite3, os, argparse
from datetime import datetime

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "data"), "task_board.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT DEFAULT 'general',
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
    """)
    conn.commit()
    return conn

def add_task(title, task_type="general", priority="medium"):
    conn = init_db()
    conn.execute("INSERT INTO tasks (title, type, priority) VALUES (?, ?, ?)",
                 (title, task_type, priority))
    conn.commit()
    print(f"Added: {title} [{task_type}, {priority}]")

def list_tasks(status="pending"):
    conn = init_db()
    rows = conn.execute(
        "SELECT id, title, type, priority, created_at FROM tasks WHERE status = ? ORDER BY "
        "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at",
        (status,)
    ).fetchall()
    if not rows:
        print(f"No {status} tasks.")
        return
    for r in rows:
        print(f"  [{r[0]}] {r[3].upper():6s} {r[2]:10s} {r[1]}")

def complete_task(task_id):
    conn = init_db()
    conn.execute("UPDATE tasks SET status = 'complete', completed_at = ? WHERE id = ?",
                 (datetime.now().isoformat(), task_id))
    conn.commit()
    print(f"Completed task {task_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    
    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--type", default="general")
    a.add_argument("--priority", default="medium", choices=["high", "medium", "low"])
    
    sub.add_parser("list")
    
    c = sub.add_parser("complete")
    c.add_argument("id", type=int)
    
    args = parser.parse_args()
    if args.cmd == "add":
        add_task(args.title, args.type, args.priority)
    elif args.cmd == "list":
        list_tasks()
    elif args.cmd == "complete":
        complete_task(args.id)
    else:
        parser.print_help()
```

### 3. Always-On Script (P1)

Create `setup/nodes/configure_bob_always_on.sh`:
```bash
#!/bin/bash
echo "Configuring Bob for 24/7 operation..."

sudo pmset -c sleep 0
sudo pmset -c disksleep 0
sudo pmset -c displaysleep 15
sudo pmset -c womp 1
sudo pmset -c autorestart 1

echo "Power settings:"
pmset -g custom | grep -E "sleep|wake|restart"

echo ""
echo "Manual checks needed:"
echo "  1. System Settings → Screen Time → OFF"
echo "  2. System Settings → General → Software Update → Automatic Updates OFF"
echo "  3. System Settings → Focus → No scheduled focus modes"
echo ""
echo "Done. Bob will stay awake when plugged in."
```

Create `setup/nodes/BOB_24_7_RUNBOOK.md`:
```markdown
# Bob 24/7 Always-On Runbook

## Setup
Run once: `./setup/nodes/configure_bob_always_on.sh`

## Manual Checks
- Screen Time: OFF
- Software Update: Manual only (no auto-restart)
- Focus/DND: No schedules
- Energy Saver: Never sleep when plugged in

## Monitoring
- VPN guard: every 5 min via launchd
- Smoke test: weekly via launchd
- Backup: nightly via crontab

## Recovery
If Bob restarts (power outage, update):
1. Docker Desktop auto-starts
2. `docker compose up -d` (add to Login Items if not set)
3. `launchctl load ~/Library/LaunchAgents/com.symphony.*.plist`
4. Verify: `./scripts/smoke-test.sh`
```

### 4. Knowledge Cortex Seed (P1)

Create `knowledge/cortex/learnings.md`:
```markdown
# Symphony Cortex — Learnings

Automatically updated by `openclaw/continuous_learning.py`.

## 2026-04-04
- System initialized with 16 Docker services
- D-Tools sync scanning 100 opportunities
- Weather trading is top category by win rate
- Steve Topletz is most active client (84 Aspen Meadow, $63K project)
- Control4 + Samsung + Episode + Araknis is the standard stack
```

### 5. Bob Maintenance Script (P1)

Create `tools/bob_maintenance.py` (~80 lines):
```python
"""
Bob maintenance — clean up Docker artifacts, old logs, temp files.

Usage:
  python3 tools/bob_maintenance.py --dry    # Preview
  python3 tools/bob_maintenance.py           # Execute
"""
import subprocess, os, argparse, shutil
from pathlib import Path

def get_docker_disk():
    result = subprocess.run(["docker", "system", "df"], capture_output=True, text=True)
    return result.stdout

def prune_docker(dry=False):
    if dry:
        print("[DRY] Would run: docker system prune -f --filter 'until=72h'")
        return
    subprocess.run(["docker", "system", "prune", "-f", "--filter", "until=72h"])

def clean_logs(dry=False):
    log_dirs = ["/tmp/briefing.log", "/tmp/vpn-guard.log", "/tmp/backup-data.log",
                "/tmp/bob-workspace.log", "/tmp/symphony-smoke-test.log"]
    for log in log_dirs:
        if os.path.exists(log):
            size = os.path.getsize(log)
            if size > 10 * 1024 * 1024:  # > 10MB
                if dry:
                    print(f"[DRY] Would truncate {log} ({size // 1024}KB)")
                else:
                    with open(log, "w") as f:
                        f.write(f"--- Truncated by maintenance at {__import__('datetime').datetime.now()} ---\n")

def clean_backups(dry=False):
    backup_dir = os.path.expanduser("~/AI-Server/backups")
    if os.path.exists(backup_dir):
        dirs = sorted(Path(backup_dir).iterdir())
        if len(dirs) > 7:
            for d in dirs[:-7]:
                if dry:
                    print(f"[DRY] Would remove old backup: {d}")
                else:
                    shutil.rmtree(d)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    
    print("=== Docker Disk Usage ===")
    print(get_docker_disk())
    print("\n=== Pruning Docker ===")
    prune_docker(args.dry)
    print("\n=== Cleaning Logs ===")
    clean_logs(args.dry)
    print("\n=== Cleaning Backups ===")
    clean_backups(args.dry)
    print("\nDone." + (" (dry run)" if args.dry else ""))
```

### 6. D-Tools Export Tool (P2)

Create `tools/bob_export_dtools.py` (~60 lines):
```python
"""
Export D-Tools project data for SOW/proposal generation.
Defaults ambiguous categories to Control4 ecosystem.
"""
import os, httpx

DTOOLS_BASE = os.environ.get("DTOOLS_API_URL", "http://dtools-bridge:5050")

async def export_project(project_id: str) -> dict:
    """Fetch full project data from D-Tools bridge."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{DTOOLS_BASE}/projects/{project_id}")
        if resp.status_code != 200:
            return {"error": f"D-Tools returned {resp.status_code}"}
        project = resp.json()
    
    # Apply Control4 fallback for ambiguous items
    for item in project.get("items", []):
        if not item.get("manufacturer") or item["manufacturer"].lower() in ("generic", "unknown", "tbd"):
            item["manufacturer"] = "Control4"
            item["_fallback_applied"] = True
    
    return project

async def search_before_create(client_name: str, project_name: str) -> dict:
    """Search D-Tools for existing client/project to avoid duplicates."""
    async with httpx.AsyncClient(timeout=15) as client:
        clients = await client.get(f"{DTOOLS_BASE}/clients", params={"search": client_name})
        projects = await client.get(f"{DTOOLS_BASE}/projects", params={"search": project_name})
    return {
        "matching_clients": clients.json() if clients.status_code == 200 else [],
        "matching_projects": projects.json() if projects.status_code == 200 else [],
    }
```

### 7. Wire Continuous Learning into Orchestrator (P1)

Edit `openclaw/orchestrator.py` — add a weekly learning run alongside the pattern engine:

```python
async def run_weekly_learning(self):
    """Run continuous learning (same schedule as pattern engine — Sunday morning MT)."""
    try:
        from continuous_learning import main as learn
        learnings = learn()
        if learnings:
            await self._publish("events:knowledge", {
                "type": "knowledge.learned",
                "employee": "beatrice",
                "title": f"Learned {len(learnings)} new patterns",
                "data": {"learnings": learnings}
            })
    except Exception as e:
        logger.warning("Weekly learning failed: %s", e)
```

Add to the Sunday morning check alongside pattern engine.

### 8. Create Launchd Plist for Learning (P2)

Create `setup/launchd/com.symphony.learning.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.learning</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3</string>
        <string>/Users/bob/AI-Server/openclaw/continuous_learning.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>5</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/symphony-learning.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/symphony-learning.log</string>
</dict>
</plist>
```

---

## Verification

After building everything:
```bash
python3 openclaw/task_board.py add "Test task board" --priority high
python3 openclaw/task_board.py list
python3 openclaw/continuous_learning.py
cat knowledge/cortex/learnings.md
python3 tools/bob_maintenance.py --dry
bash setup/nodes/configure_bob_always_on.sh
ls setup/nodes/BOB_24_7_RUNBOOK.md
```

Then rebuild OpenClaw to pick up the learning wiring:
```bash
docker compose build --no-cache openclaw && docker compose up -d openclaw
sleep 30
docker logs openclaw 2>&1 | grep "learning\|knowledge\|cortex" | tail -5
```
