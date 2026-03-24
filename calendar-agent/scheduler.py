"""Scheduling logic: find free slots, suggest times, check conflicts."""

from datetime import datetime, timedelta, time
from typing import Optional


BUSINESS_START = time(8, 0)
BUSINESS_END = time(18, 0)


def parse_event_times(event: dict) -> tuple[Optional[datetime], Optional[datetime]]:
    """Extract start/end datetimes from a Zoho event."""
    try:
        start = datetime.fromisoformat(event.get("dateandtime", {}).get("start", ""))
        end = datetime.fromisoformat(event.get("dateandtime", {}).get("end", ""))
        return start, end
    except (ValueError, TypeError, AttributeError):
        return None, None


def find_free_slots(events: list, date_str: str, duration_minutes: int = 60) -> list[dict]:
    """Find available time slots on a given date."""
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    day_start = datetime.combine(target, BUSINESS_START)
    day_end = datetime.combine(target, BUSINESS_END)
    duration = timedelta(minutes=duration_minutes)

    busy = []
    for ev in events:
        s, e = parse_event_times(ev)
        if s and e and s.date() == target:
            busy.append((s, e))
    busy.sort()

    slots = []
    cursor = day_start
    for start, end in busy:
        if cursor + duration <= start:
            slots.append({
                "start": cursor.isoformat(),
                "end": start.isoformat(),
                "duration_minutes": int((start - cursor).total_seconds() / 60),
            })
        cursor = max(cursor, end)

    if cursor + duration <= day_end:
        slots.append({
            "start": cursor.isoformat(),
            "end": day_end.isoformat(),
            "duration_minutes": int((day_end - cursor).total_seconds() / 60),
        })

    return slots
