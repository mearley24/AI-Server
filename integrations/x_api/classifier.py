"""X item quality gate — heuristic classifier.

No LLM calls. Pure keyword/pattern matching, deterministic and fast.

Returns a Classification with:
  content_category  : "work" | "neutral" | "non_work" | "unsafe"
  work_relevance_score : 0.0–1.0
  quality_flags     : list of flag strings
  classification_reason : human-readable explanation

Promotion rules (applied by intake.py):
  eligible  → category == "work" and score >= 0.7 and no flags
  pending   → category == "work" and score in [0.5, 0.7) and no flags
  blocked   → category != "work" or score < 0.5 or any flags present
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

# Each term is checked as a word-boundary match (case-insensitive).
# Weights: each match contributes to the score adjustment.

_WORK_TERMS: dict[str, float] = {
    # AI / ML / LLMs
    "ai": 0.06, "ml": 0.06, "llm": 0.10, "llms": 0.10,
    "gpt": 0.08, "claude": 0.08, "anthropic": 0.10, "openai": 0.08,
    "gemini": 0.06, "mistral": 0.06, "llama": 0.06,
    "agent": 0.08, "agents": 0.08, "agentic": 0.10,
    "langchain": 0.08, "rag": 0.08, "retrieval": 0.06,
    "embedding": 0.08, "embeddings": 0.08, "vector": 0.06,
    "transformer": 0.08, "inference": 0.08, "fine-tuning": 0.08,
    "finetuning": 0.08, "benchmark": 0.06, "dataset": 0.06,
    "neural": 0.06, "diffusion": 0.06, "multimodal": 0.08,
    "rlhf": 0.10, "dpo": 0.08, "sft": 0.06, "mcp": 0.08,
    "context window": 0.10, "reasoning": 0.06, "prompting": 0.08,
    # Software / engineering
    "code": 0.05, "coding": 0.06, "software": 0.06,
    "engineering": 0.06, "developer": 0.06, "api": 0.06, "sdk": 0.08,
    "framework": 0.06, "library": 0.05, "open source": 0.08,
    "github": 0.08, "pull request": 0.06, "deployment": 0.06,
    "architecture": 0.06, "backend": 0.06, "frontend": 0.05,
    "database": 0.05, "postgres": 0.06, "redis": 0.06,
    "docker": 0.06, "kubernetes": 0.06, "devops": 0.06,
    "python": 0.06, "typescript": 0.06, "javascript": 0.05,
    "rust": 0.06, "golang": 0.06,
    # Business / startup
    "startup": 0.06, "saas": 0.08, "product": 0.04,
    "launch": 0.04, "revenue": 0.06, "b2b": 0.08,
    "automation": 0.06, "workflow": 0.06, "productivity": 0.05,
    "integration": 0.05, "pipeline": 0.05,
    "founder": 0.06, "entrepreneur": 0.06, "cto": 0.08,
    "funding": 0.06, "raise": 0.04, "investor": 0.05,
    "customer": 0.04, "client": 0.04,
    # Smart home / IoT (Bob's actual business — Symphony Smart Homes)
    "smart home": 0.12, "smarthome": 0.12, "home automation": 0.12,
    "iot": 0.10, "symphony": 0.10, "hvac": 0.10, "thermostat": 0.08,
    "sensor": 0.06, "controller": 0.06, "z-wave": 0.10, "zigbee": 0.10,
    "real estate": 0.08, "contractor": 0.06, "construction": 0.06,
    "proposal": 0.05, "quote": 0.04,
    # Research / content worth reading
    "paper": 0.05, "research": 0.06, "study": 0.04,
    "published": 0.04, "arxiv": 0.10,
}

# Non-work terms — subtract from score
_NON_WORK_TERMS: dict[str, float] = {
    # Politics / politicians
    "trump": 0.15, "biden": 0.12, "harris": 0.10,
    "democrat": 0.15, "republican": 0.15, "gop": 0.15,
    "maga": 0.20, "liberal": 0.10, "conservative": 0.10,
    "dnc": 0.15, "rnc": 0.15,
    "senate": 0.10, "congress": 0.10, "congressman": 0.10,
    "election": 0.12, "vote": 0.10, "ballot": 0.12,
    "abortion": 0.15, "gun control": 0.15, "immigration": 0.12,
    "illegal alien": 0.20, "border crisis": 0.18,
    "protest": 0.08, "rally": 0.06,
    "leftist": 0.15, "fascist": 0.15, "communist": 0.15,
    "woke": 0.12, "based": 0.05,
    # War / conflict
    "gaza": 0.12, "ukraine": 0.08, "ceasefire": 0.10,
    "hamas": 0.15, "isis": 0.15,
    # Entertainment / celebrity
    "kardashian": 0.20, "celebrity": 0.10,
    "grammys": 0.15, "oscars": 0.15, "emmys": 0.15,
    "reality tv": 0.15, "tiktok dance": 0.15,
    # Crypto speculation / hype (not engineering)
    "to the moon": 0.12, "lambo": 0.12, "wen": 0.06,
    "shitcoin": 0.15, "rugpull": 0.12,
}

# Unsafe terms — immediate unsafe category + block
_UNSAFE_TERMS: frozenset[str] = frozenset({
    "rape", "molest", "pedophile", "child porn",
    "kys", "kill yourself", "kill all",
    "nigger", "faggot", "tranny",
})

# Political pattern — triggers `political` flag even without full score hit
_POLITICAL_TERMS: frozenset[str] = frozenset({
    "trump", "biden", "harris", "democrat", "republican", "gop", "maga",
    "liberal", "conservative", "dnc", "rnc", "senate", "congress",
    "election", "vote", "ballot", "abortion", "gun control", "immigration",
    "leftist", "fascist", "communist", "woke", "antifa", "protest", "rally",
    "manifesto", "regime",
})


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

@dataclass
class Classification:
    content_category: str         # "work" | "neutral" | "non_work" | "unsafe"
    work_relevance_score: float   # 0.0–1.0
    quality_flags: list[str] = field(default_factory=list)
    classification_reason: str = ""

    @property
    def promoted_status(self) -> str:
        """Return the processed_status to assign to the item."""
        if self.content_category == "unsafe":
            return "blocked"
        if self.quality_flags:
            return "blocked"
        if self.content_category != "work":
            return "blocked"
        if self.work_relevance_score < 0.5:
            return "blocked"
        if self.work_relevance_score >= 0.7:
            return "eligible"
        return "pending"


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return text.lower()


def _word_boundary_match(text_lower: str, term: str) -> bool:
    """Return True if term appears as a whole word/phrase in text."""
    # Use word boundaries for single words; substring match for phrases
    if " " in term:
        return term in text_lower
    return bool(re.search(rf"\b{re.escape(term)}\b", text_lower))


def _detect_flags(text: str, text_lower: str) -> list[str]:
    flags: list[str] = []

    # political
    if any(_word_boundary_match(text_lower, t) for t in _POLITICAL_TERMS):
        flags.append("political")

    # emotional: >3 exclamation marks OR >25% all-caps words (min 5 words)
    exclamations = text.count("!")
    words = text.split()
    caps_words = sum(1 for w in words if w.isupper() and len(w) > 2)
    if exclamations >= 4 or (len(words) >= 5 and caps_words / len(words) > 0.25):
        flags.append("emotional")

    # rant: long text + emotional markers
    if len(text) > 240 and ("emotional" in flags or exclamations >= 3):
        flags.append("rant")

    # offensive: unsafe terms also flag as offensive here (category handles blocking)
    if any(_word_boundary_match(text_lower, t) for t in _UNSAFE_TERMS):
        flags.append("offensive")

    # low_signal: very short, no meaningful content
    stripped = re.sub(r"https?://\S+", "", text).strip()
    stripped = re.sub(r"[@#]\w+", "", stripped).strip()
    if len(stripped) < 20:
        flags.append("low_signal")

    return flags


def classify(text: str | None, item_type: str = "post", url: str | None = None) -> Classification:
    """Classify an X item and return a Classification.

    Args:
        text: raw tweet text (may be None for URL-only items)
        item_type: "post" | "like" | "bookmark" | "url"
        url: external URL if item_type == "url"
    """
    if not text:
        text = ""

    text_lower = _normalize(text)

    # --- Unsafe check (immediate) ------------------------------------------
    if any(_word_boundary_match(text_lower, t) for t in _UNSAFE_TERMS):
        return Classification(
            content_category="unsafe",
            work_relevance_score=0.0,
            quality_flags=["offensive"],
            classification_reason="Contains unsafe content.",
        )

    # --- Score work signals --------------------------------------------------
    base_score = 0.35
    work_hits: list[str] = []
    non_work_hits: list[str] = []

    for term, weight in _WORK_TERMS.items():
        if _word_boundary_match(text_lower, term):
            base_score += weight
            work_hits.append(term)

    for term, weight in _NON_WORK_TERMS.items():
        if _word_boundary_match(text_lower, term):
            base_score -= weight
            non_work_hits.append(term)

    score = max(0.0, min(1.0, base_score))

    # --- Detect flags --------------------------------------------------------
    flags = _detect_flags(text, text_lower)

    # --- Determine category --------------------------------------------------
    if "offensive" in flags:
        category = "unsafe"
    elif "political" in flags or any(t in non_work_hits for t in _POLITICAL_TERMS):
        category = "non_work"
    elif score >= 0.5:
        category = "work"
    elif score >= 0.35:
        category = "neutral"
    else:
        category = "non_work"

    # --- Build reason --------------------------------------------------------
    parts: list[str] = [f"score={score:.2f}"]
    if work_hits:
        parts.append(f"work_signals=[{', '.join(work_hits[:5])}]")
    if non_work_hits:
        parts.append(f"non_work_signals=[{', '.join(non_work_hits[:5])}]")
    if flags:
        parts.append(f"flags=[{', '.join(flags)}]")
    reason = "; ".join(parts)

    return Classification(
        content_category=category,
        work_relevance_score=round(score, 3),
        quality_flags=flags,
        classification_reason=reason,
    )
