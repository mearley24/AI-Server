"""Ollama and LM Studio health checks — host-only (local LAN access)."""

import os
import urllib.request
import json
from fastapi import APIRouter

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434")


@router.get("/status")
async def ai_status():
    """Check local AI services availability."""
    ollama_ok = _check_url(f"{OLLAMA_URL}/api/tags")
    return {
        "ollama": {"url": OLLAMA_URL, "available": ollama_ok},
    }


@router.get("/verify/ollama")
async def verify_ollama():
    """Verify Ollama and list available models."""
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/tags",
            headers={"User-Agent": "SymphonyGateway"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"available": True, "models": models}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _check_url(url: str, timeout: int = 3) -> bool:
    """Return True if the URL responds without error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SymphonyGateway"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False
