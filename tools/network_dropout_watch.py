#!/usr/bin/env python3
"""Continuously monitor LAN/WAN/AV reachability and log dropout events."""

from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

STOP = False


def _handle_signal(signum: int, _frame: Any) -> None:
    global STOP
    STOP = True
    print(f"[watch] received signal={signum}, stopping", flush=True)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def _now() -> str:
    return datetime.now().isoformat()


def ping_once(host: str, timeout_ms: int = 1000) -> Dict[str, Any]:
    cmd = ["ping", "-c", "1", "-W", str(timeout_ms), host]
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(1, timeout_ms // 1000 + 1), check=False)
    except Exception as exc:
        return {
            "host": host,
            "ok": False,
            "latency_ms": None,
            "error": str(exc),
            "duration_ms": round((time.time() - start) * 1000, 2),
        }

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(r"time=([0-9.]+)\s*ms", output)
    latency = float(match.group(1)) if match else None
    return {
        "host": host,
        "ok": proc.returncode == 0,
        "latency_ms": latency,
        "return_code": proc.returncode,
        "duration_ms": round((time.time() - start) * 1000, 2),
    }


def classify(sample: Dict[str, Dict[str, Any]]) -> str:
    gateway_ok = sample.get("gateway", {}).get("ok", False)
    wan_ok = sample.get("wan", {}).get("ok", False)
    c4_ok = sample.get("control4", {}).get("ok", True)
    sonos_ok = sample.get("sonos", {}).get("ok", True)

    if not gateway_ok and not wan_ok:
        return "lan_or_router_down"
    if gateway_ok and not wan_ok:
        return "wan_down"
    if gateway_ok and wan_ok and (not c4_ok or not sonos_ok):
        return "av_path_issue"
    return "healthy"


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def watch(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    status_file = state_dir / "dropout_watch_status.json"
    events_file = state_dir / "dropout_watch_events.jsonl"
    pid_file = state_dir / "dropout_watch.pid"
    pid_file.write_text(str(os_getpid()), encoding="utf-8")

    targets: Dict[str, Optional[str]] = {
        "gateway": args.gateway_ip,
        "wan": args.wan_ip,
        "control4": args.control4_ip,
        "sonos": args.sonos_ip,
    }

    print(f"[watch] started at {_now()} targets={targets}", flush=True)
    previous_health: Optional[str] = None

    try:
        while not STOP:
            sample_targets: Dict[str, Dict[str, Any]] = {}
            for key, host in targets.items():
                if host:
                    sample_targets[key] = ping_once(host, timeout_ms=1000)

            health = classify(sample_targets)
            sample = {
                "timestamp": _now(),
                "health": health,
                "targets": sample_targets,
            }
            write_json(
                status_file,
                {
                    "success": True,
                    "running": True,
                    "pid": os_getpid(),
                    "updated_at": sample["timestamp"],
                    "health": health,
                    "targets": targets,
                    "sample": sample_targets,
                },
            )

            if previous_health is None:
                append_jsonl(events_file, {"timestamp": sample["timestamp"], "event": "watch_started", "health": health, "targets": targets})
            elif previous_health != health:
                append_jsonl(
                    events_file,
                    {
                        "timestamp": sample["timestamp"],
                        "event": "state_change",
                        "from": previous_health,
                        "to": health,
                        "sample": sample_targets,
                    },
                )
                print(f"[watch] state change: {previous_health} -> {health}", flush=True)
            previous_health = health

            time.sleep(max(0.5, float(args.interval_sec)))
    finally:
        write_json(
            status_file,
            {
                "success": True,
                "running": False,
                "pid": os_getpid(),
                "updated_at": _now(),
                "health": previous_health or "unknown",
                "targets": targets,
                "stopped": True,
            },
        )
        append_jsonl(events_file, {"timestamp": _now(), "event": "watch_stopped"})
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        print("[watch] stopped", flush=True)

    return 0


def status(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    status_file = state_dir / "dropout_watch_status.json"
    events_file = state_dir / "dropout_watch_events.jsonl"
    if status_file.exists():
        print(status_file.read_text(encoding="utf-8"))
    else:
        print(json.dumps({"success": True, "running": False, "status": "not_started"}, indent=2))
    if events_file.exists():
        print(f"events_file={events_file}")
    return 0


def os_getpid() -> int:
    import os

    return os.getpid()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Network dropout watcher")
    parser.add_argument("--state-dir", default="data/network_watch", help="Directory for status/events files")
    parser.add_argument("--gateway-ip", default="192.168.1.1")
    parser.add_argument("--wan-ip", default="1.1.1.1")
    parser.add_argument("--control4-ip", default="")
    parser.add_argument("--sonos-ip", default="")
    parser.add_argument("--interval-sec", type=float, default=2.0)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.status:
        return status(args)
    if args.watch:
        return watch(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
