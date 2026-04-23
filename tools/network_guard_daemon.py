#!/usr/bin/env python3
"""
network_guard_daemon.py

Lightweight network anomaly monitor for Symphony operations.

Checks:
- Gateway reachability (ping + packet loss + jitter)
- Optional Control4 controller reachability (ping)

Behavior:
- Sends Telegram alerts only when thresholds are exceeded (cooldown + fingerprint changes)
- Creates/updates a single rolling task-board incident automatically
- Marks the incident resolved when network recovers
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

def sanitize_for_telegram(text: str) -> str:
    return text[:4096]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "data" / "network_guard_state.json"
EVENTS_FILE = BASE_DIR / "data" / "network_guard_events.jsonl"
TASK_DB = BASE_DIR / "orchestrator" / "task_board.db"

INCIDENT_SOURCE = "network_guard"
INCIDENT_SOURCE_ID = "network_guard_primary"

CHECK_COUNT = int(os.environ.get("NETWORK_GUARD_PING_COUNT", "6"))
CHECK_INTERVAL_DEFAULT = int(os.environ.get("NETWORK_GUARD_INTERVAL_SEC", "120"))
ALERT_COOLDOWN_SECONDS = int(os.environ.get("NETWORK_GUARD_ALERT_COOLDOWN_SECONDS", "900"))
CONSECUTIVE_BAD_REQUIRED = int(os.environ.get("NETWORK_GUARD_CONSECUTIVE_BAD_REQUIRED", "2"))

LOSS_WARN_PCT = float(os.environ.get("NETWORK_GUARD_LOSS_WARN_PCT", "5"))
LOSS_CRIT_PCT = float(os.environ.get("NETWORK_GUARD_LOSS_CRIT_PCT", "20"))
JITTER_WARN_MS = float(os.environ.get("NETWORK_GUARD_JITTER_WARN_MS", "25"))
JITTER_CRIT_MS = float(os.environ.get("NETWORK_GUARD_JITTER_CRIT_MS", "60"))
AVG_LATENCY_WARN_MS = float(os.environ.get("NETWORK_GUARD_AVG_LATENCY_WARN_MS", "40"))
AVG_LATENCY_CRIT_MS = float(os.environ.get("NETWORK_GUARD_AVG_LATENCY_CRIT_MS", "120"))

NETWORK_GUARD_GATEWAY = os.environ.get("NETWORK_GUARD_GATEWAY", "192.168.1.1").strip()
NETWORK_GUARD_CONTROL4_HOST = os.environ.get("NETWORK_GUARD_CONTROL4_HOST", "").strip()
NETWORK_GUARD_DNS_TEST_HOST = os.environ.get("NETWORK_GUARD_DNS_TEST_HOST", "google.com").strip()
NETWORK_GUARD_HTTP_TEST_URL = os.environ.get("NETWORK_GUARD_HTTP_TEST_URL", "http://connectivitycheck.gstatic.com/generate_204").strip()


def now_iso() -> str:
    return datetime.now().isoformat()


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_event(event: dict[str, Any]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")


def send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or os.environ.get("TELEGRAM_OWNER_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": sanitize_for_telegram(message)}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def ping_stats(host: str, count: int = CHECK_COUNT) -> dict[str, Any]:
    """
    Parse `ping` output on macOS/Linux variants.
    """
    ping_bin = shutil.which("ping") or ("/sbin/ping" if Path("/sbin/ping").exists() else "/usr/sbin/ping")
    cmd = [ping_bin, "-c", str(max(1, count)), host]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=str(BASE_DIR))
    except Exception as exc:
        return {
            "host": host,
            "reachable": False,
            "packet_loss_pct": 100.0,
            "avg_ms": 9999.0,
            "jitter_ms": 9999.0,
            "raw_error": str(exc),
        }

    text = f"{p.stdout}\n{p.stderr}".strip()
    packet_loss = 100.0
    avg_ms = 9999.0
    jitter_ms = 9999.0

    loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*packet loss", text, re.IGNORECASE)
    if loss_match:
        packet_loss = _safe_float(loss_match.group(1), 100.0)

    # macOS: round-trip min/avg/max/stddev = 15.994/20.959/26.130/3.190 ms
    # Linux: rtt min/avg/max/mdev = 14.180/15.553/18.076/1.442 ms
    rtt_match = re.search(
        r"(?:round-trip|rtt)\s+min/avg/max/(?:stddev|mdev)\s*=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms",
        text,
        re.IGNORECASE,
    )
    if rtt_match:
        avg_ms = _safe_float(rtt_match.group(2), 9999.0)
        jitter_ms = _safe_float(rtt_match.group(4), 9999.0)

    reachable = p.returncode == 0 and packet_loss < 100.0
    return {
        "host": host,
        "reachable": reachable,
        "packet_loss_pct": round(packet_loss, 2),
        "avg_ms": round(avg_ms, 2),
        "jitter_ms": round(jitter_ms, 2),
        "returncode": p.returncode,
    }


def classify_endpoint(endpoint_name: str, stats: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    severity = "healthy"
    loss = float(stats.get("packet_loss_pct", 100.0))
    avg = float(stats.get("avg_ms", 9999.0))
    jitter = float(stats.get("jitter_ms", 9999.0))
    reachable = bool(stats.get("reachable", False))

    if not reachable:
        reasons.append(f"{endpoint_name}:unreachable")
        return "critical", reasons

    if loss >= LOSS_CRIT_PCT:
        reasons.append(f"{endpoint_name}:loss={loss}%")
        severity = "critical"
    elif loss >= LOSS_WARN_PCT:
        reasons.append(f"{endpoint_name}:loss={loss}%")
        severity = "warning"

    if avg >= AVG_LATENCY_CRIT_MS:
        reasons.append(f"{endpoint_name}:avg={avg}ms")
        severity = "critical"
    elif avg >= AVG_LATENCY_WARN_MS and severity != "critical":
        reasons.append(f"{endpoint_name}:avg={avg}ms")
        severity = "warning"

    if jitter >= JITTER_CRIT_MS:
        reasons.append(f"{endpoint_name}:jitter={jitter}ms")
        severity = "critical"
    elif jitter >= JITTER_WARN_MS and severity != "critical":
        reasons.append(f"{endpoint_name}:jitter={jitter}ms")
        severity = "warning"

    return severity, reasons


def dns_resolves(hostname: str) -> dict[str, Any]:
    import socket

    try:
        ip = socket.gethostbyname(hostname)
        return {"host": hostname, "ok": True, "ip": ip}
    except Exception as exc:
        return {"host": hostname, "ok": False, "error": str(exc)}


def http_probe(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return {"url": url, "ok": 200 <= resp.status < 400, "status_code": int(resp.status)}
    except Exception as exc:
        return {"url": url, "ok": False, "error": str(exc)}


def build_snapshot() -> dict[str, Any]:
    endpoints: list[tuple[str, str]] = [("gateway", NETWORK_GUARD_GATEWAY)]
    if NETWORK_GUARD_CONTROL4_HOST:
        endpoints.append(("control4", NETWORK_GUARD_CONTROL4_HOST))

    checks: dict[str, Any] = {}
    worst = "healthy"
    reasons: list[str] = []
    for endpoint_name, host in endpoints:
        stats = ping_stats(host)
        checks[endpoint_name] = stats
        sev, endpoint_reasons = classify_endpoint(endpoint_name, stats)
        reasons.extend(endpoint_reasons)
        if sev == "critical":
            worst = "critical"
        elif sev == "warning" and worst == "healthy":
            worst = "warning"

    dns_check = dns_resolves(NETWORK_GUARD_DNS_TEST_HOST)
    checks["dns"] = dns_check
    if not dns_check.get("ok"):
        reasons.append(f"dns_fail:{NETWORK_GUARD_DNS_TEST_HOST}")
        if worst != "critical":
            worst = "warning"

    web_check = http_probe(NETWORK_GUARD_HTTP_TEST_URL)
    checks["http"] = web_check
    if not web_check.get("ok"):
        reasons.append("http_probe_fail")
        if worst != "critical":
            worst = "warning"

    fingerprint = "healthy" if worst == "healthy" else "|".join(sorted(reasons))
    return {
        "timestamp": now_iso(),
        "status": worst,
        "fingerprint": fingerprint,
        "reasons": reasons,
        "checks": checks,
    }


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(TASK_DB))


def upsert_incident_task(snapshot: dict[str, Any]) -> int | None:
    if not TASK_DB.exists():
        return None
    conn = _conn()
    cur = conn.cursor()
    now = now_iso()
    cur.execute(
        """
        SELECT id FROM tasks
        WHERE source = ? AND source_id = ? AND status IN ('pending', 'in_progress', 'blocked')
        ORDER BY id DESC
        LIMIT 1
        """,
        (INCIDENT_SOURCE, INCIDENT_SOURCE_ID),
    )
    row = cur.fetchone()
    metadata = {
        "status": snapshot["status"],
        "reasons": snapshot["reasons"],
        "checks": snapshot["checks"],
        "fingerprint": snapshot["fingerprint"],
        "last_seen_at": snapshot["timestamp"],
    }
    description = (
        "Network Guard detected instability.\n"
        f"Status: {snapshot['status']}\n"
        f"Reasons: {', '.join(snapshot['reasons']) if snapshot['reasons'] else 'n/a'}\n"
        "Focus: gateway reachability, packet loss, jitter, latency, Control4 host."
    )
    if row:
        task_id = int(row[0])
        cur.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, priority = ?, task_type = 'troubleshooting',
                updated_at = ?, metadata = ?
            WHERE id = ?
            """,
            ("Investigate network instability (Network Guard)", description, "high", now, json.dumps(metadata), task_id),
        )
        cur.execute(
            """
            INSERT INTO task_history (task_id, action, worker, timestamp, notes)
            VALUES (?, 'updated', 'bob', ?, ?)
            """,
            (task_id, now, f"Network Guard update: {snapshot['status']} {snapshot['fingerprint']}"),
        )
    else:
        cur.execute(
            """
            INSERT INTO tasks (title, description, task_type, priority, status, created_at, updated_at, source, source_id, metadata)
            VALUES (?, ?, 'troubleshooting', 'high', 'pending', ?, ?, ?, ?, ?)
            """,
            (
                "Investigate network instability (Network Guard)",
                description,
                now,
                now,
                INCIDENT_SOURCE,
                INCIDENT_SOURCE_ID,
                json.dumps(metadata),
            ),
        )
        task_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO task_history (task_id, action, worker, timestamp, notes)
            VALUES (?, 'created', 'bob', ?, ?)
            """,
            (task_id, now, "Network Guard incident auto-created"),
        )
    conn.commit()
    conn.close()
    return task_id


def resolve_incident_task(snapshot: dict[str, Any]) -> int | None:
    if not TASK_DB.exists():
        return None
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM tasks
        WHERE source = ? AND source_id = ? AND status IN ('pending', 'in_progress', 'blocked')
        ORDER BY id DESC
        LIMIT 1
        """,
        (INCIDENT_SOURCE, INCIDENT_SOURCE_ID),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    task_id = int(row[0])
    now = now_iso()
    cur.execute(
        """
        UPDATE tasks
        SET status = 'completed', completed_at = ?, updated_at = ?, completion_notes = ?
        WHERE id = ?
        """,
        (now, now, f"Network recovered at {snapshot['timestamp']}", task_id),
    )
    cur.execute(
        """
        INSERT INTO task_history (task_id, action, worker, timestamp, notes)
        VALUES (?, 'completed', 'bob', ?, ?)
        """,
        (task_id, now, "Network Guard auto-resolved incident"),
    )
    conn.commit()
    conn.close()
    return task_id


def should_alert(state: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    if snapshot["status"] == "healthy":
        return False
    last_fp = str(state.get("last_alert_fingerprint", ""))
    if snapshot["fingerprint"] != last_fp:
        return True
    last_ts = float(state.get("last_alert_ts", 0))
    return (datetime.now().timestamp() - last_ts) >= ALERT_COOLDOWN_SECONDS


def monitor_once(alert: bool = True) -> dict[str, Any]:
    state = load_state()
    snapshot = build_snapshot()
    previous_status = str(state.get("last_status", "unknown"))

    consecutive_bad = int(state.get("consecutive_bad", 0))
    if snapshot["status"] == "healthy":
        consecutive_bad = 0
    else:
        consecutive_bad += 1

    snapshot["consecutive_bad"] = consecutive_bad
    state["consecutive_bad"] = consecutive_bad

    incident_task_id: int | None = None
    must_open_incident = snapshot["status"] == "critical" or consecutive_bad >= CONSECUTIVE_BAD_REQUIRED
    if snapshot["status"] != "healthy" and must_open_incident:
        incident_task_id = upsert_incident_task(snapshot)
        append_event(
            {
                "timestamp": snapshot["timestamp"],
                "event": "degraded",
                "status": snapshot["status"],
                "fingerprint": snapshot["fingerprint"],
                "reasons": snapshot["reasons"],
                "incident_task_id": incident_task_id,
                "consecutive_bad": consecutive_bad,
            }
        )
        if alert and should_alert(state, snapshot):
            lines = [
                "🚨 Network Guard Alert",
                f"Status: {snapshot['status']}",
                f"Consecutive bad checks: {consecutive_bad}",
                f"Reasons: {', '.join(snapshot['reasons'])}",
            ]
            if incident_task_id:
                lines.append(f"Task board incident: #{incident_task_id}")
            sent = send_telegram("\n".join(lines))
            if sent:
                state["last_alert_ts"] = datetime.now().timestamp()
                state["last_alert_fingerprint"] = snapshot["fingerprint"]

    if snapshot["status"] == "healthy":
        resolved_id = resolve_incident_task(snapshot)
        if previous_status in {"warning", "critical"}:
            append_event(
                {
                    "timestamp": snapshot["timestamp"],
                    "event": "recovered",
                    "status": snapshot["status"],
                    "fingerprint": snapshot["fingerprint"],
                    "resolved_task_id": resolved_id,
                }
            )
        if alert and previous_status in {"warning", "critical"}:
            msg = "✅ Network Guard recovered to healthy."
            if resolved_id:
                msg += f" Closed task #{resolved_id}."
            _ = send_telegram(msg)

    state["last_status"] = snapshot["status"]
    state["last_fingerprint"] = snapshot["fingerprint"]
    state["last_check"] = snapshot["timestamp"]
    save_state(state)
    snapshot["incident_task_id"] = incident_task_id
    return snapshot


def run_daemon(interval_sec: int, alert: bool) -> int:
    while True:
        result = monitor_once(alert=alert)
        print(json.dumps(result, indent=2), flush=True)
        # keep this simple and robust
        import time
        time.sleep(max(20, interval_sec))


def main() -> int:
    if load_dotenv is not None:
        load_dotenv(BASE_DIR / ".env")

    parser = argparse.ArgumentParser(description="Network anomaly monitor for Symphony")
    parser.add_argument("--once", action="store_true", help="Run one check and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_DEFAULT, help="Seconds between checks in daemon mode")
    parser.add_argument("--no-alert", action="store_true", help="Run checks but suppress Telegram alerts")
    args = parser.parse_args()

    if args.daemon:
        return run_daemon(interval_sec=args.interval, alert=not args.no_alert)

    result = monitor_once(alert=not args.no_alert)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
