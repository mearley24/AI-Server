#!/usr/bin/env python3
"""
Bob maintenance — clean Docker artifacts, old logs, and stale backups.

Usage:
  python3 tools/bob_maintenance.py --dry    # Preview
  python3 tools/bob_maintenance.py --run    # Execute
  python3 tools/bob_maintenance.py --run --purge-memory   # Execute + purge inactive RAM
"""

import argparse
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

LOG_FILES = [
    "/tmp/briefing.log",
    "/tmp/vpn-guard.log",
    "/tmp/backup-data.log",
    "/tmp/bob-workspace.log",
    "/tmp/symphony-smoke-test.log",
    "/tmp/symphony-learning.log",
]
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_DIR = os.path.expanduser("~/AI-Server/backups")
KEEP_BACKUPS = 7


def get_docker_disk() -> str:
    result = subprocess.run(["docker", "system", "df"], capture_output=True, text=True)
    return result.stdout


def prune_docker(dry: bool = False) -> None:
    if dry:
        print("[DRY] Would run: docker system prune -f --filter 'until=72h'")
        return
    subprocess.run(["docker", "system", "prune", "-f", "--filter", "until=72h"])


def clean_logs(dry: bool = False) -> None:
    for log in LOG_FILES:
        if os.path.exists(log):
            size = os.path.getsize(log)
            if size > MAX_LOG_BYTES:
                if dry:
                    print(f"[DRY] Would truncate {log} ({size // 1024}KB)")
                else:
                    with open(log, "w") as f:
                        f.write(f"--- Truncated by maintenance at {datetime.now()} ---\n")
                    print(f"Truncated {log}")


def clean_backups(dry: bool = False) -> None:
    if not os.path.exists(BACKUP_DIR):
        return
    dirs = sorted(Path(BACKUP_DIR).iterdir())
    if len(dirs) > KEEP_BACKUPS:
        for d in dirs[:-KEEP_BACKUPS]:
            if dry:
                print(f"[DRY] Would remove old backup: {d}")
            else:
                shutil.rmtree(d, ignore_errors=True)
                print(f"Removed old backup: {d}")


def purge_memory() -> None:
    """macOS: purge inactive RAM."""
    print("Purging inactive memory...")
    subprocess.run(["sudo", "purge"], check=False)


def vacuum_dbs(dry: bool = False) -> None:
    """VACUUM SQLite databases under data/."""
    import sqlite3

    data_dir = os.path.expanduser("~/AI-Server/data")
    if not os.path.isdir(data_dir):
        return
    for db_file in Path(data_dir).rglob("*.db"):
        if dry:
            print(f"[DRY] Would VACUUM {db_file}")
        else:
            try:
                conn = sqlite3.connect(str(db_file))
                conn.execute("VACUUM")
                conn.close()
                print(f"VACUUM {db_file.name}")
            except Exception as e:
                print(f"VACUUM {db_file.name} failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bob maintenance script")
    parser.add_argument("--dry", action="store_true", help="Preview without changes")
    parser.add_argument("--run", action="store_true", help="Execute cleanup")
    parser.add_argument("--purge-memory", action="store_true", help="Also purge inactive RAM")
    args = parser.parse_args()

    dry = not args.run

    print("=== Docker Disk Usage ===")
    print(get_docker_disk())

    print("=== Pruning Docker ===")
    prune_docker(dry)

    print("\n=== Cleaning Logs ===")
    clean_logs(dry)

    print("\n=== Cleaning Backups ===")
    clean_backups(dry)

    print("\n=== VACUUM SQLite DBs ===")
    vacuum_dbs(dry)

    if args.purge_memory and not dry:
        print("\n=== Purging Memory ===")
        purge_memory()

    print(f"\nDone.{' (dry run — use --run to execute)' if dry else ''}")
