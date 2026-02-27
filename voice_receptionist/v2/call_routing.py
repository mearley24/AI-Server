"""
call_routing.py — Symphony Smart Homes Voice Receptionist
Intelligent call routing engine for Bob the Conductor.

Handles:
  - Caller ID matching (known clients → personalized greeting)
  - Time-of-day routing (business hours vs after-hours)
  - Intent detection (sales, support, emergency, vendor)
  - Script selection and session configuration
  - Escalation logic (when to text the owner)
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional

from call_scripts import SCRIPTS, build_system_prompt

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

TIMEZONE          = ZoneInfo(os.getenv("BUSINESS_TIMEZONE", "America/Denver"))
BUSINESS_OPEN     = dtime(8, 0)    # 8:00 AM
BUSINESS_CLOSE    = dtime(18, 0)   # 6:00 PM
BUSINESS_DAYS     = {0, 1, 2, 3, 4}  # Monday–Friday (weekday() values)

# Intent keyword maps (lowercase keywords → script key)
INTENT_KEYWORDS: dict[str, list[str]] = {
    "emergency": [
        "emergency", "urgent", "broken", "not working", "outage",
        "offline", "down", "alarm", "security", "smoke", "fire",
        "flood", "water", "leak", "power", "dead",
    ],
    "sales_inquiry": [
        "new home", "new construction", "renovation", "remodel",
        "upgrade", "interested", "quote", "proposal", "consultation",
        "how much", "cost", "price", "pricing", "estimate",
        "smart home", "home theater", "automation", "audio", "video",
        "lighting", "shade", "shading", "network", "wifi", "camera",
        "security system", "control4", "lutron", "sonos",
    ],
    "known_client_support": [
        "not working", "broken", "issue", "problem", "help",
        "service", "support", "repair", "fix", "tech", "technician",
        "appointment", "schedule", "maintenance",
    ],
    "vendor_call": [
        "vendor", "supplier", "rep", "sales rep", "account manager",
        "wholesale", "distributor", "partnership", "integrate",
        "demo", "product", "catalog",
    ],
}


# ─── Caller Identity Resolver ─────────────────────────────────────────────────

class CallerResolver:
    """
    Resolves a caller phone number to a known client record.
    In production, this queries the CRM / caller_memory module.
    """

    def __init__(self, crm_lookup_fn=None):
        """
        Args:
            crm_lookup_fn: Optional callable(phone_number: str) -> dict | None
                           Returns client record dict or None if not found.
        """
        self._lookup = crm_lookup_fn

    def resolve(self, phone_number: str) -> Optional[dict]:
        """
        Resolve a phone number to a client record.

        Returns:
            dict with keys: name, systems, last_service, status, notes
            or None if not found.
        """
        if not phone_number:
            return None

        # Normalize phone number
        normalized = self._normalize_phone(phone_number)

        if self._lookup:
            try:
                return self._lookup(normalized)
            except Exception as e:
                logger.warning(f"CRM lookup failed for {normalized}: {e}")
                return None

        # No CRM connected — return None (unknown caller)
        return None

    @staticmethod
    def _normalize_phone(number: str) -> str:
        """Strip all non-digit characters, add +1 prefix if needed."""
        digits = re.sub(r"\D", "", number)
        if len(digits) == 10:
            digits = "1" + digits
        return "+" + digits


# ─── Business Hours Checker ───────────────────────────────────────────────────

class BusinessHoursChecker:
    """Determines if the current time falls within business hours."""

    def __init__(
        self,
        open_time: dtime = BUSINESS_OPEN,
        close_time: dtime = BUSINESS_CLOSE,
        business_days: set = BUSINESS_DAYS,
        timezone: ZoneInfo = TIMEZONE,
    ):
        self.open_time = open_time
        self.close_time = close_time
        self.business_days = business_days
        self.timezone = timezone

    def is_open(self, at: datetime | None = None) -> bool:
        """
        Returns True if the given datetime (or now) is within business hours.
        """
        now = at or datetime.now(self.timezone)
        if now.weekday() not in self.business_days:
            return False
        current_time = now.time()
        return self.open_time <= current_time < self.close_time

    def next_open_description(self) -> str:
        """Returns a human-readable description of when we next open."""
        now = datetime.now(self.timezone)
        days_ahead = 0
        for _ in range(7):
            days_ahead += 1
            candidate = now.replace(
                hour=self.open_time.hour,
                minute=self.open_time.minute,
                second=0,
                microsecond=0,
            )
            # Simple: just say "tomorrow morning" or "Monday morning"
            if days_ahead == 1:
                return "tomorrow morning at 8 AM"
            weekday_name = [
                "Monday", "Tuesday", "Wednesday",
                "Thursday", "Friday", "Saturday", "Sunday"
            ][(now.weekday() + days_ahead) % 7]
            if (now.weekday() + days_ahead) % 7 in self.business_days:
                return f"{weekday_name} morning at 8 AM"
        return "next business day at 8 AM"


# ─── Intent Detector ──────────────────────────────────────────────────────────

class IntentDetector:
    """
    Lightweight keyword-based intent detector.
    Used to select the appropriate call script before the LLM takes over.
    """

    def __init__(self, keyword_map: dict[str, list[str]] = INTENT_KEYWORDS):
        self._map = keyword_map

    def detect(self, text: str) -> str:
        """
        Returns the best-matching intent key, or 'general_incoming' if none found.

        Args:
            text: Any text from the caller — could be their initial statement,
                  IVR digit press description, or CRM note.

        Returns:
            Script key string.
        """
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for intent, keywords in self._map.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[intent] = score

        if not scores:
            return "general_incoming"

        # Emergency always wins if tied
        if "emergency" in scores:
            return "emergency"

        return max(scores, key=lambda k: scores[k])


# ─── Escalation Engine ────────────────────────────────────────────────────────

class EscalationEngine:
    """
    Determines when Bob should escalate a call to the owner.
    """

    # Phrases that should always trigger escalation regardless of context
    HARD_ESCALATION_PHRASES = [
        "speak to a human",
        "speak to someone",
        "talk to a person",
        "talk to a real person",
        "talk to the owner",
        "get the owner",
        "transfer me",
        "this is an emergency",
        "i need mike",
        "put me through",
    ]

    def __init__(self, owner_phone: str = ""):
        self.owner_phone = owner_phone or os.getenv("OWNER_CELL_NUMBER", "+13035559999")

    def should_escalate(self, caller_text: str, intent: str) -> bool:
        """
        Returns True if the call should be escalated to the owner immediately.
        """
        text_lower = caller_text.lower()

        # Hard escalation phrases
        for phrase in self.HARD_ESCALATION_PHRASES:
            if phrase in text_lower:
                return True

        # Emergency intent always escalates
        if intent == "emergency":
            return True

        return False

    def build_escalation_sms(
        self,
        caller_number: str,
        caller_name: str,
        intent: str,
        summary: str,
    ) -> str:
        """
        Build the SMS text to send to the owner when escalating.
        """
        name_display = caller_name or caller_number
        return (
            f"🎵 Symphony Call Alert\n"
            f"From: {name_display} ({caller_number})\n"
            f"Intent: {intent.replace('_', ' ').title()}\n"
            f"Summary: {summary}\n"
            f"— Bob"
        )


# ─── Main Router ──────────────────────────────────────────────────────────────

class CallRouter:
    """
    Central routing engine. Combines all subsystems to produce a
    fully configured session dict for the OpenAI Realtime API.
    """

    def __init__(
        self,
        crm_lookup_fn=None,
        hours_checker: BusinessHoursChecker | None = None,
        intent_detector: IntentDetector | None = None,
        escalation_engine: EscalationEngine | None = None,
    ):
        self.resolver = CallerResolver(crm_lookup_fn)
        self.hours   = hours_checker or BusinessHoursChecker()
        self.intent  = intent_detector or IntentDetector()
        self.escalation = escalation_engine or EscalationEngine()

    def route(
        self,
        phone_number: str,
        initial_text: str = "",
        override_script: str | None = None,
    ) -> dict:
        """
        Determine the correct script and build a session config.

        Args:
            phone_number:    Caller's phone number (E.164 format preferred).
            initial_text:    Any initial text context (IVR input, CRM note, etc.).
            override_script: Force a specific script key (for testing).

        Returns:
            dict with keys:
              - script_key: str
              - system_prompt: str
              - initial_greeting: str
              - follow_up_prompts: dict
              - client_context: dict | None
              - should_escalate: bool
              - escalation_sms: str | None
              - is_business_hours: bool
        """
        # 1. Resolve caller identity
        client = self.resolver.resolve(phone_number)
        client_name = client.get("name", "") if client else ""

        # 2. Check business hours
        is_open = self.hours.is_open()

        # 3. Detect intent from initial text
        intent = self.intent.detect(initial_text) if initial_text else "general_incoming"

        # 4. Select script
        if override_script and override_script in SCRIPTS:
            script_key = override_script
        elif not is_open:
            script_key = "after_hours"
        elif intent == "emergency":
            script_key = "emergency"  # Handled by emergency_handler.py
        elif client and intent in ("known_client_support", "general_incoming"):
            script_key = "known_client_support"
        elif intent == "sales_inquiry":
            script_key = "sales_inquiry"
        elif intent == "vendor_call":
            script_key = "vendor_call"
        elif client:
            script_key = "known_client_support"
        else:
            script_key = "general_incoming"

        # 5. Check for escalation
        should_escalate = self.escalation.should_escalate(initial_text, intent)
        escalation_sms = None
        if should_escalate:
            escalation_sms = self.escalation.build_escalation_sms(
                caller_number=phone_number,
                caller_name=client_name,
                intent=intent,
                summary=initial_text[:200] if initial_text else "No initial context",
            )

        # 6. Build system prompt
        system_prompt = build_system_prompt(
            script_key=script_key,
            client_context=client,
            extra_context=None,
        )

        # 7. Get script components
        script = SCRIPTS.get(script_key, SCRIPTS["general_incoming"])
        greeting = script["initial_greeting"]

        # Format greeting with client name if available
        if client_name:
            first_name = client_name.split()[0]
            try:
                greeting = greeting.format(first_name=first_name)
            except KeyError:
                pass  # Greeting doesn't use first_name — that's fine

        logger.info(
            f"Routed call: phone={phone_number}, script={script_key}, "
            f"client={'known' if client else 'unknown'}, "
            f"hours={'open' if is_open else 'closed'}, "
            f"escalate={should_escalate}"
        )

        return {
            "script_key": script_key,
            "system_prompt": system_prompt,
            "initial_greeting": greeting,
            "follow_up_prompts": script.get("follow_up_prompts", {}),
            "client_context": client,
            "should_escalate": should_escalate,
            "escalation_sms": escalation_sms,
            "is_business_hours": is_open,
        }

    def get_next_open_message(self) -> str:
        """Returns a human-readable 'we reopen' message for after-hours use."""
        return self.hours.next_open_description()


# ─── Callback Queue ───────────────────────────────────────────────────────────

import heapq
from dataclasses import dataclass, field


@dataclass(order=True)
class CallbackRequest:
    """
    Represents a queued callback request.
    priority: 1 = urgent, 2 = same-day, 3 = next business day
    """
    priority: int
    created_at: str = field(compare=False)
    phone_number: str = field(compare=False)
    caller_name: str = field(compare=False)
    reason: str = field(compare=False)
    preferred_time: str = field(compare=False, default="")


class CallbackQueue:
    """Priority queue for callback requests."""

    def __init__(self):
        self._queue: list[tuple] = []

    def add(
        self,
        phone_number: str,
        caller_name: str,
        reason: str,
        priority: int = 3,
        preferred_time: str = "",
    ) -> CallbackRequest:
        """
        Add a callback request to the queue.

        Args:
            priority: 1 = urgent, 2 = same-day, 3 = next-business-day
        """
        from datetime import datetime as dt
        req = CallbackRequest(
            priority=priority,
            created_at=dt.now().isoformat(),
            phone_number=phone_number,
            caller_name=caller_name,
            reason=reason,
            preferred_time=preferred_time,
        )
        heapq.heappush(self._queue, (priority, req.created_at, req))
        logger.info(f"Callback queued: {caller_name} ({phone_number}) P{priority}")
        return req

    def pop_next(self) -> CallbackRequest | None:
        """Return and remove the highest-priority callback request."""
        if self._queue:
            _, _, item = heapq.heappop(self._queue)
            return item
        return None

    def peek_all(self) -> list[CallbackRequest]:
        """Return all pending callbacks in priority order (non-destructive)."""
        return [item for _, _, item in sorted(self._queue)]

    def size(self) -> int:
        return len(self._queue)


# Global callback queue instance
callback_queue = CallbackQueue()
