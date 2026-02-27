#!/usr/bin/env python3
"""
node_health_monitor.py — Symphony Smart Homes AI Network Health Monitor
=======================================================================
Runs on Bob. Checks all registered nodes in parallel and displays a
live dashboard or outputs JSON for scripting.

Usage:
  python3 node_health_monitor.py              # Human-readable dashboard
  python3 node_health_monitor.py --json       # JSON output for scripting
  python3 node_health_monitor.py --watch 30   # Refresh every 30 seconds
  python3 node_health_monitor.py --node maestro  # Check single node
  python3 node_health_monitor.py --alert      # Exit 1 if any node is offline
  python3 node_health_monitor.py --alert --webhook-url https://...  # Slack alert
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_REGISTRY_PATH = Path.home() / ".symphony" / "registry" / "nodes_registry.json"
DEFAULT_TIMEOUT = 5        # seconds per health check
DEFAULT_MAX_WORKERS = 10   # parallel threads for checking nodes
DEFAULT_WATCH_INTERVAL = 30  # seconds between refreshes in --watch mode

# ANSI colors for terminal output
COLOR_GREEN  = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED    = "\033[91m"
COLOR_BLUE   = "\033[94m"
COLOR_RESET  = "\033[0m"
COLOR_BOLD   = "\033[1m"
COLOR_DIM    = "\033[2m"

# ---------------------------------------------------------------------------
# Node status result structure
# ---------------------------------------------------------------------------

class NodeStatus:
    def __init__(self, node_id: str, display_name: str):
        self.node_id      = node_id
        self.display_name = display_name
        self.ping_ok      = False
        self.ping_ms      = None
        self.ollama_ok    = False
        self.ollama_ms    = None
        self.models       = []
        self.docker_ok    = None   # None = not checked (not expected on this node)
        self.registry_ok  = None   # None = not checked
        self.heartbeat_age_s = None  # None = unknown
        self.error        = None
        self.overall      = "unknown"  # online / degraded / offline

    def to_dict(self) -> dict:
        return {
            "node_id":        self.node_id,
            "display_name":   self.display_name,
            "overall":        self.overall,
            "ping_ok":        self.ping_ok,
            "ping_ms":        self.ping_ms,
            "ollama_ok":      self.ollama_ok,
            "ollama_ms":      self.ollama_ms,
            "models":         self.models,
            "docker_ok":      self.docker_ok,
            "registry_ok":    self.registry_ok,
            "heartbeat_age_s": self.heartbeat_age_s,
            "error":          self.error,
        }

# ---------------------------------------------------------------------------
# Low-level check helpers
# ---------------------------------------------------------------------------

def ping_host(host: str, timeout: int = 5) -> tuple[bool, Optional[float]]:
    """Ping a host. Returns (reachable, round_trip_ms)."""
    try:
        t0 = time.monotonic()
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout * 1000), host],
            capture_output=True,
            timeout=timeout + 1,
        )
        ms = (time.monotonic() - t0) * 1000
        return result.returncode == 0, round(ms, 1)
    except Exception:
        return False, None


def check_ollama(host: str, port: int = 11434, timeout: int = 5) -> tuple[bool, Optional[float], list]:
    """Check Ollama API. Returns (ok, response_ms, [model_names])."""
    url = f"http://{host}:{port}/api/tags"
    try:
        t0 = time.monotonic()
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ms = (time.monotonic() - t0) * 1000
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return True, round(ms, 1), models
    except Exception:
        return False, None, []


def check_http_endpoint(url: str, timeout: int = 5) -> tuple[bool, Optional[float]]:
    """Generic HTTP GET check. Returns (ok, response_ms)."""
    try:
        t0 = time.monotonic()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ms = (time.monotonic() - t0) * 1000
            return resp.status < 500, round(ms, 1)
    except Exception:
        return False, None


# ---------------------------------------------------------------------------
# Per-node health check
# ---------------------------------------------------------------------------

def check_node(node: dict, timeout: int = DEFAULT_TIMEOUT) -> NodeStatus:
    """
    Runs all applicable health checks for a single node entry from
    nodes_registry.json.
    """
    node_id = node.get("node_id", "unknown")
    display_name = node.get("display_name", node_id)
    status = NodeStatus(node_id, display_name)

    host = node.get("ip") or node.get("hostname")
    if not host:
        status.error = "No IP or hostname in registry"
        status.overall = "offline"
        return status

    services = node.get("services", {})

    # --- Ping ---
    status.ping_ok, status.ping_ms = ping_host(host, timeout)

    if not status.ping_ok:
        status.overall = "offline"
        status.error = f"Ping failed to {host}"
        return status

    # --- Ollama ---
    if services.get("ollama", False):
        ollama_port = services.get("ollama_port", 11434)
        status.ollama_ok, status.ollama_ms, status.models = check_ollama(
            host, ollama_port, timeout
        )

    # --- Docker registry API (Bob only) ---
    if services.get("registry_api", False):
        registry_port = services.get("registry_api_port", 8765)
        registry_url = f"http://{host}:{registry_port}/api/health"
        status.registry_ok, _ = check_http_endpoint(registry_url, timeout)

    # --- Determine overall status ---
    has_expected_ollama = services.get("ollama", False)
    if has_expected_ollama and not status.ollama_ok:
        status.overall = "degraded"
    else:
        status.overall = "online"

    return status


# ---------------------------------------------------------------------------
# Parallel health check for all nodes
# ---------------------------------------------------------------------------

def check_all_nodes(
    nodes: list,
    filter_node_id: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[NodeStatus]:
    """Check all nodes in parallel. Returns list of NodeStatus."""
    if filter_node_id:
        nodes = [n for n in nodes if n.get("node_id") == filter_node_id]
        if not nodes:
            print(f"Error: no node with id '{filter_node_id}' found in registry.")
            sys.exit(1)

    results = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(nodes))) as executor:
        future_map = {executor.submit(check_node, node, timeout): node for node in nodes}
        for future in as_completed(future_map):
            results.append(future.result())

    # Sort by node_id for stable output
    results.sort(key=lambda s: s.node_id)
    return results


# ---------------------------------------------------------------------------
# Dashboard renderer
# ---------------------------------------------------------------------------

def status_symbol(ok: Optional[bool]) -> str:
    if ok is True:  return f"{COLOR_GREEN}✓{COLOR_RESET}"
    if ok is False: return f"{COLOR_RED}✗{COLOR_RESET}"
    return f"{COLOR_DIM}−{COLOR_RESET}"  # not checked


def overall_badge(status: str) -> str:
    if status == "online":   return f"{COLOR_GREEN}{COLOR_BOLD}ONLINE  {COLOR_RESET}"
    if status == "degraded": return f"{COLOR_YELLOW}{COLOR_BOLD}DEGRADED{COLOR_RESET}"
    return                          f"{COLOR_RED}{COLOR_BOLD}OFFLINE {COLOR_RESET}"


def render_dashboard(results: list[NodeStatus], registry_meta: dict) -> str:
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    online  = sum(1 for r in results if r.overall == "online")
    degraded = sum(1 for r in results if r.overall == "degraded")
    offline = sum(1 for r in results if r.overall == "offline")

    lines.append(f"")
    lines.append(f"{COLOR_BOLD}{'='*72}{COLOR_RESET}")
    lines.append(f"{COLOR_BOLD}  SYMPHONY NODE HEALTH MONITOR{COLOR_RESET}")
    lines.append(f"  {now}")
    lines.append(f"  Nodes: {COLOR_GREEN}{online} online{COLOR_RESET}  "
                 f"{COLOR_YELLOW}{degraded} degraded{COLOR_RESET}  "
                 f"{COLOR_RED}{offline} offline{COLOR_RESET}")
    lines.append(f"{COLOR_BOLD}{'='*72}{COLOR_RESET}")

    for r in results:
        lines.append("")
        lines.append(f"  {overall_badge(r.overall)}  {COLOR_BOLD}{r.display_name}{COLOR_RESET}  "
                     f"{COLOR_DIM}[{r.node_id}]{COLOR_RESET}")

        if r.error and r.overall == "offline":
            lines.append(f"    {COLOR_RED}Error: {r.error}{COLOR_RESET}")
            continue

        ping_str = f"{r.ping_ms:.0f}ms" if r.ping_ms is not None else "n/a"
        lines.append(f"    Ping:   {status_symbol(r.ping_ok)}  {ping_str}")

        if r.ollama_ok is not None or r.ollama_ms is not None or r.models:
            ollama_str = f"{r.ollama_ms:.0f}ms" if r.ollama_ms is not None else "n/a"
            lines.append(f"    Ollama: {status_symbol(r.ollama_ok)}  {ollama_str}")
            if r.models:
                model_list = "  ".join(r.models[:6])
                if len(r.models) > 6:
                    model_list += f"  (+{len(r.models)-6} more)"
                lines.append(f"    Models: {COLOR_DIM}{model_list}{COLOR_RESET}")

        if r.registry_ok is not None:
            lines.append(f"    Registry API: {status_symbol(r.registry_ok)}")

    lines.append("")
    lines.append(f"{COLOR_BOLD}{'='*72}{COLOR_RESET}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Slack / webhook alert
# ---------------------------------------------------------------------------

def send_webhook_alert(webhook_url: str, results: list[NodeStatus]) -> None:
    offline  = [r for r in results if r.overall == "offline"]
    degraded = [r for r in results if r.overall == "degraded"]

    if not offline and not degraded:
        return  # nothing to alert

    lines = ["*Symphony Node Alert*"]
    for r in offline:
        lines.append(f":red_circle: *{r.display_name}* is OFFLINE  —  {r.error or 'no response'}")
    for r in degraded:
        lines.append(f":warning: *{r.display_name}* is DEGRADED  —  Ollama not responding")

    payload = json.dumps({"text": "\n".join(lines)}).encode()
    try:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to send webhook alert: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Registry loader
# ---------------------------------------------------------------------------

def load_registry(path: Path) -> tuple[list, dict]:
    """Load nodes_registry.json. Returns (nodes_list, meta_dict)."""
    if not path.exists():
        print(f"Error: registry file not found at {path}", file=sys.stderr)
        print("Run provision_node.sh on Bob first, or specify --registry PATH", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    nodes = data.get("nodes", [])
    meta  = data.get("_meta", {})
    return nodes, meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Symphony node health monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--registry",    default=str(DEFAULT_REGISTRY_PATH),
                        help=f"Path to nodes_registry.json (default: {DEFAULT_REGISTRY_PATH})")
    parser.add_argument("--json",        action="store_true",
                        help="Output JSON instead of human-readable dashboard")
    parser.add_argument("--watch",       type=int, metavar="SECONDS", default=None,
                        help="Refresh every N seconds (like watch mode)")
    parser.add_argument("--node",        metavar="NODE_ID", default=None,
                        help="Check a single node by its node_id")
    parser.add_argument("--alert",       action="store_true",
                        help="Exit with code 1 if any node is offline or degraded")
    parser.add_argument("--webhook-url", metavar="URL", default=None,
                        help="Slack-compatible webhook URL for alerting")
    parser.add_argument("--timeout",     type=int, default=DEFAULT_TIMEOUT,
                        help=f"Per-check timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--workers",     type=int, default=DEFAULT_MAX_WORKERS,
                        help=f"Parallel workers for checking (default: {DEFAULT_MAX_WORKERS})")
    args = parser.parse_args()

    registry_path = Path(args.registry)

    def run_once():
        nodes, meta = load_registry(registry_path)
        results = check_all_nodes(
            nodes,
            filter_node_id=args.node,
            timeout=args.timeout,
            max_workers=args.workers,
        )

        if args.json:
            output = {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "nodes": [r.to_dict() for r in results],
                "summary": {
                    "total":    len(results),
                    "online":   sum(1 for r in results if r.overall == "online"),
                    "degraded": sum(1 for r in results if r.overall == "degraded"),
                    "offline":  sum(1 for r in results if r.overall == "offline"),
                },
            }
            print(json.dumps(output, indent=2))
        else:
            print(render_dashboard(results, meta))

        if args.webhook_url:
            send_webhook_alert(args.webhook_url, results)

        if args.alert:
            bad = [r for r in results if r.overall in ("offline", "degraded")]
            if bad:
                return 1
        return 0

    if args.watch:
        try:
            while True:
                # Clear screen
                print("\033[2J\033[H", end="")
                run_once()
                print(f"\n  {COLOR_DIM}Next refresh in {args.watch}s (Ctrl+C to exit){COLOR_RESET}")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
            sys.exit(0)
    else:
        sys.exit(run_once())


if __name__ == "__main__":
    main()
