"""
Reply-action parser — Phase 1 foundation.

Pure function with no I/O or side effects.
Resolves a raw iMessage reply string to the action slot it references.

Accepted forms (case-insensitive):
    "1"       "2"       "3"
    "reply 1" "reply1"  "Reply 2"
    "r1"      "R2"      "r 3"

Extraneous trailing text is tolerated ("reply 2 please" → slot 2).
Multiple distinct valid-slot numbers in one reply → ambiguous → do nothing.
No typo tolerance; no fuzzy matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class ParsedReply:
    slot: Optional[int]   # resolved slot number, or None
    status: str           # "matched" | "ambiguous" | "unrecognized"

    @property
    def matched(self) -> bool:
        return self.status == "matched"


# Leading token: optional "reply"/"r" prefix, then a digit run, then optional tail.
# Captures group 1 = the digit string.
_LEAD_RE = re.compile(r'^(?:reply\s*|r\s*)(\d+)(?:\s.*)?$')
_BARE_RE = re.compile(r'^(\d+)(?:\s.*)?$')


def parse_reply(raw: str, valid_slots: FrozenSet[int]) -> ParsedReply:
    """
    Map *raw* reply text to a slot number given the set of *valid_slots*.

    Returns a ParsedReply with status:
      "matched"      — unambiguous match; .slot is set
      "ambiguous"    — multiple valid slots detected; .slot is None
      "unrecognized" — no valid slot found; .slot is None
    """
    normalized = raw.strip().lower()

    # Extract the candidate leading token
    m = _LEAD_RE.match(normalized) or _BARE_RE.match(normalized)
    if m is None:
        return ParsedReply(slot=None, status="unrecognized")

    candidate = int(m.group(1))

    # Ambiguity: count how many distinct valid-slot integers appear anywhere in
    # the message (not just the leading token).
    all_ints = {int(x) for x in re.findall(r'\d+', normalized)}
    slot_hits = all_ints & set(valid_slots)
    if len(slot_hits) > 1:
        return ParsedReply(slot=None, status="ambiguous")

    if candidate not in valid_slots:
        return ParsedReply(slot=None, status="unrecognized")

    return ParsedReply(slot=candidate, status="matched")
