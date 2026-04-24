"""cortex/autonomy.py — Autonomy Control Plane v1.

Provides:
- Data models for Verification, HumanGate, AutonomyQuestion, AutonomyOverview
- VerificationScanner — reads ops/verification/ for recent PASS/FAIL/etc. verdicts
- HumanGateScanner — finds NEEDS_MATT / [FOLLOWUP] markers across key files
- AutonomyAssessor — answers 10 autonomy-readiness questions via cheap local checks
- InvestigationEngine — for each AUTO_REVIEW gate: gathers evidence, produces hypothesis + proposed fix
- register_autonomy_routes(app) — mounts GET /api/autonomy/overview + /api/autonomy/investigations
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

logger = logging.getLogger(__name__)

# ── Repo root resolution ──────────────────────────────────────────────────────

# When running inside Docker the repo is at /app; on the Mac host it is at
# /Users/bob/AI-Server.  We resolve relative to this file and fall back.
_MODULE_DIR = Path(__file__).resolve().parent
_REPO_CANDIDATES = [
    _MODULE_DIR.parent,                          # normal: cortex/ → repo root
    Path("/app"),                                # Docker bind-mount
    Path("/Users/bob/AI-Server"),                # host path
]


def _repo_root() -> Path:
    for p in _REPO_CANDIDATES:
        if (p / "ops" / "verification").is_dir():
            return p
    return _MODULE_DIR.parent


REPO = _repo_root()
OPS_VERIFICATION_DIR = REPO / "ops" / "verification"
STATUS_REPORT_PATH = REPO / "STATUS_REPORT.md"
OPS_RUNBOOKS_DIR = REPO / "ops" / "runbooks"
CURSOR_PROMPTS_DIR = REPO / ".cursor" / "prompts"
WORK_QUEUE_PENDING_DIR = REPO / "ops" / "work_queue" / "pending"
DATA_TASK_RUNNER_DIR = Path("/Users/bob/AI-Server/data/task_runner")

# ── Data models ────────────────────────────────────────────────────────────────

VALID_VERDICTS = frozenset(
    ["PASS", "FAIL", "PARTIAL", "GAP", "UNKNOWN", "ARMED", "CLOSED", "NEEDS_MATT"]
)

# Matches a line where a gate marker LEADS the line (after optional whitespace + "- ").
# Rejects: inline prose, backtick mentions, section headings, historical references.
_ACTIVE_GATE_LINE = re.compile(
    r"^\s*-?\s*\[(NEEDS_MATT|FOLLOWUP|BLOCKED|ARMED)\]",
    re.IGNORECASE,
)

# For filename scanning only — looks for bracket form anywhere in the name.
_GATE_IN_FILENAME = re.compile(
    r"\[(NEEDS_MATT|FOLLOWUP|BLOCKED|ARMED)\]",
    re.IGNORECASE,
)

# Legacy alias kept so classify_gate callers still compile; not used for line matching.
GATE_MARKERS = _ACTIVE_GATE_LINE

# ── Gate action-class triage ──────────────────────────────────────────────────

# Evaluated in priority order: first match wins.
_WAITING_EXTERNAL_KW = re.compile(
    r"\b(wallet|fund|usdc|matic|polygon|deposit|payment|gas fee"
    r"|macbook|matt.s machine|matt.s macbook|ios.app|symphonyops"
    r"|physical|device|third.party|provider|account status"
    r"|keychain unlock|unlock.*keychain|apple id"
    r"|private.api helper|trusted number|merge conflict)\b",
    re.IGNORECASE,
)
_APPROVAL_REQUIRED_KW = re.compile(
    r"\b(sudo|password|credential|secret|api.key"
    r"|cortex_reply_dry_run|allowed_test_recipients|dry_run=0"
    r"|live.send|outbound.send|external.send|send.*imessage"
    r"|applescript|osascript|macos permission|automation permission"
    r"|approval required|approve|sign off"
    r"|restart.*docker|docker.*restart)\b",
    re.IGNORECASE,
)
_NEEDS_MATT_KW = re.compile(
    r"\b(client|legal|customer|contract|billing|invoice"
    r"|matt decides|human decision|human only"
    r"|configure.*manually|manually configure"
    r"|macbook|matt.s machine)\b",
    re.IGNORECASE,
)
_AUTO_FIX_KW = re.compile(
    r"\b(prune|truncate|cp /dev/null|cleanup|clean up|delete.*log"
    r"|copy.*plist|plist.*launchagents|launchagents.*visibility"
    r"|network.guard.err|dropout.watch.*plist|log rotation"
    r"|image prune|docker.*prune|remove.*stale|housekeeping)\b",
    re.IGNORECASE,
)


def classify_gate(excerpt: str, marker: str) -> str:
    """Triage a human gate into one of five action classes.

    Priority order: WAITING_EXTERNAL > APPROVAL_REQUIRED > NEEDS_MATT >
    AUTO_FIX > AUTO_REVIEW (default).
    """
    text = excerpt + " " + marker
    if _WAITING_EXTERNAL_KW.search(text):
        return "WAITING_EXTERNAL"
    if _APPROVAL_REQUIRED_KW.search(text):
        return "APPROVAL_REQUIRED"
    if _NEEDS_MATT_KW.search(text):
        return "NEEDS_MATT"
    if _AUTO_FIX_KW.search(text):
        return "AUTO_FIX"
    return "AUTO_REVIEW"


@dataclass
class Verification:
    """A single parsed ops/verification/ file."""

    path: str
    filename: str
    timestamp: str           # YYYYMMDD-HHMMSS from filename
    topic: str               # slug from filename
    verdict: str             # PASS / FAIL / PARTIAL / GAP / UNKNOWN / ARMED / CLOSED / NEEDS_MATT
    summary: str             # first non-empty meaningful lines


@dataclass
class HumanGate:
    """A human-intervention gate found in repo files."""

    source: str              # filename / path
    marker: str              # NEEDS_MATT / [FOLLOWUP] / etc.
    excerpt: str             # short excerpt for context
    action_class: str = "AUTO_REVIEW"  # AUTO_FIX / AUTO_REVIEW / APPROVAL_REQUIRED / WAITING_EXTERNAL / NEEDS_MATT


@dataclass
class AutonomyQuestion:
    """One of the 10 autonomy-readiness questions."""

    key: str
    label: str
    status: str              # ok / warn / fail / unknown
    detail: str


@dataclass
class Investigation:
    """Structured investigation report for one AUTO_REVIEW gate."""

    gate_excerpt: str
    gate_source: str
    root_cause_hypothesis: str
    evidence: list[dict[str, Any]]   # [{type, source, content}]
    proposed_fix: str
    confidence: float                # 0.0 – 1.0
    investigated_at: str
    status: str = "complete"         # complete | partial | no_evidence


@dataclass
class AutonomyOverview:
    """Full autonomy control plane snapshot."""

    generated_at: str
    overall_status: str      # ok / warn / degraded
    human_gates: list[HumanGate] = field(default_factory=list)
    recent_verifications: list[Verification] = field(default_factory=list)
    questions: list[AutonomyQuestion] = field(default_factory=list)
    gate_summary: dict[str, int] = field(default_factory=dict)  # counts by action_class


# ── VerificationScanner ───────────────────────────────────────────────────────

_FNAME_RE = re.compile(r"^(\d{8}-\d{6})-(.+?)(?:\.txt|\.md)?$")
_VERDICT_RE = re.compile(
    r"\b(PASS|FAIL|PARTIAL|GAP|UNKNOWN|ARMED|CLOSED|NEEDS_MATT)\b"
)

_MAX_FILES = 50
_MAX_LINES_PER_FILE = 40
_MAX_FILE_BYTES = 500 * 1024  # 500 KB


def _parse_timestamp(raw: str) -> str:
    """Convert YYYYMMDD-HHMMSS → ISO-8601 string (best effort)."""
    try:
        dt = datetime.strptime(raw, "%Y%m%d-%H%M%S")
        return dt.isoformat()
    except ValueError:
        return raw


def _extract_verdict(lines: list[str]) -> str:
    """Scan lines for the strongest verdict signal."""
    # Prefer lines that look like explicit verdict labels
    for line in lines:
        m = _VERDICT_RE.search(line)
        if m:
            return m.group(1)
    return "UNKNOWN"


def _extract_summary(lines: list[str]) -> str:
    """Return first 3 non-empty, non-header lines joined."""
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("=") or stripped.startswith("#"):
            continue
        kept.append(stripped)
        if len(kept) >= 3:
            break
    return " | ".join(kept)[:300]


class VerificationScanner:
    """Scans ops/verification/ and returns parsed Verification objects."""

    def __init__(self, verification_dir: Path = OPS_VERIFICATION_DIR) -> None:
        self._dir = verification_dir

    def scan(self) -> list[Verification]:
        """Return up to _MAX_FILES most-recent Verification objects."""
        if not self._dir.is_dir():
            return []

        # Collect only files (not dirs), sort newest first by filename
        entries = sorted(
            (p for p in self._dir.iterdir() if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )[:_MAX_FILES]

        results: list[Verification] = []
        for path in entries:
            v = self._parse_file(path)
            if v:
                results.append(v)
        return results

    def _parse_file(self, path: Path) -> Verification | None:
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                return None

            m = _FNAME_RE.match(path.stem if path.suffix else path.name)
            if m:
                ts_raw, topic = m.group(1), m.group(2)
            else:
                ts_raw = path.name[:15]
                topic = path.name

            # Read bounded lines
            lines: list[str] = []
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i >= _MAX_LINES_PER_FILE:
                        break
                    lines.append(line.rstrip())

            verdict = _extract_verdict(lines)
            summary = _extract_summary(lines)

            return Verification(
                path=str(path),
                filename=path.name,
                timestamp=_parse_timestamp(ts_raw),
                topic=topic,
                verdict=verdict,
                summary=summary,
            )
        except Exception as exc:
            logger.debug("autonomy.verification_parse_error file=%s err=%s", path.name, exc)
            return None


# ── HumanGateScanner ──────────────────────────────────────────────────────────

_STATUS_TAIL_LINES = 200


class HumanGateScanner:
    """Scans STATUS_REPORT.md and key filename lists for human-gate markers."""

    def __init__(
        self,
        status_report: Path = STATUS_REPORT_PATH,
        runbooks_dir: Path = OPS_RUNBOOKS_DIR,
        prompts_dir: Path = CURSOR_PROMPTS_DIR,
    ) -> None:
        self._status = status_report
        self._runbooks = runbooks_dir
        self._prompts = prompts_dir

    def scan(self) -> list[HumanGate]:
        """Return up to 20 HumanGate objects, most-recent first."""
        gates: list[HumanGate] = []
        gates.extend(self._scan_status_report())
        gates.extend(self._scan_filenames(self._runbooks, "runbook"))
        gates.extend(self._scan_filenames(self._prompts, "prompt"))
        # Deduplicate by (source, marker, excerpt[:60])
        seen: set[tuple[str, str, str]] = set()
        unique: list[HumanGate] = []
        for g in gates:
            key = (g.source, g.marker, g.excerpt[:60])
            if key not in seen:
                seen.add(key)
                unique.append(g)
        return unique[:20]

    def _scan_status_report(self) -> list[HumanGate]:
        if not self._status.is_file():
            return []
        gates: list[HumanGate] = []
        try:
            with self._status.open("r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
            tail = all_lines[-_STATUS_TAIL_LINES:]
            for line in tail:
                stripped = line.strip()
                # Skip resolved strikethrough markers — "- ~~[MARKER]..." or "~~[MARKER]..."
                if stripped.startswith("~~[") or stripped.startswith("- ~~["):
                    continue
                # Only treat lines where the bracket marker LEADS the line as active gates.
                # This rejects prose/backtick mentions and section headings.
                m = _ACTIVE_GATE_LINE.match(line)
                if m:
                    marker = m.group(1).upper()
                    gates.append(HumanGate(
                        source="STATUS_REPORT.md",
                        marker=marker,
                        excerpt=stripped[:160],
                        action_class=classify_gate(stripped, marker),
                    ))
        except Exception as exc:
            logger.debug("autonomy.status_report_scan_error err=%s", exc)
        return gates

    def _scan_filenames(self, directory: Path, kind: str) -> list[HumanGate]:
        """Flag filenames that contain gate keywords."""
        if not directory.is_dir():
            return []
        gates: list[HumanGate] = []
        for p in sorted(directory.iterdir(), key=lambda x: x.name, reverse=True):
            if p.is_file() and _GATE_IN_FILENAME.search(p.name):
                m = _GATE_IN_FILENAME.search(p.name)
                marker = m.group(1).upper() if m else "GATE"
                gates.append(HumanGate(
                    source=f"{kind}/{p.name}",
                    marker=marker,
                    excerpt=f"{kind} filename contains gate marker",
                    action_class=classify_gate(p.name, marker),
                ))
        return gates


# ── AutonomyAssessor ──────────────────────────────────────────────────────────

_BB_HEALTH_URL = "http://localhost:8102/api/bluebubbles/health"
_HTTP_TIMEOUT = 3.0

# Direct DB access — avoids Cortex calling itself (would deadlock the async loop)
_CORTEX_DB = Path(os.environ.get("CORTEX_DATA_DIR", "/data/cortex")) / "brain.db"


def _db_memory_count() -> int:
    """Return total memory count directly from SQLite (non-blocking read)."""
    try:
        conn = sqlite3.connect(str(_CORTEX_DB), timeout=2)
        row = conn.execute("SELECT COUNT(*) FROM memories WHERE importance > 0").fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def _q(key: str, label: str, status: str, detail: str) -> AutonomyQuestion:
    return AutonomyQuestion(key=key, label=label, status=status, detail=detail)


class AutonomyAssessor:
    """Answers the 10 autonomy-readiness questions via cheap local checks."""

    def __init__(
        self,
        verification_scanner: VerificationScanner | None = None,
        gate_scanner: HumanGateScanner | None = None,
    ) -> None:
        self._vs = verification_scanner or VerificationScanner()
        self._gs = gate_scanner or HumanGateScanner()

    async def assess(self) -> AutonomyOverview:
        loop = asyncio.get_event_loop()
        # Run blocking file I/O in a thread pool to avoid blocking the event loop
        gates = await loop.run_in_executor(None, self._gs.scan)
        verifications = await loop.run_in_executor(None, self._vs.scan)

        questions: list[AutonomyQuestion] = [
            await self._is_bob_alive(),
            await self._can_receive_messages(),
            self._can_write_memory(verifications),
            self._can_use_embeddings(),
            self._can_execute_signed_tasks(),
            await self._can_send_outbound(),
            self._what_is_blocked_on_matt(gates),
            self._what_failed_recently(verifications),
            self._what_got_verified_recently(verifications),
            self._what_is_bob_doing_next(verifications),
        ]

        # Overall status: fail if any fail, warn if any warn, else ok
        statuses = [q.status for q in questions]
        if "fail" in statuses:
            overall = "degraded"
        elif "warn" in statuses:
            overall = "warn"
        else:
            overall = "ok"

        active_gates = gates[:20]
        gate_summary: dict[str, int] = {}
        for g in active_gates:
            gate_summary[g.action_class] = gate_summary.get(g.action_class, 0) + 1

        return AutonomyOverview(
            generated_at=datetime.now(timezone.utc).isoformat(),
            overall_status=overall,
            human_gates=active_gates,
            recent_verifications=verifications[:10],
            questions=questions,
            gate_summary=gate_summary,
        )

    # ── Individual checks ─────────────────────────────────────────────────────

    async def _is_bob_alive(self) -> AutonomyQuestion:
        key = "is_bob_alive"
        label = "Is Bob (Cortex) alive?"
        # Direct DB check — Cortex cannot call itself without deadlocking
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(None, _db_memory_count)
        if count >= 0:
            return _q(key, label, "ok", f"alive — {count} memories in DB")
        return _q(key, label, "warn", "DB unreadable or empty")

    async def _can_receive_messages(self) -> AutonomyQuestion:
        key = "can_receive_messages"
        label = "Can Bob receive iMessages?"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(_BB_HEALTH_URL)
            if resp.status_code == 200:
                data = resp.json()
                inbound = (data.get("counters") or {}).get("inbound_count", 0) or 0
                last = data.get("last_inbound_event_at") or "never"
                status_str = data.get("status", "unknown")
                if status_str == "healthy":
                    return _q(key, label, "ok", f"healthy — {inbound} inbound events, last: {last}")
                return _q(key, label, "warn", f"status={status_str}, inbound={inbound}")
            return _q(key, label, "warn", f"BlueBubbles health HTTP {resp.status_code}")
        except Exception as exc:
            return _q(key, label, "warn", f"BlueBubbles check failed: {str(exc)[:80]}")

    def _can_write_memory(self, verifications: list[Verification]) -> AutonomyQuestion:
        key = "can_write_memory"
        label = "Can Bob write to memory?"
        count = _db_memory_count()
        if count > 0:
            return _q(key, label, "ok", f"memory DB has {count} entries")
        if count == 0:
            return _q(key, label, "warn", "memory count is 0 — pipeline may be cold")
        return _q(key, label, "fail", "memory DB unreadable")

    def _can_use_embeddings(self) -> AutonomyQuestion:
        key = "can_use_embeddings"
        label = "Embeddings enabled?"
        enabled = os.environ.get("CORTEX_EMBEDDINGS_ENABLED", "0") == "1"
        openai_ok = bool(os.environ.get("OPENAI_API_KEY", ""))
        ollama_model = os.environ.get("CORTEX_EMBED_OLLAMA_MODEL", "nomic-embed-text")
        if enabled:
            backend = "openai+ollama" if openai_ok else "ollama-only"
            return _q(key, label, "ok", f"enabled — model={ollama_model} backend={backend}")
        return _q(key, label, "warn", "CORTEX_EMBEDDINGS_ENABLED=0 (disabled by config)")

    def _can_execute_signed_tasks(self) -> AutonomyQuestion:
        key = "can_execute_signed_tasks"
        label = "Task runner alive?"
        heartbeat_candidates = [
            Path("/data/task_runner/heartbeat.txt"),          # Docker mount path
            Path("/data/task_runner/bob_watchdog_heartbeat.txt"),
            Path("/data/task_runner/watchdog_heartbeat.txt"),
            DATA_TASK_RUNNER_DIR / "heartbeat.txt",           # host path fallback
            DATA_TASK_RUNNER_DIR / "bob_watchdog_heartbeat.txt",
        ]
        for hb in heartbeat_candidates:
            if hb.is_file():
                age_s = time.time() - hb.stat().st_mtime
                age_min = age_s / 60
                if age_min < 30:
                    return _q(key, label, "ok", f"{hb.name} updated {age_min:.0f}min ago")
                return _q(key, label, "warn", f"{hb.name} is stale — {age_min:.0f}min old")
        return _q(key, label, "warn", "no heartbeat file found — task runner may be down")

    async def _can_send_outbound(self) -> AutonomyQuestion:
        key = "can_send_outbound"
        label = "Can Bob send outbound iMessages?"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(_BB_HEALTH_URL)
            if resp.status_code == 200:
                data = resp.json()
                outbound = (data.get("counters") or {}).get("outbound_count", 0) or 0
                last_ping = data.get("last_ping_ok_at") or "never"
                ping_err = data.get("last_ping_error")
                status_str = data.get("status", "unknown")
                if status_str == "healthy" and not ping_err:
                    return _q(key, label, "ok", f"healthy — {outbound} sent, last ping: {last_ping}")
                if ping_err:
                    return _q(key, label, "warn", f"ping error: {ping_err}")
                return _q(key, label, "warn", f"status={status_str}, outbound={outbound}")
            return _q(key, label, "warn", f"BlueBubbles health HTTP {resp.status_code}")
        except Exception as exc:
            return _q(key, label, "warn", f"BlueBubbles check failed: {str(exc)[:80]}")

    def _what_is_blocked_on_matt(self, gates: list[HumanGate]) -> AutonomyQuestion:
        key = "what_is_blocked_on_matt"
        label = "What is blocked on Matt?"
        truly_blocked = [g for g in gates if g.action_class in ("NEEDS_MATT", "WAITING_EXTERNAL", "APPROVAL_REQUIRED")]
        auto_fixable  = [g for g in gates if g.action_class == "AUTO_FIX"]
        auto_review   = [g for g in gates if g.action_class == "AUTO_REVIEW"]
        if not gates:
            return _q(key, label, "ok", "no open gates found")
        parts = []
        if truly_blocked:
            excerpts = "; ".join(g.excerpt[:50] for g in truly_blocked[:2])
            parts.append(f"{len(truly_blocked)} need Matt ({excerpts})")
        if auto_fixable:
            parts.append(f"{len(auto_fixable)} AUTO_FIX ready")
        if auto_review:
            parts.append(f"{len(auto_review)} AUTO_REVIEW queued")
        status = "warn" if truly_blocked else "ok"
        return _q(key, label, status, " | ".join(parts)[:300])

    def _what_failed_recently(self, verifications: list[Verification]) -> AutonomyQuestion:
        key = "what_failed_recently"
        label = "What failed recently?"
        failed = [v for v in verifications if v.verdict in ("FAIL", "GAP")][:5]
        if not failed:
            return _q(key, label, "ok", "no recent FAIL or GAP verdicts")
        topics = ", ".join(v.topic for v in failed[:3])
        return _q(key, label, "warn", f"{len(failed)} recent failures: {topics}")

    def _what_got_verified_recently(self, verifications: list[Verification]) -> AutonomyQuestion:
        key = "what_got_verified_recently"
        label = "What passed verification recently?"
        passed = [v for v in verifications if v.verdict in ("PASS", "CLOSED")][:5]
        if not passed:
            return _q(key, label, "warn", "no recent PASS or CLOSED verifications")
        topics = ", ".join(v.topic for v in passed[:5])
        return _q(key, label, "ok", f"{len(passed)} recent: {topics}")

    def _what_is_bob_doing_next(self, verifications: list[Verification]) -> AutonomyQuestion:
        key = "what_is_bob_doing_next"
        label = "What is Bob doing next?"
        pending_count = 0
        if WORK_QUEUE_PENDING_DIR.is_dir():
            try:
                pending_count = sum(1 for p in WORK_QUEUE_PENDING_DIR.iterdir() if p.is_file())
            except Exception:
                pass
        recent_topics = [v.topic for v in verifications[:3]]
        topic_str = ", ".join(recent_topics) if recent_topics else "none"
        if pending_count > 0:
            return _q(key, label, "ok", f"{pending_count} tasks queued — recent topics: {topic_str}")
        return _q(key, label, "warn", f"queue empty — recent verification topics: {topic_str}")


# ── Route registration ────────────────────────────────────────────────────────


# ── Investigation engine ──────────────────────────────────────────────────────

_INV_CACHE_TTL = 600  # seconds before re-investigating same gate
_MAX_LOG_LINES = 50
_MAX_FILE_BYTES = 32 * 1024   # 32 KB cap on any single evidence piece

# Keyword → (hypothesis_template, evidence_sources, proposed_fix)
_INVESTIGATION_RULES: list[tuple[re.Pattern, str, list[dict], str]] = [
    (
        re.compile(r"backfill|embed", re.I),
        "Cortex embedding backfill is incomplete or stalled.",
        [
            {"type": "db_count",    "label": "embedded rows",      "query": "SELECT COUNT(*) FROM memory_embeddings"},
            {"type": "db_count",    "label": "total memories",     "query": "SELECT COUNT(*) FROM memories WHERE importance>0"},
            {"type": "env_flag",    "label": "CORTEX_EMBEDDINGS_ENABLED"},
            {"type": "file_tail",   "label": "embed backfill log", "path": "data/task_runner/heartbeat.txt"},
        ],
        "Run: docker exec cortex python3 /app/scripts/cortex_embed_backfill.py --apply --provider ollama --db /data/cortex/brain.db",
    ),
    (
        re.compile(r"docker.*daemon|daemon.*crash|crash.loop|docker.*stability|docker.*restart", re.I),
        "Docker Desktop daemon instability — likely memory pressure or keychain-locked rebuild attempts.",
        [
            {"type": "docker_ps",   "label": "container health"},
            {"type": "file_tail",   "label": "watchdog log",       "path": "data/task_runner/bob-watchdog.log"},
            {"type": "file_stat",   "label": "watchdog heartbeat", "path": "data/task_runner/watchdog_heartbeat.txt"},
            {"type": "health_url",  "label": "cortex health",      "url": "http://127.0.0.1:8102/health"},
        ],
        "Run scripts/docker-recover.sh if daemon is down. Unlock keychain (security unlock-keychain) before --build.",
    ),
    (
        re.compile(r"network.guard|network.*guard|guard.*daemon", re.I),
        "network-guard daemon may be crash-looping or stale.",
        [
            {"type": "file_tail",   "label": "network-guard.log",  "path": "logs/network-guard.log"},
            {"type": "file_tail",   "label": "network-guard.err",  "path": "logs/network-guard.err"},
            {"type": "file_stat",   "label": "guard log mtime",    "path": "logs/network-guard.log"},
        ],
        "Check launchctl list | grep network-guard; reload plist if stale.",
    ),
    (
        re.compile(r"dropout.watch|network.*dropout|dropout.*network", re.I),
        "dropout-watch LaunchAgent status unknown.",
        [
            {"type": "file_json",   "label": "dropout status",     "path": "data/network_watch/dropout_watch_status.json"},
            {"type": "file_stat",   "label": "status mtime",       "path": "data/network_watch/dropout_watch_status.json"},
        ],
        "Verify launchctl list | grep dropout-watch; re-arm if not running.",
    ),
    (
        re.compile(r"task.runner|task runner|watchdog", re.I),
        "Task runner or watchdog may be stale or stopped.",
        [
            {"type": "file_stat",   "label": "heartbeat mtime",    "path": "data/task_runner/heartbeat.txt"},
            {"type": "file_tail",   "label": "heartbeat content",  "path": "data/task_runner/heartbeat.txt"},
            {"type": "file_tail",   "label": "watchdog log",       "path": "data/task_runner/bob-watchdog.log"},
        ],
        "Run: launchctl list | grep task-runner; if stopped, launchctl load ~/Library/LaunchAgents/com.symphony.task-runner.plist",
    ),
    (
        re.compile(r"log.*prun|prun.*log|network.guard.err|truncat", re.I),
        "Log file has not been pruned; disk space may be wasted.",
        [
            {"type": "file_stat",   "label": "file size",          "path": "logs/network-guard.err"},
        ],
        "Run: cp /dev/null logs/network-guard.err  (safe — guard is healthy, only pre-fix tracebacks remain)",
    ),
    (
        re.compile(r"plist.*launchagent|launchagent.*plist|dropout.*copy|copy.*plist", re.I),
        "LaunchAgent plist not copied to ~/Library/LaunchAgents/ for standard visibility.",
        [
            {"type": "file_stat",   "label": "setup plist",        "path": "setup/launchd/com.symphony.network-dropout-watch.plist"},
        ],
        "Run: cp setup/launchd/com.symphony.network-dropout-watch.plist ~/Library/LaunchAgents/",
    ),
]

_DEFAULT_HYPOTHESIS = "Gate requires review; no specific pattern matched."
_DEFAULT_FIX = "Review gate context and determine the appropriate action manually."


def _collect_evidence(sources: list[dict], repo: Path) -> list[dict[str, Any]]:
    """Gather bounded evidence from each source descriptor. Never raises."""
    results: list[dict[str, Any]] = []
    for src in sources:
        kind = src.get("type", "")
        label = src.get("label", kind)
        try:
            if kind == "file_tail":
                p = repo / src["path"]
                if p.is_file() and p.stat().st_size <= _MAX_FILE_BYTES * 3:
                    lines = p.read_text(errors="replace").splitlines()
                    tail = lines[-_MAX_LOG_LINES:]
                    results.append({"type": kind, "label": label, "source": str(p),
                                    "content": "\n".join(tail), "lines": len(tail)})
                elif p.is_file():
                    results.append({"type": kind, "label": label, "source": str(p),
                                    "content": f"(file too large: {p.stat().st_size} bytes — skipped)"})
                else:
                    results.append({"type": kind, "label": label, "source": str(p), "content": "file not found"})

            elif kind == "file_stat":
                p = repo / src["path"]
                if p.is_file():
                    st = p.stat()
                    age_min = (time.time() - st.st_mtime) / 60
                    results.append({"type": kind, "label": label, "source": str(p),
                                    "content": f"size={st.st_size}B  age={age_min:.0f}min"})
                else:
                    results.append({"type": kind, "label": label, "source": str(p), "content": "not found"})

            elif kind == "file_json":
                p = repo / src["path"]
                if p.is_file():
                    raw = p.read_text(errors="replace")[:_MAX_FILE_BYTES]
                    try:
                        parsed = json.loads(raw)
                        results.append({"type": kind, "label": label, "source": str(p), "content": parsed})
                    except Exception:
                        results.append({"type": kind, "label": label, "source": str(p), "content": raw[:300]})
                else:
                    results.append({"type": kind, "label": label, "source": str(p), "content": "not found"})

            elif kind == "db_count":
                conn = sqlite3.connect(str(_CORTEX_DB), timeout=2)
                row = conn.execute(src["query"]).fetchone()
                conn.close()
                results.append({"type": kind, "label": label, "content": int(row[0]) if row else 0})

            elif kind == "env_flag":
                flag = src["label"]
                val = os.environ.get(flag, "(not set)")
                results.append({"type": kind, "label": flag, "content": val})

            elif kind == "docker_ps":
                import subprocess
                out = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                    capture_output=True, text=True, timeout=5
                ).stdout.strip()
                results.append({"type": kind, "label": label, "content": out or "(no output)"})

            elif kind == "health_url":
                resp = httpx.get(src["url"], timeout=3)
                body = resp.json() if resp.status_code == 200 else resp.text[:200]
                results.append({"type": kind, "label": label, "source": src["url"], "content": body})

        except Exception as exc:
            results.append({"type": kind, "label": label, "content": f"error: {exc!s:.120}"})
    return results


def _derive_confidence(evidence: list[dict]) -> float:
    """Estimate confidence 0–1 based on how much evidence was gathered."""
    if not evidence:
        return 0.1
    found = sum(1 for e in evidence if "not found" not in str(e.get("content", ""))
                and "error:" not in str(e.get("content", "")))
    return min(0.9, 0.3 + 0.15 * found)


def investigate_gate(gate: "HumanGate", repo: Path) -> Investigation:
    """Produce a structured investigation report for one AUTO_REVIEW gate."""
    text = gate.excerpt + " " + gate.source
    hypothesis = _DEFAULT_HYPOTHESIS
    sources: list[dict] = []
    fix = _DEFAULT_FIX

    for pattern, hyp, srcs, proposed in _INVESTIGATION_RULES:
        if pattern.search(text):
            hypothesis = hyp
            sources = srcs
            fix = proposed
            break

    evidence = _collect_evidence(sources, repo)
    confidence = _derive_confidence(evidence)
    status = "complete" if evidence else "no_evidence"

    return Investigation(
        gate_excerpt=gate.excerpt[:200],
        gate_source=gate.source,
        root_cause_hypothesis=hypothesis,
        evidence=evidence,
        proposed_fix=fix,
        confidence=confidence,
        investigated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
    )


class InvestigationCache:
    """Thread-safe in-memory cache for investigation results with TTL."""

    def __init__(self, ttl: float = _INV_CACHE_TTL) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, Investigation]] = {}

    def _key(self, gate: "HumanGate") -> str:
        return f"{gate.source}::{gate.excerpt[:80]}"

    def get(self, gate: "HumanGate") -> Investigation | None:
        key = self._key(gate)
        entry = self._store.get(key)
        if entry and (time.time() - entry[0]) < self._ttl:
            return entry[1]
        return None

    def put(self, gate: "HumanGate", inv: Investigation) -> None:
        self._store[self._key(gate)] = (time.time(), inv)

    def all(self) -> list[Investigation]:
        now = time.time()
        return [inv for ts, inv in self._store.values() if (now - ts) < self._ttl]

    def clear_stale(self) -> None:
        now = time.time()
        self._store = {k: v for k, v in self._store.items() if (now - v[0]) < self._ttl}


_investigation_cache = InvestigationCache()


async def run_investigations(gates: list["HumanGate"], repo: Path) -> list[Investigation]:
    """Run investigate_gate for each AUTO_REVIEW gate, using cache."""
    auto_review = [g for g in gates if g.action_class == "AUTO_REVIEW"]
    results: list[Investigation] = []
    loop = asyncio.get_event_loop()
    for gate in auto_review:
        cached = _investigation_cache.get(gate)
        if cached:
            results.append(cached)
            continue
        inv = await loop.run_in_executor(None, investigate_gate, gate, repo)
        _investigation_cache.put(gate, inv)
        results.append(inv)
    return results


def register_autonomy_routes(app: FastAPI) -> None:
    """Mount GET /api/autonomy/overview and GET /api/autonomy/investigations."""
    assessor = AutonomyAssessor()

    @app.get("/api/autonomy/overview", tags=["autonomy"])
    async def autonomy_overview() -> dict[str, Any]:
        """Return the full autonomy control plane snapshot as JSON."""
        try:
            overview = await assessor.assess()
            data = asdict(overview)
            # Kick off investigations for AUTO_REVIEW gates (non-blocking — results cached)
            asyncio.create_task(run_investigations(overview.human_gates, REPO))
            return data
        except Exception as exc:
            logger.error("autonomy_overview_error err=%s", exc)
            return {
                "error": str(exc),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "fail",
            }

    @app.get("/api/autonomy/investigations", tags=["autonomy"])
    async def autonomy_investigations() -> dict[str, Any]:
        """Return cached investigation reports for AUTO_REVIEW gates."""
        try:
            # Also trigger fresh investigations on direct call
            overview = await assessor.assess()
            invs = await run_investigations(overview.human_gates, REPO)
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(invs),
                "investigations": [asdict(i) for i in invs],
            }
        except Exception as exc:
            logger.error("autonomy_investigations_error err=%s", exc)
            return {
                "error": str(exc),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count": 0,
                "investigations": [],
            }
