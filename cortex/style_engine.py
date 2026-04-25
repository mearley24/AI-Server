"""
Matt Reply Style Engine v1.

Applies learned style rules to draft replies so they match Matt's
natural texting style, without:
  - introducing incorrect technical information
  - hallucinating details
  - breaking grammar
  - altering equipment-specific instructions

Falls back gracefully (returns the original draft unchanged) if the
style profile is unavailable or any transformation raises an exception.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REPO_ROOT    = Path(__file__).resolve().parent.parent
_STYLE_PATH   = _REPO_ROOT / "data" / "client_intel" / "reply_style.json"

# ── Technical terms that must never be altered ────────────────────────────────
# Regex that matches the start of any technical instruction or brand name.
# If the original draft contained any of these and the styled draft does not,
# the styling is rejected and the original is returned.
_TECHNICAL_ANCHOR_RE = re.compile(
    r"\b(sonos|lutron|control4|vantage|araknis|wattbox|episode|triad|pakedge|snapav|"
    r"unplug|reboot|router|remotely|10 seconds|power cycle|wifi|wi-fi|network|"
    r"control4|camera|alarm|shade|keypad|dimmer|theater)\b",
    re.I,
)

# ── Robotic phrases that should never appear in client-facing replies ─────────
_HARDCODED_ROBOTIC: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bthank(?:s|\s+you)?\s+for\s+reaching\s+out\b", re.I), ""),
    (re.compile(r"\bdon'?t\s+hesitate\s+to\s+(?:reach\s+out|contact)\b", re.I), ""),
    (re.compile(r"\bplease\s+feel\s+free\s+to\b", re.I), ""),
    (re.compile(r"\bI\s+look\s+forward\s+to\s+hearing\s+from\s+you\b", re.I), ""),
    (re.compile(r"\bI\s+appreciate\s+your\s+patience\b", re.I), ""),
    (re.compile(r"\bI\s+apologise\s+for\s+any\s+inconvenience\b", re.I), ""),
    (re.compile(r"\bapologize\s+for\s+any\s+inconvenience\b", re.I), ""),
    # Generic AI-support closing: "let me know if you have any questions" etc.
    (re.compile(
        r"\blet\s+me\s+know\s+if\s+you\s+(?:have|need)\s+(?:any\s+)?(?:questions?|concerns?|issues?|anything)\b[.!]?",
        re.I,
    ), ""),
]

# ── Phrase replacements: formal/wordy → natural/concise ──────────────────────
_HARDCODED_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    # "get back to you shortly" → action-oriented, never "let you know" alone
    (re.compile(r"\bget\s+back\s+to\s+you\s+shortly\b", re.I),
     "check on it"),
    # "get back to you with what I find" → concise
    (re.compile(r"\bget\s+back\s+to\s+you\s+with\s+what\s+I\s+find\b", re.I),
     "check on it"),
    # "reach out once I have an update" → direct
    (re.compile(r"\breach\s+out\s+once\s+I\s+have\s+an?\s+update\b", re.I),
     "check on it"),
    # "Give me a few minutes and" → shorter
    (re.compile(r"\bGive\s+me\s+a\s+few\s+minutes\s+and\b", re.I),
     "Give me a bit and"),
    # "I'll take a look and let you know what I find / get back to you" → shorter
    (re.compile(
        r"\bI'?ll\s+take\s+a\s+look\s+and\s+(?:let\s+you\s+know\s+what\s+I\s+find|"
        r"get\s+back\s+to\s+you)\b",
        re.I,
     ),
     "I'll check on it"),
]


# ── Profile loader ─────────────────────────────────────────────────────────────

_cached_profile: dict[str, Any] | None = None


def load_style_profile(path: Path | None = None) -> dict[str, Any]:
    """Load (and cache) the style profile from reply_style.json.

    Returns an empty dict if the file is missing — the engine degrades
    gracefully to hardcoded rules only.
    """
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile
    target = path or _STYLE_PATH
    if not target.is_file():
        _cached_profile = {}
        return _cached_profile
    try:
        _cached_profile = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        _cached_profile = {}
    return _cached_profile


def _reload_profile() -> None:
    """Force profile reload on next call (used in tests)."""
    global _cached_profile
    _cached_profile = None


# ── Core transformations ──────────────────────────────────────────────────────

def _remove_robotic_phrases(text: str, profile: dict) -> str:
    """Strip or replace robotic phrases using hardcoded + profile rules."""
    # Hardcoded rules first (always applied)
    for pattern, replacement in _HARDCODED_ROBOTIC:
        text = pattern.sub(replacement, text).strip()
    # Profile-driven robotic phrases (simple substring removal)
    for phrase in profile.get("robotic_phrases", []):
        idx = text.lower().find(phrase.lower())
        if idx != -1:
            text = (text[:idx] + text[idx + len(phrase):]).strip()
    return " ".join(text.split())  # normalise whitespace


def _apply_replacements(text: str, profile: dict) -> str:
    """Apply phrase replacements: wordy/formal → natural/concise."""
    # Hardcoded replacements first
    for pattern, replacement in _HARDCODED_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    # Profile-driven replacements
    for rule in profile.get("replacements", []):
        src = rule.get("from", "")
        dst = rule.get("to", "")
        if src and dst and src.lower() in text.lower():
            idx = text.lower().find(src.lower())
            text = text[:idx] + dst + text[idx + len(src):]
    return text


def _fix_punctuation(text: str) -> str:
    """Clean up punctuation artifacts left by removals or replacements."""
    # "— ." or "—." at end → drop the dash
    text = re.sub(r"\s*—\s*\.\s*$", ".", text)
    # Leading "— " (robotic phrase was at start)
    text = re.sub(r"^—\s+", "", text)
    # Double spaces
    text = " ".join(text.split())
    # Ensure sentence ends with punctuation
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _technical_anchors(text: str) -> set[str]:
    """Return the set of technical terms present in a text."""
    return {m.group(0).lower() for m in _TECHNICAL_ANCHOR_RE.finditer(text)}


def _safety_check(original: str, styled: str) -> bool:
    """Return True if the styled reply preserves all technical anchors."""
    orig_anchors = _technical_anchors(original)
    if not orig_anchors:
        return True                              # no technical terms to protect
    styled_anchors = _technical_anchors(styled)
    return orig_anchors.issubset(styled_anchors)


# ── Public API ─────────────────────────────────────────────────────────────────

def apply_style(
    draft: str,
    context: dict | None = None,
    profile_path: Path | None = None,
) -> tuple[str, bool, float]:
    """Apply Matt's reply style to a draft.

    Parameters
    ----------
    draft        : the draft reply from _build_draft_with_context()
    context      : optional dict with relationship_type, profile, etc.
    profile_path : override for testing

    Returns
    -------
    (styled_draft, style_applied, style_confidence)
      style_applied    — True if the text was changed
      style_confidence — 0.0–1.0 reflecting how well the draft matches
                         the learned style (moderate by design; limited data)
    """
    if not draft or not draft.strip():
        return draft, False, 0.0

    profile = load_style_profile(profile_path)

    original = draft
    try:
        text = draft

        # Step 1: remove robotic phrases
        text = _remove_robotic_phrases(text, profile)

        # Step 2: apply phrase replacements
        text = _apply_replacements(text, profile)

        # Step 3: clean up punctuation artifacts
        text = _fix_punctuation(text)

        # Safety gate: if technical anchors were lost, return original
        if not _safety_check(original, text):
            return original, False, 0.0

        changed = text.strip() != original.strip()

        # Confidence: starts at 0.5 (limited training data), bumps if the
        # draft already matches Matt's known patterns.
        confidence = 0.50
        profile_phrases = [p["phrase"].lower() for p in profile.get("greeting_patterns", [])]
        first_word = text.split()[0].lower().rstrip(",—- ") if text.split() else ""
        if first_word in {"got", "on", "alrighty", "yeah", "perfect", "all"} or \
                any(first_word in pp for pp in profile_phrases):
            confidence = 0.70
        if not changed:
            confidence = max(0.50, confidence)

        return text.strip(), changed, round(confidence, 2)

    except Exception:
        # Never let styling crash the reply pipeline
        return original, False, 0.0
