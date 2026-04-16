#!/usr/bin/env python3
"""Throttle non-critical launch agents during business hours."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime


NONCRITICAL_LABELS = [
    "com.symphony.learning",
    "com.symphony.learner-light",
    "com.symphony.trading-provider-slo-monitor",
    "com.symphony.trading-research-bot-hourly",
    "com.symphony.trading-research-daily-digest",
    "com.symphony.trading-research-quality-weekly",
    "com.symphony.trading-pnl-attribution-daily",
    "com.symphony.trading-topic-graph-daily",
    "com.symphony.signal-action-hourly",
    "com.symphony.decision-hygiene-hourly",
    "com.symphony.graph-drift-watcher-daily",
    "com.symphony.quality-gate-nightly",
    "com.symphony.efficiency",
    "com.symphony.focus-ops-monitor",
    "com.symphony.multi-machine-sync-monitor",
    "com.symphony.failure-replay-queue",
    "com.symphony.subscription-audit",
    "com.symphony.polymarket-scan",
    "com.symphony.x-drip",
    "com.symphony.x-mention-replier",
]

CRITICAL_LABELS = [
    "com.symphony.mobile-api",
    "com.symphony.trading-api",
    "com.symphony.markup-app",
    "com.symphony.notes-watcher",
    "com.symphony.incoming-tasks",
    "com.symphony.employee-beatrice-bot",
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def bootout(uid: str, label: str) -> None:
    run(["launchctl", "bootout", f"gui/{uid}", label])


def kickstart(uid: str, label: str) -> None:
    run(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"])


def in_business_hours(now: datetime) -> bool:
    # Weekdays 7:00-18:59 local time
    return now.weekday() < 5 and 7 <= now.hour < 19


def main() -> None:
    uid = str(os.getuid())
    now = datetime.now()
    business = in_business_hours(now)

    if business:
        for label in NONCRITICAL_LABELS:
            bootout(uid, label)
    else:
        for label in NONCRITICAL_LABELS:
            kickstart(uid, label)

    # Always enforce critical services.
    for label in CRITICAL_LABELS:
        kickstart(uid, label)


if __name__ == "__main__":
    main()
