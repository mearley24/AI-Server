"""Detect scope / change-order language in client emails -> Linear issue + Redis event."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("openclaw.scope_tracker")

_SCOPE_RE = re.compile(
    r"\b(?:change\s*order|scope\s*change|add\s+to\s+scope|additional\s+work"
    r"|modif(?:y|ied|ication)|revised?\s+scope|new\s+scope|scope\s+update"
    r"|out\s+of\s+scope|scope\s*creep|extras?\s+beyond|addendum)\b",
    re.I,
)


def _seen_path(data_dir: str) -> Path:
    return Path(data_dir) / "scope_tracker_seen.json"


def _load_seen(data_dir: str) -> set[str]:
    p = _seen_path(data_dir)
    if not p.is_file():
        return set()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return set(str(x) for x in raw)
    except Exception:
        pass
    return set()


def _save_seen(data_dir: str, ids: set[str]) -> None:
    p = _seen_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = sorted(ids)[-500:]
    p.write_text(json.dumps(keep), encoding="utf-8")


async def process_new_emails(
    emails: list[dict[str, Any]],
    redis_client: Any = None,
    data_dir: str = "",
) -> int:
    """Scan *emails* for scope-change language. Returns count of matches found.

    Parameters
    ----------
    emails : list of email dicts (must have id/message_id, subject, snippet).
    redis_client : optional - anything with _redis_publish (Orchestrator) or a Redis URL string.
    data_dir : path to DATA_DIR for deduplication state.
    """
    if not data_dir:
        data_dir = os.environ.get("DATA_DIR", "/app/data")

    seen = _load_seen(data_dir)
    hits = 0

    for em in emails:
        eid = str(em.get("id") or em.get("message_id") or "")
        if not eid or eid in seen:
            continue

        subj = em.get("subject") or ""
        snip = em.get("snippet") or em.get("summary") or ""
        blob = f"{subj}\n{snip}"
        if not _SCOPE_RE.search(blob):
            continue

        seen.add(eid)
        hits += 1
        logger.info("scope_change_detected email_id=%s subject=%s", eid[:48], subj[:80])

        event_payload = {
            "type": "client.scope_change_detected",
            "data": {
                "email_id": eid,
                "subject": subj[:200],
                "sender": (em.get("sender_name") or em.get("sender") or "")[:120],
            },
        }

        if redis_client is not None:
            try:
                pub = getattr(redis_client, "_redis_publish", None)
                if pub and callable(pub):
                    await pub("events:clients", event_payload)
                else:
                    import redis as redis_sync

                    if isinstance(redis_client, str):
                        r = redis_sync.from_url(redis_client, decode_responses=True)
                    else:
                        r = redis_client
                    try:
                        r.publish("events:clients", json.dumps(event_payload))
                    finally:
                        if isinstance(redis_client, str):
                            r.close()
            except Exception as exc:
                logger.debug("scope_tracker redis publish: %s", exc)

        try:
            ls = getattr(redis_client, "_linear_sync", None)
            if ls and hasattr(ls, "create_doc_regeneration_issue"):
                await ls.create_doc_regeneration_issue(
                    title=f"Scope change detected: {subj[:120]}",
                    description=f"Email ID: {eid}\nSubject: {subj}\nSnippet: {snip[:2000]}",
                    client_name=(em.get("sender_name") or "")[:120],
                )
        except Exception as exc:
            logger.debug("scope_tracker linear: %s", exc)

    if hits:
        _save_seen(data_dir, seen)

    return hits
