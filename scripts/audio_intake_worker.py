#!/usr/bin/env python3
"""
Audio Intake Worker — transcribes meeting audio with whisper.cpp, analyzes
the transcript with an LLM, and ingests structured output into Cortex as
`meeting_intel` memories.

Runs on Bob as a host-side launchd job every 10 minutes. Safe to re-run —
uses a single-instance lock file to prevent overlapping processing.

Design note (Guardrail §6 — transcript_analyst signature divergence):
    integrations/x_intake/transcript_analyst.analyze_transcript_file(md_path)
    expects a specific .md layout (Summary / Flags / Strategies / Key Quotes /
    Full Transcript) and writes its OWN Cortex memories as x_intel / strategy_idea
    / external_research. It does not return the participants/clients/projects/
    action_items/dollar_amounts shape this worker needs.

    Per the prompt's guardrail ("do not rewrite the analyst"), this worker
    implements a parallel, meeting-focused analyzer that reuses the same
    Ollama-first-then-OpenAI pattern and the same Cortex /remember contract,
    but writes a single `meeting_intel` memory per meeting with the fields
    Matt asked for.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

# --- Config ---
ROOT = Path(os.environ.get("AI_SERVER_ROOT", "/Users/bob/AI-Server"))
INCOMING = ROOT / "data/audio_intake/incoming"
PROCESSING = ROOT / "data/audio_intake/processing"
PROCESSED = ROOT / "data/audio_intake/processed"
FAILED = ROOT / "data/audio_intake/failed"
TRANSCRIPTS = ROOT / "data/transcripts/meetings"
QUEUE_DB = ROOT / "data/audio_intake/queue.db"
MODELS_DIR = ROOT / "models/whisper"
LOCK_FILE = ROOT / "data/audio_intake/.worker.lock"
LOG_DIR = ROOT / "data/audio_intake"

CORTEX_URL = os.environ.get("CORTEX_URL", "http://127.0.0.1:8102")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MEETING_MODEL", "qwen3:8b")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
IMESSAGE_NOTIFY_URL = os.environ.get("IMESSAGE_NOTIFY_URL", "http://127.0.0.1:8199/notify")

AUDIO_EXTS = {".wav", ".m4a", ".mp3", ".flac", ".aac"}

# --- Logging ---
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "worker.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("audio_intake")


# ── Lock ──────────────────────────────────────────────────────────────────────


def acquire_lock() -> bool:
    """Single-instance lock so overlapping launchd runs don't double-process."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            return False  # still running
        except (ValueError, ProcessLookupError, PermissionError):
            try:
                LOCK_FILE.unlink()
            except FileNotFoundError:
                pass
            return acquire_lock()


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def pick_model() -> Path:
    for name in ("ggml-large-v3.bin", "ggml-medium.bin", "ggml-small.bin"):
        p = MODELS_DIR / name
        if p.exists():
            return p
    raise RuntimeError(f"No whisper model found in {MODELS_DIR}")


def parse_date_from_name(name: str) -> Optional[str]:
    """Extract YYYY-MM-DD from filenames like 20240712..., 2024-07-12..., 07-12-2024..."""
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{2})[-_](\d{2})[-_](20\d{2})", name)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return None


def slugify(text: str, max_len: int = 40) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
    return t[:max_len] or "meeting"


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(QUEUE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def enqueue(path: Path) -> int:
    source_date = parse_date_from_name(path.name)
    if not source_date:
        mt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        source_date = mt.strftime("%Y-%m-%d")
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO audio_intake_queue
               (source_path, original_name, source_date, size_bytes, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (str(path), path.name, source_date, path.stat().st_size),
        )
        return int(cur.lastrowid or 0)


def already_enqueued(name: str) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM audio_intake_queue WHERE original_name = ? LIMIT 1",
            (name,),
        ).fetchone()
    return row is not None


def mark(row_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db() as conn:
        conn.execute(
            f"UPDATE audio_intake_queue SET {sets} WHERE id = ?",
            (*fields.values(), row_id),
        )


# ── Whisper ───────────────────────────────────────────────────────────────────


def transcribe(audio_path: Path, out_dir: Path) -> Path:
    """Run whisper.cpp, return path to the .txt output."""
    model = pick_model()
    out_prefix = out_dir / audio_path.stem
    cmd = [
        "whisper-cli",
        "-m", str(model),
        "-f", str(audio_path),
        "-otxt",
        "-of", str(out_prefix),
        "-l", "en",
        "-t", str(os.cpu_count() or 8),
        "-pp",  # print-progress
    ]
    log.info("transcribing %s with %s", audio_path.name, model.name)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if res.returncode != 0:
        raise RuntimeError(f"whisper failed: {res.stderr[-1000:]}")
    txt = out_prefix.with_suffix(".txt")
    if not txt.exists():
        raise RuntimeError(f"whisper produced no output at {txt}")
    return txt


# ── LLM analysis (meeting-focused) ────────────────────────────────────────────


_MEETING_PROMPT = """You are analyzing a meeting audio transcript for Matt Earley, owner of
Symphony Smart Homes — a residential AV / smart-home integration company in
the Vail Valley, Colorado (Eagle County). Projects involve Control4, Lutron,
Crestron, Sonos, Araknis networking, Luma surveillance, and similar gear.

Return ONLY valid JSON with these exact keys:

{
  "summary": "3-6 sentence plain-English summary of what this meeting is about and what was decided",
  "participants": ["first names or role names of people who spoke, best-effort"],
  "clients": ["client last names or property nicknames that were discussed (e.g. Holdeman, Mitchell, Aspen Glen)"],
  "projects": ["project names, addresses, or room names discussed"],
  "decisions": ["clear decisions that were made in this meeting"],
  "action_items": ["specific follow-up actions, in imperative voice"],
  "dollar_amounts": ["any dollar amounts mentioned, with 1-sentence context"],
  "topics": ["3-8 topic tags"]
}

Rules:
- Do NOT invent people, clients, projects, or dollar amounts that are not in the transcript.
- If a field has no content, return [] (empty array) for it.
- Keep each action_item to one sentence, imperative voice ("Call Mitchell about the shade estimate").
- participants: best-effort from context; if unknown, return [].

Transcript:
{transcript}
"""


def _ollama_chat(prompt: str) -> Optional[dict]:
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }).encode()
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read())
        content = raw.get("message", {}).get("content", "")
        if not content:
            return None
        # Strip qwen3-style <think>…</think> reasoning tokens (same fix as transcript_analyst).
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    pass
        return None
    except Exception as exc:
        log.info("meeting_ollama_failed: %s", str(exc)[:200])
        return None


def _openai_chat(prompt: str) -> Optional[dict]:
    api_key = OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=1800,
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        log.warning("meeting_openai_failed: %s", str(exc)[:200])
        return None


def analyze_meeting(transcript_text: str) -> dict:
    """
    Return a dict with: summary, participants, clients, projects, decisions,
    action_items, dollar_amounts, topics.

    Empty lists for missing fields. Never raises — on total LLM failure,
    returns a minimal dict with summary='' and empty arrays.
    """
    snippet = (transcript_text or "").strip()
    if len(re.sub(r"[^\w\s]", "", snippet)) < 40:
        # too short to analyze meaningfully
        return {
            "summary": "(transcript too short to analyze)",
            "participants": [], "clients": [], "projects": [],
            "decisions": [], "action_items": [], "dollar_amounts": [],
            "topics": [],
        }

    prompt = _MEETING_PROMPT.replace("{transcript}", snippet[:45000])
    result = _ollama_chat(prompt) or _openai_chat(prompt)

    if not result or not isinstance(result, dict):
        log.warning("meeting_analysis_failed: no usable result from Ollama or OpenAI")
        return {
            "summary": "(LLM analysis failed — raw transcript saved)",
            "participants": [], "clients": [], "projects": [],
            "decisions": [], "action_items": [], "dollar_amounts": [],
            "topics": [],
        }

    def _list(key: str) -> list:
        v = result.get(key)
        if isinstance(v, list):
            return [str(x) for x in v if x]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    return {
        "summary": str(result.get("summary", "") or "").strip(),
        "participants": _list("participants"),
        "clients": _list("clients"),
        "projects": _list("projects"),
        "decisions": _list("decisions"),
        "action_items": _list("action_items"),
        "dollar_amounts": _list("dollar_amounts"),
        "topics": _list("topics"),
    }


# ── Cortex ────────────────────────────────────────────────────────────────────


def post_to_cortex(payload: dict) -> Optional[str]:
    try:
        url = f"{CORTEX_URL.rstrip('/')}/remember"
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        mem_id = str(body.get("id", ""))
        log.info("cortex_posted: id=%s", mem_id or "?")
        return mem_id or None
    except Exception as exc:
        log.error("cortex_post_failed: %s", str(exc)[:200])
        return None


# ── Markdown artifact ─────────────────────────────────────────────────────────


def write_markdown(row: sqlite3.Row, transcript_text: str, analysis: dict) -> Path:
    date = row["source_date"] or datetime.now().strftime("%Y-%m-%d")
    topic = (analysis.get("summary") or row["original_name"])[:60]
    fname = f"{date}__{slugify(topic)}.md"
    path = TRANSCRIPTS / fname
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Meeting — {date}",
        "",
        f"**Source file:** `{row['original_name']}`",
        f"**Ingested:** {datetime.now(tz=timezone.utc).isoformat()}",
        "",
        "## Summary",
        analysis.get("summary") or "(no summary)",
        "",
    ]
    for key in ("participants", "clients", "projects", "decisions", "action_items", "dollar_amounts", "topics"):
        vals = analysis.get(key) or []
        if vals:
            lines.append(f"## {key.replace('_', ' ').title()}")
            for v in vals:
                lines.append(f"- {v}")
            lines.append("")
    lines.append("## Transcript")
    lines.append("")
    lines.append(transcript_text.strip())
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── One-file pipeline ─────────────────────────────────────────────────────────


def process_one(row: sqlite3.Row) -> None:
    src = Path(row["source_path"])
    if not src.exists():
        # Source was moved into PROCESSING in an earlier failed attempt?
        alt = PROCESSING / row["original_name"]
        if alt.exists():
            src = alt
        else:
            mark(row["id"], status="failed", error_msg=f"source missing: {row['source_path']}")
            return

    PROCESSING.mkdir(parents=True, exist_ok=True)
    proc_path = PROCESSING / src.name
    if src.resolve() != proc_path.resolve():
        shutil.move(str(src), str(proc_path))
    mark(row["id"], status="transcribing", source_path=str(proc_path))

    try:
        txt_path = transcribe(proc_path, PROCESSING)
        transcript_text = txt_path.read_text(encoding="utf-8", errors="replace")

        mark(row["id"], status="analyzing")
        analysis = analyze_meeting(transcript_text)

        refreshed = db().execute(
            "SELECT * FROM audio_intake_queue WHERE id = ?", (row["id"],)
        ).fetchone()
        md_path = write_markdown(refreshed, transcript_text, analysis)

        cortex_payload = {
            "category": "meeting_intel",
            "title": f"Meeting {refreshed['source_date']}: {(analysis.get('summary') or refreshed['original_name'])[:70]}",
            "content": (
                f"Meeting on {refreshed['source_date']}\n"
                f"Source: {refreshed['original_name']}\n\n"
                f"Summary: {analysis.get('summary','')}\n\n"
                + ("Decisions:\n" + "\n".join(f"- {d}" for d in analysis.get("decisions", [])) + "\n\n"
                   if analysis.get("decisions") else "")
                + ("Action items:\n" + "\n".join(f"- {a}" for a in analysis.get("action_items", [])) + "\n\n"
                   if analysis.get("action_items") else "")
                + f"Transcript: {md_path.name}"
            ),
            "source": f"audio_intake:{refreshed['original_name']}",
            "confidence": 0.8,
            "importance": 7,
            "tags": ["meeting_audio"] + list(analysis.get("clients", []))[:3] + list(analysis.get("projects", []))[:3],
            "metadata": {
                "date": refreshed["source_date"],
                "original_file": refreshed["original_name"],
                "transcript_path": str(md_path),
                "participants": analysis.get("participants", []),
                "clients": analysis.get("clients", []),
                "projects": analysis.get("projects", []),
                "action_items": analysis.get("action_items", []),
                "dollar_amounts": analysis.get("dollar_amounts", []),
                "topics": analysis.get("topics", []),
                "analyzed_by": "audio_intake_worker",
            },
            "ttl_days": 365,
        }
        mem_id = post_to_cortex(cortex_payload)

        mark(
            row["id"],
            status="done",
            transcript_path=str(md_path),
            summary=(analysis.get("summary") or "")[:2000],
            participants=json.dumps(analysis.get("participants", [])),
            projects=json.dumps(analysis.get("projects", [])),
            clients=json.dumps(analysis.get("clients", [])),
            action_items=json.dumps(analysis.get("action_items", [])),
            dollar_amounts=json.dumps(analysis.get("dollar_amounts", [])),
            cortex_memory_id=mem_id or "",
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
        )

        # Move original to processed; cleanup intermediate .txt
        PROCESSED.mkdir(parents=True, exist_ok=True)
        final = PROCESSED / proc_path.name
        shutil.move(str(proc_path), str(final))
        try:
            txt_path.unlink()
        except FileNotFoundError:
            pass
        log.info("done: %s -> %s (cortex %s)", refreshed["original_name"], md_path.name, mem_id or "skipped")
    except Exception as exc:
        log.exception("failed on %s", row["original_name"])
        try:
            FAILED.mkdir(parents=True, exist_ok=True)
            shutil.move(str(proc_path), str(FAILED / proc_path.name))
        except Exception:
            pass
        mark(row["id"], status="failed", error_msg=str(exc)[:1000])


# ── Notifications ─────────────────────────────────────────────────────────────


def send_imessage_summary(counts: dict) -> None:
    """Best-effort notify via imessage-server /notify. Silent on failure."""
    body = (
        f"Meeting audio batch done: "
        f"{counts['done']} transcribed, {counts['failed']} failed. "
        f"Top clients: {', '.join(counts['top_clients'][:3]) or '—'}. "
        f"Top projects: {', '.join(counts['top_projects'][:3]) or '—'}."
    )
    try:
        payload = json.dumps({"message": body, "subject": "audio-intake"}).encode()
        req = Request(
            IMESSAGE_NOTIFY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=8) as resp:
            resp.read()
        log.info("imessage_summary_sent: done=%s failed=%s", counts["done"], counts["failed"])
    except Exception as exc:
        log.info("imessage_summary_skipped: %s", str(exc)[:120])


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    if not acquire_lock():
        log.info("another worker instance is running; exiting")
        return 0
    try:
        INCOMING.mkdir(parents=True, exist_ok=True)

        # 1. Scan incoming for new files (skip already-enqueued names to stay idempotent)
        new_files = [
            p for p in INCOMING.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        ]
        for p in new_files:
            if not already_enqueued(p.name):
                enqueue(p)

        # 2. Drain pending / stuck rows
        rows = list(db().execute(
            "SELECT * FROM audio_intake_queue "
            "WHERE status IN ('pending','transcribing','analyzing') "
            "ORDER BY id ASC"
        ).fetchall())
        log.info("pending/stuck rows: %d", len(rows))

        start_done = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='done'"
        ).fetchone()[0]
        start_failed = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='failed'"
        ).fetchone()[0]

        for row in rows:
            process_one(row)

        end_done = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='done'"
        ).fetchone()[0]
        end_failed = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='failed'"
        ).fetchone()[0]
        delta_done = end_done - start_done
        delta_failed = end_failed - start_failed

        if delta_done or delta_failed:
            recent = db().execute(
                "SELECT clients, projects FROM audio_intake_queue "
                "WHERE status='done' ORDER BY id DESC LIMIT ?", (max(delta_done, 1),)
            ).fetchall()
            cc: dict = {}
            pp: dict = {}
            for r in recent:
                for c in json.loads(r["clients"] or "[]"):
                    cc[c] = cc.get(c, 0) + 1
                for p in json.loads(r["projects"] or "[]"):
                    pp[p] = pp.get(p, 0) + 1
            top_c = sorted(cc, key=cc.get, reverse=True)
            top_p = sorted(pp, key=pp.get, reverse=True)
            send_imessage_summary({
                "done": delta_done,
                "failed": delta_failed,
                "top_clients": top_c,
                "top_projects": top_p,
            })
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
