"""
Research Agent — performs product/topic research using the Perplexity sonar API.

Provides:
- research_products(query, context) — product alternatives, specs, pricing
- research_topic(query) — general research for any topic
- save_research(project_name, filename, content) — saves to knowledge/{project}/
"""

import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger("openclaw.research_agent")

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

# Base knowledge directory (relative to repo root)
_REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = _REPO_ROOT / "knowledge"


# ---------------------------------------------------------------------------
# Core Perplexity API
# ---------------------------------------------------------------------------

def search_perplexity(query: str, system_prompt: str = "") -> str | None:
    """
    Search using Perplexity sonar API.

    Args:
        query: The search query.
        system_prompt: Optional system prompt for context.

    Returns:
        Response text or None if API key not set / request failed.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        logger.warning("PERPLEXITY_API_KEY not set — research unavailable")
        return None

    default_system = (
        "You are a research assistant for Symphony Smart Homes, "
        "a residential/commercial AV, lighting, network, and automation "
        "integrator in Eagle County, Colorado. "
        "Provide concise, factual answers with specific model numbers, "
        "pricing ranges, and availability when applicable."
    )

    try:
        resp = requests.post(
            PERPLEXITY_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [
                    {"role": "system", "content": system_prompt or default_system},
                    {"role": "user", "content": query},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("Perplexity API error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def research_products(query: str, context: str = "") -> str | None:
    """
    Search for product alternatives, specs, and pricing.

    Args:
        query: What to research (e.g., "LG C4 77\" OLED alternatives for commercial install")
        context: Additional context about the project or requirements.

    Returns:
        Research results as text, or None.
    """
    system_prompt = (
        "You are a product research specialist for a smart home integrator. "
        "When researching products, provide:\n"
        "1. Top 2-3 alternatives with model numbers\n"
        "2. Key specs comparison (size, features, connectivity)\n"
        "3. Approximate pricing (MSRP and dealer/distributor if known)\n"
        "4. Availability through major AV distributors (Snap One, ADI, Anixter)\n"
        "5. Any compatibility notes with Control4, Crestron, or Lutron systems\n\n"
        "Keep responses concise — bullet points preferred."
    )

    full_query = query
    if context:
        full_query = f"{query}\n\nContext: {context}"

    return search_perplexity(full_query, system_prompt)


def research_topic(query: str) -> str | None:
    """
    General research for any topic.

    Args:
        query: The research question.

    Returns:
        Research results as text, or None.
    """
    return search_perplexity(query)


def save_research(project_name: str, filename: str, content: str) -> str:
    """
    Save research output to knowledge/{project_name}/{filename}.

    Args:
        project_name: Project folder name (e.g., "topletz", "shaw")
        filename: File name (e.g., "tv-alternatives.md")
        content: Research content to save.

    Returns:
        Absolute path to the saved file.
    """
    project_dir = KNOWLEDGE_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    filepath = project_dir / filename
    filepath.write_text(content, encoding="utf-8")

    logger.info("Research saved: %s", filepath)
    return str(filepath)
