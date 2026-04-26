"""Reply Suggestion Engine — Ollama-backed draft generator.

Produces a short, contextual reply draft using:
  - relationship profile and accepted facts
  - incoming message text
  - recent reply history (last 3–5 receipts)
  - active self-improvement rules (avoid_generic, prefer_short)

Never auto-sends. Always requires manual approval.
All Ollama calls are local — no external API usage.
Falls back gracefully when Ollama is unavailable.
"""
from __future__ import annotations

import re
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────────

_MAX_REPLY_SENTENCES = 3
_TIMEOUT_SECONDS = 30

# Generic filler phrases that avoid_generic suppresses
_GENERIC_PHRASES = [
    "let me know if you have any questions",
    "feel free to reach out",
    "don't hesitate to contact",
    "hope this helps",
    "please let me know",
    "looking forward to hearing from you",
]

# ── Safety gate constants ──────────────────────────────────────────────────────

# Phrases that claim Matt is taking unconfirmed action (presence/availability)
_UNSAFE_ACTION_PHRASES = [
    "i'm on my way",
    "i am on my way",
    "i'll be there",
    "i will be there",
    "i'll come by",
    "i will come by",
    "i'll swing by",
    "i will swing by",
    "i'm heading over",
    "i am heading over",
    "i'll head over",
    "i'll stop by",
    "i'm available",
    "i am available",
    "i'll be available",
    "i'm scheduled",
    "i am scheduled",
    "i'll schedule",
    "i will schedule",
    "i can be there",
    "i'll get there",
    "i'll be out",
    "i will be out",
    "i'll be over",
    "i will be over",
    "i'll head out",
    "i will head out",
    "i'll come out",
    "i will come out",
    "be out to check",
    "out to check",
    "out to take a look",
    "out to fix",
    "i'll need to visit",
    "i will need to visit",
    "i'll need to come",
    "i will need to come",
    "i'll need to stop by",
    "i will need to stop by",
    "i'll need to swing by",
    "i will need to swing by",
]

# Banned support filler (broader than _GENERIC_PHRASES — hard blocks)
_BANNED_FILLER = [
    "let me know if you need further assistance",
    "let me know if you need any further assistance",
    "let me know if you need further help",
    "let me know if you need any further help",
    "let me know if you need more help",
    "let me know if you need anything else",
    "let me know if there's anything else",
    "let me know if there is anything else",
    "don't hesitate to reach out",
    "please don't hesitate",
    "if you have any other questions",
    "if you have any questions, feel free",
    "thank you for reaching out",
    "thank you for contacting",
    "i hope this helps",
    "hope that helps",
    "let me know when you're available",
    "let me know when you are available",
    "let me know your availability",
]

# Diagnostic questions that are irrelevant to audio/AV-only requests
_NETWORK_DIAG_PHRASES = [
    "wifi password",
    "wi-fi password",
    "router settings",
    "router password",
    "network password",
    "internet connection",
    "check your internet",
    "connected to the network",
    "connected to wifi",
    "connected to wi-fi",
]

# Keywords that indicate a pure audio/AV issue (no networking component)
_AUDIO_ONLY_KEYWORDS = [
    "sonos",
    "speaker",
    "speakers",
    "audio",
    "music",
    "sound",
    "subwoofer",
    "surround",
]

# Keywords that indicate networking IS relevant
_NETWORK_KEYWORDS = [
    "wifi",
    "wi-fi",
    "internet",
    "network",
    "router",
    "connection",
    "connected",
    "offline",
]

# System-aware fallback templates keyed by detected system keyword
# {system_key: (self_fix, onsite_offer)}
_SYSTEM_TEMPLATES: dict[str, tuple[str, str]] = {
    "wifi": (
        "try unplugging your router for 30 seconds and letting it reconnect",
        "I can take a closer look at the network config",
    ),
    "wi-fi": (
        "try unplugging your router for 30 seconds and letting it reconnect",
        "I can take a closer look at the network config",
    ),
    "sonos": (
        "try unplugging your Sonos for about 10 seconds and plugging it back in",
        "I can swing by and take a look",
    ),
    "lutron": (
        "try cycling the Lutron processor off and back on",
        "I can come take a look if that doesn't clear it",
    ),
    "control4": (
        "try rebooting your Control4 controller",
        "I can remote in or swing by if it's still not right",
    ),
    "thermostat": (
        "try cycling the thermostat off and back on at the breaker",
        "I can stop by if it's still acting up",
    ),
    "shades": (
        "try holding the shade button until it moves, then release — that re-calibrates it",
        "I can come calibrate it in person if needed",
    ),
    "tv": (
        "try holding the power button on the TV itself for 10 seconds",
        "I can swing by if a full reset is needed",
    ),
}


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(
    message_text: str,
    relationship_type: str,
    display_name: str,
    summary: str,
    systems: list[str],
    open_requests: list[str],
    recent_replies: list[dict],
    behavior_hints: dict,
) -> str:
    """Assemble the Ollama prompt from available context."""
    avoid_generic = behavior_hints.get("avoid_generic", False)
    prefer_short  = behavior_hints.get("prefer_short", False)

    rel_label = relationship_type.replace("_", " ") if relationship_type else "contact"
    name_part = f" — {display_name}" if display_name and display_name != "Unknown" else ""

    context_lines: list[str] = []
    if summary:
        context_lines.append(f"Background: {summary[:200]}")
    if systems:
        context_lines.append(f"Systems on file: {', '.join(systems[:4])}")
    if open_requests:
        context_lines.append(f"Open requests: {'; '.join(open_requests[:3])}")
    if recent_replies:
        last = recent_replies[0]
        ts = (last.get("ts") or "")[:10]
        context_lines.append(f"Last contact: {ts}")
    context_block = "\n".join(context_lines) if context_lines else "No prior context on file."

    reply_rules: list[str] = [
        f"Keep the reply to {_MAX_REPLY_SENTENCES} sentences or fewer.",
        "Sound natural and direct — like a trusted professional who knows the client.",
        "Do NOT sign off with 'Matt' or any name.",
        "Do NOT mention Symphony Smart Homes by name.",
        "Do NOT claim you are on your way, available, or scheduled unless the client's message explicitly confirms an appointment.",
        "Do NOT ask diagnostic questions about WiFi, router, or network unless the client's message specifically mentions a connectivity problem.",
        "Do NOT use phrases like 'let me know if you need further assistance' or 'don't hesitate to reach out'.",
        "For equipment issues (Sonos, Control4, Lutron, etc.), offer one simple self-fix step first, then offer an on-site visit if needed.",
    ]
    if avoid_generic or prefer_short:
        reply_rules.append(
            "Do NOT use generic filler phrases such as 'let me know if you have any questions', "
            "'feel free to reach out', or 'hope this helps'."
        )
    if prefer_short:
        reply_rules.append("One or two sentences is ideal. Shorter is better.")

    rules_block = "\n".join(f"- {r}" for r in reply_rules)

    incoming = message_text.strip() if message_text.strip() else "(no message text provided)"

    return f"""/no_think
You are replying on behalf of Matt Earley, owner of a residential AV and smart-home company in Eagle County, Colorado.

Contact type: {rel_label}{name_part}

{context_block}

Incoming message:
"{incoming}"

Reply rules:
{rules_block}

Write only the reply text. No preamble, no explanation, no quotes around your reply.

Reply:"""


# ── Response cleaner ───────────────────────────────────────────────────────────

def _clean_response(text: str) -> str:
    """Strip thinking tokens and tidy up LLM output."""
    # Remove <think>...</think> blocks (qwen3 extended thinking)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace and common quote wrapping
    text = text.strip().strip('"').strip("'").strip()
    return text


def _contains_generic(text: str) -> bool:
    norm = _normalize(text)
    return any(phrase in norm for phrase in _GENERIC_PHRASES)


# ── Safety gate ────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase and normalize typographic apostrophes/quotes to ASCII."""
    return (
        text.lower()
        .replace("’", "'")   # right single quotation mark → straight
        .replace("‘", "'")   # left single quotation mark → straight
        .replace("“", '"')   # left double quotation mark → straight
        .replace("”", '"')   # right double quotation mark → straight
        .replace("–", "-")   # en dash
        .replace("—", "-")   # em dash
    )


# Regex patterns for committed presence claims (I'll/I will, not "I can" conditionals)
# "I can swing by if needed" is acceptable; "I'll swing by tomorrow" is not.
_UNSAFE_ACTION_RE = re.compile(
    r"""
    (?:
        i['']?m\s+(?:on\s+my\s+way|heading\s+over|coming\s+over|scheduled)
      | i['']?ll\s+be\s+(?:there|by|out|over|around|at\s+your|heading|coming|stopping)
      | i['']?ll\s+(?:come|go|head|stop|swing|pop|drop)\s+(?:by|over|out|in|around)
      | i\s+will\s+(?:be\s+there|come\s+by|stop\s+by|swing\s+by|head\s+over|be\s+over|be\s+out)
      | (?:be|come|stop|swing|pop|drop)\s+(?:by|over|out)\s+(?:shortly|soon|today|tomorrow|this\s+\w+|in\s+a\s+bit|later\s+today)
      | on\s+my\s+way\s+(?:to|over|there)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _detect_unsafe_action(text: str) -> str | None:
    """Return the matched phrase if draft claims unconfirmed presence/action."""
    norm = _normalize(text)
    # Phrase list check first (fast path)
    for phrase in _UNSAFE_ACTION_PHRASES:
        if phrase in norm:
            return phrase
    # Regex catch-all for variants not in the phrase list
    m = _UNSAFE_ACTION_RE.search(norm)
    if m:
        return m.group(0).strip()
    return None


def _detect_banned_filler(text: str) -> str | None:
    """Return the matched phrase if draft uses hard-banned support filler."""
    norm = _normalize(text)
    for phrase in _BANNED_FILLER:
        if phrase in norm:
            return phrase
    return None


def _is_irrelevant_network_diag(draft: str, message_text: str) -> bool:
    """True when draft asks about WiFi/router but message is audio-only."""
    draft_norm = _normalize(draft)
    msg_norm   = _normalize(message_text)

    has_network_diag = any(p in draft_norm for p in _NETWORK_DIAG_PHRASES)
    if not has_network_diag:
        return False

    msg_mentions_audio   = any(k in msg_norm for k in _AUDIO_ONLY_KEYWORDS)
    msg_mentions_network = any(k in msg_norm for k in _NETWORK_KEYWORDS)

    # Irrelevant if the message is about audio but not networking
    return msg_mentions_audio and not msg_mentions_network


def _detect_system(message_text: str, systems_on_file: list[str]) -> str | None:
    """Return a system key for the equipment mentioned in the message.

    Checks message text first. Only falls back to systems_on_file when the
    message explicitly mentions a known system — avoids using Sonos template
    for a WiFi complaint just because Sonos is in the profile.
    """
    msg_low = message_text.lower()
    for key in _SYSTEM_TEMPLATES:
        if key in msg_low:
            return key
    return None


def _build_fallback(system_key: str | None, message_text: str) -> str:
    """Build a safe fallback draft from system templates."""
    if system_key and system_key in _SYSTEM_TEMPLATES:
        self_fix, onsite = _SYSTEM_TEMPLATES[system_key]
        return f"Got it — {self_fix}. If it's still acting up after that, {onsite}."
    return "Got it — I'll look into that and get back to you shortly."


def _safety_check(
    draft: str,
    message_text: str,
    systems_on_file: list[str],
) -> tuple[str, list[str]]:
    """Run safety gate on a draft.

    Returns (final_draft, violations) where violations is a list of strings
    describing each problem found. If violations is non-empty the draft was
    replaced with a safe fallback.
    """
    violations: list[str] = []

    unsafe_action = _detect_unsafe_action(draft)
    if unsafe_action:
        violations.append(f"unsafe_action_phrase='{unsafe_action}'")

    banned = _detect_banned_filler(draft)
    if banned:
        violations.append(f"banned_filler='{banned}'")

    if _is_irrelevant_network_diag(draft, message_text):
        violations.append("irrelevant_network_diagnostic")

    if violations:
        system_key = _detect_system(message_text, systems_on_file)
        fallback   = _build_fallback(system_key, message_text)
        return fallback, violations

    return draft, violations


# ── Confidence scorer ──────────────────────────────────────────────────────────

def _score_confidence(
    has_profile: bool,
    has_message: bool,
    has_facts: bool,
    behavior_hints: dict,
    ollama_ok: bool,
    safety_rewrite: bool = False,
) -> float:
    if not ollama_ok:
        return 0.0
    score = 0.5
    if has_profile:
        score += 0.2
    if has_facts:
        score += 0.15
    if has_message:
        score += 0.1
    if behavior_hints.get("prefer_short") or behavior_hints.get("avoid_generic"):
        score += 0.05
    result = round(min(score, 1.0), 2)
    # Cap below 0.85 when the safety gate had to rewrite the draft
    if safety_rewrite:
        result = min(result, 0.84)
    return result


# ── Core async function ────────────────────────────────────────────────────────

async def build_suggestion(
    contact_handle: str,
    message_text: str,
    profile: dict | None,
    accepted_by_type: dict[str, list[dict]],
    recent_replies: list[dict],
    active_rules: list[dict],
    behavior_hints: dict,
    ollama_host: str,
    ollama_model: str,
    timeout: int = _TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Build a suggested reply using local Ollama. Never raises.

    Returns:
        {status, draft, confidence, applied_rules, reasoning, safety_violations}
    On Ollama failure returns status='error' with a fallback draft.
    """
    import httpx  # local import keeps module importable without httpx installed

    has_profile  = profile is not None
    rel_type     = (profile or {}).get("relationship_type", "unknown")
    display_name = (profile or {}).get("display_name", "")
    summary      = (profile or {}).get("summary", "")
    systems      = (profile or {}).get("systems_or_topics", [])
    open_reqs    = (profile or {}).get("open_requests", [])
    has_facts    = bool(accepted_by_type)
    has_message  = bool(message_text.strip())

    # Collect applied rule summaries (approved only — already filtered upstream)
    applied_rules = [
        {
            "rule_id":           r.get("rule_id", ""),
            "behavior_category": r.get("behavior_category", ""),
            "summary":           r.get("summary", ""),
        }
        for r in active_rules
        if r.get("behavior_category") in ("reply_phrasing", "triage_scoring")
    ]

    prompt = _build_prompt(
        message_text=message_text,
        relationship_type=rel_type,
        display_name=display_name,
        summary=summary,
        systems=systems,
        open_requests=open_reqs,
        recent_replies=recent_replies[:3],
        behavior_hints=behavior_hints,
    )

    reasoning_parts: list[str] = [
        f"relationship_type={rel_type}",
        f"has_profile={has_profile}",
        f"has_facts={has_facts}",
        f"message_provided={has_message}",
        f"active_rules={len(active_rules)}",
        f"hints={list(behavior_hints.keys())}",
    ]

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{ollama_host}/api/generate",
                json={"model": ollama_model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
    except Exception as exc:
        return {
            "status":           "error",
            "error":            f"Ollama unavailable: {str(exc)[:120]}",
            "draft":            "",
            "confidence":       0.0,
            "applied_rules":    applied_rules,
            "reasoning":        "; ".join(reasoning_parts),
            "safety_violations": [],
        }

    draft = _clean_response(raw)

    # ── Safety gate ────────────────────────────────────────────────────────────
    draft, violations = _safety_check(draft, message_text, systems)
    safety_rewrite = bool(violations)

    if safety_rewrite:
        reasoning_parts.append(f"safety_rewrite=True violations={violations}")
    elif behavior_hints.get("avoid_generic") and _contains_generic(draft):
        reasoning_parts.append("warning=generic_phrase_detected_in_draft")

    confidence = _score_confidence(
        has_profile=has_profile,
        has_message=has_message,
        has_facts=has_facts,
        behavior_hints=behavior_hints,
        ollama_ok=True,
        safety_rewrite=safety_rewrite,
    )

    return {
        "status":            "ok",
        "draft":             draft,
        "confidence":        confidence,
        "applied_rules":     applied_rules,
        "reasoning":         "; ".join(reasoning_parts),
        "safety_violations": violations,
    }
