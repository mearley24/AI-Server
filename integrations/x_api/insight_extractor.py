"""Heuristic insight extraction from eligible X items.

No LLM calls — pure keyword/pattern matching, deterministic.

Returns an XInsight or None if the item does not meet quality bar:
  - processed_status must be "eligible"
  - relevance_score >= 0.7
  - extracted summary must be non-generic (>= 30 chars, >= 5 words)
"""
from __future__ import annotations

import re
from typing import Optional

from integrations.x_api.insight_models import XInsight

# ---------------------------------------------------------------------------
# Topic detection — ordered by specificity (first match wins)
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS: list[tuple[str, list[str]]] = [
    ("smart_home", [
        "smart home", "smarthome", "home automation", "control4",
        "z-wave", "zigbee", "hvac", "thermostat", "lutron",
        "crestron", "savant", "home theater", "lighting control",
        "iot", "home assistant",
    ]),
    ("av", [
        "audio video", "audio/video", "av system", "av integration",
        "projector", "display", "hdmi", "4k", "surround sound",
        "home cinema", "media room",
    ]),
    ("ai_ml", [
        "llm", "gpt", "claude", "anthropic", "openai", "gemini",
        "mistral", "llama", "agentic", "rag", "embedding",
        "transformer", "inference", "fine-tuning", "finetuning",
        "langchain", "context window", "prompting", "mcp",
        "machine learning", "deep learning", "neural network",
    ]),
    ("engineering", [
        "python", "typescript", "rust", "golang",
        "docker", "kubernetes", "postgres", "redis",
        "open source", "github", "architecture",
        "backend", "frontend", "devops", "api design", "sdk",
    ]),
    ("business", [
        "startup", "saas", "revenue", "b2b", "funding", "founder",
        "entrepreneur", "mrr", "arr", "valuation", "pitch deck",
    ]),
]

# ---------------------------------------------------------------------------
# Insight type detection — ordered, first match wins
# ---------------------------------------------------------------------------

_INSIGHT_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("troubleshooting_tip", [
        r"\bfix(ed)?\b", r"\berror\b", r"\bissue\b", r"\bproblem\b",
        r"\bdebug(ging)?\b", r"\bbroken\b", r"\bworkaround\b",
        r"\bresolv(e|ed)\b", r"\bsolution\b", r"\bbug\b",
        r"\bcrash(ed)?\b", r"\bfail(ed|ure)?\b",
    ]),
    ("workflow_improvement", [
        r"\btip\b", r"\btrick\b", r"\bbetter\b", r"\bimprove\b",
        r"\befficient\b", r"\bfaster\b", r"\boptimiz\b",
        r"\bshortcut\b", r"\bautomat(e|ion)\b", r"\bsave time\b",
        r"\bstreamline\b", r"\bboost\b", r"\bproductivity\b",
    ]),
    ("product_idea", [
        r"\bidea\b", r"\bfeature\b", r"\bwish\b", r"\bimagin(e|ing)\b",
        r"\bcould build\b", r"\bwould be great\b", r"\bproposal\b",
        r"\bsuggestion\b", r"\bwhat if\b", r"\bjust (shipped|launched|released)\b",
        r"\bannouncing\b", r"\blaunch(ed|ing)\b",
    ]),
]

# Phrases that make a summary generic/useless
_GENERIC_PHRASES: frozenset[str] = frozenset({
    "see link", "check this out", "must read", "lol", "haha",
    "great thread", "interesting", "this is cool", "wow",
    "so true", "facts", "based", "exactly",
})


def _detect_topic(text_lower: str) -> str:
    for topic, keywords in _TOPIC_KEYWORDS:
        for kw in keywords:
            if kw in text_lower:
                return topic
    return "general"


def _detect_insight_type(text_lower: str) -> str:
    for itype, patterns in _INSIGHT_TYPE_KEYWORDS:
        for pat in patterns:
            if re.search(pat, text_lower):
                return itype
    return "general_knowledge"


def _strip_noise(text: str) -> str:
    """Remove URLs, @mentions, and #hashtags."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _extract_summary(clean: str) -> str:
    """1–2 sentence summary, max 150 chars."""
    sentences = _split_sentences(clean)
    if not sentences:
        return ""
    summary = " ".join(sentences[:2])
    if len(summary) > 150:
        summary = summary[:147].rstrip() + "…"
    return summary


def _extract_key_points(clean: str) -> list[str]:
    """Up to 3 meaningful sentences as bullet points."""
    sentences = _split_sentences(clean)
    return [s for s in sentences if len(s) > 20][:3]


def _is_generic(summary: str) -> bool:
    """Return True if the summary is too vague to store."""
    if len(summary) < 30:
        return True
    words = summary.split()
    if len(words) < 5:
        return True
    s_lower = summary.lower()
    return any(phrase in s_lower for phrase in _GENERIC_PHRASES)


def extract_insight(item: dict) -> Optional[XInsight]:
    """Extract a structured insight from an eligible x_items row.

    Returns None if:
    - processed_status is not "eligible"
    - relevance_score < 0.7
    - summary is generic or too short
    """
    if item.get("processed_status") != "eligible":
        return None

    score = float(item.get("work_relevance_score") or 0.0)
    if score < 0.7:
        return None

    text = item.get("text") or ""
    url  = item.get("url")
    full_text = text if text else (url or "")
    if not full_text.strip():
        return None

    text_lower = full_text.lower()
    clean = _strip_noise(full_text)

    summary = _extract_summary(clean)
    if _is_generic(summary):
        return None

    return XInsight(
        x_item_id=      item["x_item_id"],
        topic=          _detect_topic(text_lower),
        insight_type=   _detect_insight_type(text_lower),
        summary=        summary,
        key_points=     _extract_key_points(clean),
        relevance_score=round(score, 3),
        source_url=     url,
        author_handle=  item.get("author_handle"),
        created_at=     item.get("created_at"),
    )
