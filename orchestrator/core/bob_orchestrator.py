#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE = Path.home() / "AI-Server"
LOG = BASE / "orchestrator/logs/bob_orchestrator.log"

LOG.parent.mkdir(parents=True, exist_ok=True)

ALLOWED_ACTIONS = {
    "scan_raw_projects": str(BASE / "tools/bob_scan_raw_projects.sh"),
    "scan_library": str(BASE / "tools/bob_scan_library.sh"),
    "build_inventory": str(BASE / "tools/RUN_Bob_Build_Inventory.command"),
    "fetch_manuals": str(BASE / "tools/RUN_Bob_Fetch_Manuals.command"),
    "room_mapper": str(BASE / "tools/bob_room_mapper.py"),
    "build_room_packages": str(BASE / "tools/bob_build_room_packages.py"),
}

PIPELINES = {
    "refresh_everything": [
        "scan_raw_projects",
        "scan_library",
        "build_inventory",
        "fetch_manuals",
        "room_mapper",
        "build_room_packages",
    ]
}

def log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a") as f:
        f.write(f"[{ts}] {message}\n")

def execute(action: str):
    if action not in ALLOWED_ACTIONS:
        print(f"Action not allowed: {action}")
        return

    cmd = ALLOWED_ACTIONS[action]
    print(f"Executing: {action}")
    log(f"Executing: {action}")

    if cmd.endswith(".py"):
        subprocess.run(["python", cmd])
    else:
        subprocess.run([cmd])

def run_pipeline(name: str):
    if name not in PIPELINES:
        print("Unknown pipeline.")
        return

    for step in PIPELINES[name]:
        execute(step)

    print("Pipeline complete.")

def main():
    if len(sys.argv) < 2:
        print("Usage: RUN_BOB.command <command> [project_name]")
        print("Available commands:")
        print(" - refresh_everything")
        print(" - analyze_project <project_folder_name>  # Proposal Intelligence + D-Tools CSV")
        print(" - export_dtools <project_folder_name>   # D-Tools CSV only")
        return

    command = sys.argv[1]

    if command == "analyze_project":
        if len(sys.argv) < 3:
            print("Please provide project folder name.")
            return

        project_name = sys.argv[2]
        subprocess.run([
            "python",
            str(BASE / "tools/bob_project_analyzer.py"),
            project_name,
        ])
        subprocess.run([
            "python",
            str(BASE / "tools/bob_proposal_to_dtools.py"),
            project_name,
        ])
        return

    if command == "export_dtools":
        if len(sys.argv) < 3:
            print("Please provide project folder name.")
            return

        project_name = sys.argv[2]
        subprocess.run([
            "python",
            str(BASE / "tools/bob_proposal_to_dtools.py"),
            project_name,
        ])
        return

    if command in PIPELINES:
        run_pipeline(command)
    else:
        execute(command)
