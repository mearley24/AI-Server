"""
emergency_handler.py — Symphony Smart Homes Voice Receptionist
Emergency call detection and escalation for Bob the Conductor.

Handles:
  - Real-time emergency keyword detection during a call
  - Severity scoring (P1 / P2 / P3)
  - Immediate SMS alert to owner
  - Telegram push notification
  - Emergency call log entry
  - Cool-down / dedup logic (don't spam the owner)
  - After-hours emergency override
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

OWNER_CELL        = os.getenv("OWNER_CELL_NUMBER", "+13035559999")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
TWILIO_FROM       = os.getenv("TWILIO_PHONE_NUMBER", "")

# Cool-down: don't send more than 1 owner alert per N seconds per caller
ALERT_COOLDOWN_SECONDS = int(os.getenv("EMERGENCY_COOLDOWN_SECONDS", "300"))  # 5 min


# ─── Emergency Classification ────────────────────────────────────────────────────

# P1: Life/safety or total system failure — alert owner immediately
P1_KEYWORDS = [
    "fire", "smoke", "flood", "water leak", "carbon monoxide", "co alarm",
    "intruder", "break-in", "break in", "someone broke in",
    "alarm going off", "alarm won't stop", "alarm triggered",
    "no power", "power is out", "power outage",
    "911", "call 911", "emergency services",
    "help me", "i need help now", "this is an emergency",
]

# P2: Major functional failure — alert owner, but less urgently
P2_KEYWORDS = [
    "security system down", "cameras offline", "cameras not working",
    "locks not working", "door won't lock", "garage won't open",
    "no internet", "internet is down", "network is down",
    "heat is out", "ac is out", "hvac not working", "thermostat broken",
    "nothing works", "whole system is down", "everything is down",
]

# P3: Significant issue but not immediately dangerous
P3_KEYWORDS = [
    "not working", "broken", "offline", "down", "stopped working",
    "won't turn on", "won't turn off", "stuck", "frozen",
    "app not responding", "remote not working",
]


@dataclass
class EmergencyEvent:
    """
    Represents a detected emergency situation during a call.
    """
    call_sid: str
    phone_number: str
    caller_name: str
    severity: str           # P1 | P2 | P3
    trigger_phrase: str     # The exact phrase that triggered detection
    full_transcript: str    # Transcript text at time of detection
    detected_at: str        # ISO8601
    alert_sent: bool = False
    alert_channel: str = ""  # sms | telegram | both | none
    owner_notified: bool = False
    id: Optional[int] = field(default=None, compare=False)


# ─── Emergency Detector ─────────────────────────────────────────────────────────

class EmergencyDetector:
    """
    Real-time emergency keyword scanner for call transcripts.

    Called incrementally as the OpenAI Realtime stream produces transcript
    text. Designed to fire as early as possible — before the caller finishes
    their sentence if a P1 keyword is present.
    """

    def __init__(self):
        self._seen_p1: set[str] = set()
        self._seen_p2: set[str] = set()
        self._seen_p3: set[str] = set()

    def scan(
        self,
        text: str,
        already_seen: set[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Scan a text chunk for emergency keywords.

        Args:
            text:         Raw transcript text to scan.
            already_seen: Set of already-reported keywords (to avoid re-firing).

        Returns:
            (severity, trigger_phrase) or (None, None) if no emergency found.
            severity is 'P1', 'P2', or 'P3'.
        """
        seen = already_seen or set()
        lower = text.lower()

        for phrase in P1_KEYWORDS:
            if phrase in lower and phrase not in seen:
                return "P1", phrase

        for phrase in P2_KEYWORDS:
            if phrase in lower and phrase not in seen:
                return "P2", phrase

        for phrase in P3_KEYWORDS:
            if phrase in lower and phrase not in seen:
                return "P3", phrase

        return None, None

    def score(
        self,
        text: str,
    ) -> dict:
        """
        Return a full scoring dict with all matched keywords by severity.
        """
        lower = text.lower()
        return {
            "P1": [kw for kw in P1_KEYWORDS if kw in lower],
            "P2": [kw for kw in P2_KEYWORDS if kw in lower],
            "P3": [kw for kw in P3_KEYWORDS if kw in lower],
        }


# ─── Alert Dispatcher ────────────────────────────────────────────────────────────

class AlertDispatcher:
    """
    Sends emergency alerts to the owner via SMS and/or Telegram.
    Implements cool-down logic to prevent alert spam.
    """

    def __init__(self):
        # Track last alert time per caller number
        self._last_alert: dict[str, float] = {}

    def _is_cooled_down(self, phone_number: str) -> bool:
        """Return True if enough time has passed since the last alert for this caller."""
        last = self._last_alert.get(phone_number, 0)
        return (time.time() - last) >= ALERT_COOLDOWN_SECONDS

    def _mark_alerted(self, phone_number: str) -> None:
        self._last_alert[phone_number] = time.time()

    def send_sms_alert(
        self,
        event: EmergencyEvent,
    ) -> bool:
        """
        Send an emergency SMS to the owner via Twilio.
        Returns True on success.
        """
        if not self._is_cooled_down(event.phone_number):
            logger.info(f"Emergency SMS skipped (cool-down): {event.phone_number}")
            return False

        try:
            from twilio.rest import Client
            client = Client(
                os.getenv("TWILIO_ACCOUNT_SID"),
                os.getenv("TWILIO_AUTH_TOKEN"),
            )
            name_display = event.caller_name or event.phone_number
            severity_emoji = {
                "P1": "🚨",
                "P2": "⚠️",
                "P3": "🟡",
            }.get(event.severity, "⚠️")

            body = (
                f"{severity_emoji} SYMPHONY {event.severity} EMERGENCY\n"
                f"From: {name_display} ({event.phone_number})\n"
                f"Trigger: \"{event.trigger_phrase}\"\n"
                f"At: {event.detected_at[:16]}Z\n"
                f"SID: {event.call_sid[-6:]}"
            )

            client.messages.create(
                to=OWNER_CELL,
                from_=TWILIO_FROM,
                body=body,
            )
            self._mark_alerted(event.phone_number)
            logger.info(f"Emergency SMS sent for {event.phone_number} ({event.severity})")
            return True

        except Exception as e:
            logger.error(f"Failed to send emergency SMS: {e}")
            return False

    def send_telegram_alert(
        self,
        event: EmergencyEvent,
    ) -> bool:
        """
        Send an emergency Telegram message to the owner.
        Returns True on success.
        """
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.debug("Telegram not configured — skipping Telegram alert")
            return False

        try:
            import urllib.request
            import urllib.parse

            name_display = event.caller_name or event.phone_number
            severity_emoji = {"P1": "🚨", "P2": "⚠️", "P3": "🟡"}.get(event.severity, "⚠️")

            text = (
                f"{severity_emoji} *{event.severity} EMERGENCY — Symphony*\n"
                f"From: {name_display} (`{event.phone_number}`)\n"
                f"Trigger: _{event.trigger_phrase}_\n"
                f"Time: {event.detected_at[:16]}Z\n"
                f"Call SID: `{event.call_sid}`"
            )

            params = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            })
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?{params}"
            urllib.request.urlopen(url, timeout=5)

            logger.info(f"Emergency Telegram sent for {event.phone_number} ({event.severity})")
            return True

        except Exception as e:
            logger.error(f"Failed to send emergency Telegram: {e}")
            return False

    def dispatch(
        self,
        event: EmergencyEvent,
        channels: str = "both",
    ) -> dict:
        """
        Dispatch an emergency alert over specified channels.

        Args:
            channels: 'sms' | 'telegram' | 'both'

        Returns:
            dict with 'sms_sent' and 'telegram_sent' booleans.
        """
        sms_sent = False
        telegram_sent = False

        if channels in ("sms", "both"):
            sms_sent = self.send_sms_alert(event)

        if channels in ("telegram", "both"):
            telegram_sent = self.send_telegram_alert(event)

        return {
            "sms_sent": sms_sent,
            "telegram_sent": telegram_sent,
            "any_sent": sms_sent or telegram_sent,
        }


# ─── Emergency Handler (Main Controller) ────────────────────────────────────────

class EmergencyHandler:
    """
    Main controller for emergency call handling.

    Integrates detection, alerting, and call logging into a single
    call-level object. One instance per active call.
    """

    def __init__(
        self,
        call_sid: str,
        phone_number: str,
        caller_name: str = "",
        alert_channels: str = "both",
    ):
        self.call_sid = call_sid
        self.phone_number = phone_number
        self.caller_name = caller_name
        self.alert_channels = alert_channels

        self._detector = EmergencyDetector()
        self._dispatcher = AlertDispatcher()
        self._seen_keywords: set[str] = set()
        self._triggered = False
        self._events: list[EmergencyEvent] = []

    def process_transcript_chunk(
        self,
        text: str,
    ) -> Optional[EmergencyEvent]:
        """
        Process a new chunk of transcript text.

        Call this incrementally as the OpenAI Realtime stream produces text.
        Returns an EmergencyEvent if an emergency is detected, else None.

        Only fires once per call per severity level (dedup).
        """
        severity, phrase = self._detector.scan(text, self._seen_keywords)

        if severity is None:
            return None

        # Deduplicate — don't fire again for the same keyword
        self._seen_keywords.add(phrase)

        # Build event
        event = EmergencyEvent(
            call_sid=self.call_sid,
            phone_number=self.phone_number,
            caller_name=self.caller_name,
            severity=severity,
            trigger_phrase=phrase,
            full_transcript=text,
            detected_at=datetime.utcnow().isoformat() + "Z",
        )

        # Dispatch alerts
        dispatch_result = self._dispatcher.dispatch(event, self.alert_channels)
        event.alert_sent = dispatch_result["any_sent"]
        event.alert_channel = (
            "both" if dispatch_result["sms_sent"] and dispatch_result["telegram_sent"]
            else "sms" if dispatch_result["sms_sent"]
            else "telegram" if dispatch_result["telegram_sent"]
            else "none"
        )
        event.owner_notified = event.alert_sent

        self._triggered = True
        self._events.append(event)

        logger.warning(
            f"EMERGENCY DETECTED: {severity} | \"{phrase}\" | "
            f"{self.phone_number} | alert={event.alert_channel}"
        )

        return event

    def get_all_events(self) -> list[EmergencyEvent]:
        """Return all emergency events detected during this call."""
        return list(self._events)

    def was_triggered(self) -> bool:
        """Return True if any emergency was detected during this call."""
        return self._triggered

    def get_highest_severity(self) -> Optional[str]:
        """
        Return the highest severity level encountered during this call.
        P1 > P2 > P3 > None
        """
        priority = {"P1": 1, "P2": 2, "P3": 3}
        if not self._events:
            return None
        return min(
            self._events,
            key=lambda e: priority.get(e.severity, 99)
        ).severity

    def build_call_summary(
        self,
        full_transcript: str = "",
    ) -> dict:
        """
        Build a summary dict for logging to caller_memory after the call ends.
        """
        if not self._events:
            return {}

        return {
            "emergency_detected": True,
            "highest_severity": self.get_highest_severity(),
            "trigger_phrases": [e.trigger_phrase for e in self._events],
            "alert_channels_used": [e.alert_channel for e in self._events],
            "owner_notified": any(e.owner_notified for e in self._events),
            "event_count": len(self._events),
        }

    def reset(self) -> None:
        """
        Reset the handler for a new call segment.
        Call this if you reuse the handler object.
        Note: Does not clear _seen_keywords — those persist per call to avoid re-firing.
        Resets only the _triggered flag so new emergencies in the same call are caught."""
        self._triggered = False


# ─── Convenience Functions ─────────────────────────────────────────────────────────

def detect_intent(text: str) -> str:
    """
    Quick utility: return 'emergency' if P1/P2 keywords detected, else empty string.
    For use by call_routing.py import.
    """
    detector = EmergencyDetector()
    severity, _ = detector.scan(text)
    if severity in ("P1", "P2"):
        return "emergency"
    return ""


def score_emergency(text: str) -> dict:
    """
    Return a full emergency score for the given text.
    For use by call_routing.py import.
    """
    return EmergencyDetector().score(text)


def send_owner_emergency_text(
    caller_number: str,
    caller_name: str,
    trigger_phrase: str,
    call_sid: str = "manual",
    severity: str = "P2",
) -> bool:
    """
    Send a one-off emergency SMS to the owner.
    Used when Bob decides to escalate based on conversation context.
    Returns True on success.
    """
    dispatcher = AlertDispatcher()
    event = EmergencyEvent(
        call_sid=call_sid,
        phone_number=caller_number,
        caller_name=caller_name,
        severity=severity,
        trigger_phrase=trigger_phrase,
        full_transcript="",
        detected_at=datetime.utcnow().isoformat() + "Z",
    )
    result = dispatcher.dispatch(event, channels="both")
    return result["any_sent"]
