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
    low = text.lower()
    return any(phrase in low for phrase in _GENERIC_PHRASES)


# ── Confidence scorer ──────────────────────────────────────────────────────────

def _score_confidence(
    has_profile: bool,
    has_message: bool,
    has_facts: bool,
    behavior_hints: dict,
    ollama_ok: bool,
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
    return round(min(score, 1.0), 2)


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
        {status, draft, confidence, applied_rules, reasoning}
    On Ollama failure returns status='error' with a fallback draft.
    """
    import httpx  # local import keeps module importable without httpx installed

    has_profile = profile is not None
    rel_type    = (profile or {}).get("relationship_type", "unknown")
    display_name = (profile or {}).get("display_name", "")
    summary     = (profile or {}).get("summary", "")
    systems     = (profile or {}).get("systems_or_topics", [])
    open_reqs   = (profile or {}).get("open_requests", [])
    has_facts   = bool(accepted_by_type)
    has_message = bool(message_text.strip())

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
            "status":        "error",
            "error":         f"Ollama unavailable: {str(exc)[:120]}",
            "draft":         "",
            "confidence":    0.0,
            "applied_rules": applied_rules,
            "reasoning":     "; ".join(reasoning_parts),
        }

    draft = _clean_response(raw)

    # Warn if active avoid_generic rule didn't prevent filler
    if behavior_hints.get("avoid_generic") and _contains_generic(draft):
        reasoning_parts.append("warning=generic_phrase_detected_in_draft")

    confidence = _score_confidence(
        has_profile=has_profile,
        has_message=has_message,
        has_facts=has_facts,
        behavior_hints=behavior_hints,
        ollama_ok=True,
    )

    return {
        "status":        "ok",
        "draft":         draft,
        "confidence":    confidence,
        "applied_rules": applied_rules,
        "reasoning":     "; ".join(reasoning_parts),
    }
