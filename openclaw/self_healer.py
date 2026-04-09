"""
Self-Healing Code Pipeline
==========================
Monitors log files and Docker container logs for Python exceptions.
When a new error is detected:
  1. Extracts structured error context.
  2. Calls OpenAI GPT-4o for a minimal fix.
  3. Writes a Cursor prompt to .cursor/prompts/auto-fix-{timestamp}.md
  4. Creates a Linear issue with the fix.
  5. Sends an iMessage notification via notify_fn.

Error dedup: each unique fingerprint is stored in SQLite `error_log`.
The same fingerprint is not re-processed within 24 hours.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("openclaw.self_healer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURSOR_PROMPTS_DIR = Path(__file__).parent.parent / ".cursor" / "prompts"
DB_PATH = os.getenv("HEALER_DB_PATH", "/data/healer.db")
DEDUP_HOURS = 24

# Regex patterns for Python tracebacks
_TB_START = re.compile(r"Traceback \(most recent call last\):")
_FILE_LINE = re.compile(
    r'File "(?P<filepath>[^"]+)", line (?P<lineno>\d+), in (?P<func>\S+)'
)
_ERROR_LINE = re.compile(
    r"^(?P<etype>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*Error[^\s]*|"
    r"[A-Za-z][A-Za-z0-9_]*Exception[^\s]*|KeyboardInterrupt|SystemExit|"
    r"StopIteration|GeneratorExit|[A-Za-z][A-Za-z0-9_]*Warning):\s*(?P<msg>.*)$"
)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_log (
                fingerprint TEXT PRIMARY KEY,
                first_seen  TEXT NOT NULL,
                count       INT  NOT NULL DEFAULT 1,
                last_fix    TEXT
            )
        """)
        conn.commit()


def _is_known_recent(db_path: str, fingerprint: str) -> bool:
    """Return True if fingerprint was processed within the last 24 hours."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)
    ).isoformat()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT first_seen FROM error_log WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
    if row is None:
        return False
    return row[0] >= cutoff


def _record_error(db_path: str, fingerprint: str, fix: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO error_log (fingerprint, first_seen, count, last_fix)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(fingerprint) DO UPDATE SET
                   count    = count + 1,
                   first_seen = excluded.first_seen,
                   last_fix   = excluded.last_fix""",
            (fingerprint, now, fix),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# SelfHealer
# ---------------------------------------------------------------------------


class SelfHealer:
    """
    Monitors log files for new Python exceptions and auto-generates fixes.

    Parameters
    ----------
    log_paths : list[str]
        Paths to log files to monitor (e.g. ["/tmp/bob-healthcheck.log"]).
        Docker container log output is fetched separately via `docker logs`.
    openai_api_key : str
        OpenAI API key. If empty, fix generation is skipped.
    linear_sync : optional
        A LinearSync (or compatible) instance used to create issues.
    notify_fn : optional
        Async callable(message: str) used to send iMessage/notification.
    db_path : str
        SQLite path for error dedup. Defaults to HEALER_DB_PATH env var.
    docker_containers : list[str]
        Docker container names/IDs to read logs from. Defaults to [].
    """

    def __init__(
        self,
        log_paths: list[str],
        openai_api_key: str,
        linear_sync: Any = None,
        notify_fn: Optional[Callable] = None,
        db_path: str = DB_PATH,
        docker_containers: Optional[list[str]] = None,
    ) -> None:
        self._log_paths = log_paths
        self._api_key = openai_api_key
        self._linear = linear_sync
        self._notify_fn = notify_fn
        self._db_path = db_path
        self._docker_containers: list[str] = docker_containers or []

        _init_db(self._db_path)
        CURSOR_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "SelfHealer initialised | log_paths=%s containers=%s",
            self._log_paths,
            self._docker_containers,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def tick(self) -> int:
        """
        Run one healing cycle.

        Returns
        -------
        int
            Number of new (non-duplicate) errors processed.
        """
        all_content: list[str] = []

        # 1. Read file-based logs
        for path in self._log_paths:
            try:
                text = Path(path).read_text(errors="replace")
                all_content.append(text)
            except FileNotFoundError:
                logger.debug("Log file not found: %s", path)
            except OSError as exc:
                logger.warning("Cannot read log %s: %s", path, exc)

        # 2. Read Docker container logs (last 200 lines each)
        for container in self._docker_containers:
            docker_out = self._read_docker_logs(container)
            if docker_out:
                all_content.append(docker_out)

        combined = "\n".join(all_content)
        if not combined.strip():
            return 0

        errors = await self._parse_errors(combined)
        processed = 0

        for error in errors:
            fp = self._error_fingerprint(error)
            if _is_known_recent(self._db_path, fp):
                logger.debug("Skipping known recent error: %s", fp)
                continue

            logger.info(
                "New error detected: %s in %s:%s",
                error.get("error_type"),
                error.get("filepath"),
                error.get("lineno"),
            )

            fix = await self._generate_fix(error)
            prompt_path = await self._write_cursor_prompt(error, fix)
            await self._create_linear_issue(error, fix)
            await self._send_notification(error)

            _record_error(self._db_path, fp, fix)
            processed += 1
            logger.info("Processed error %s → prompt: %s", fp, prompt_path)

        return processed

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    async def _parse_errors(self, log_content: str) -> list[dict]:
        """
        Extract structured error dicts from log content.

        Each dict contains:
          filepath, lineno, func, error_type, error_message,
          context_lines (list[str]), raw_traceback (str)
        """
        errors: list[dict] = []
        lines = log_content.splitlines()
        i = 0
        while i < len(lines):
            if _TB_START.search(lines[i]):
                # Collect the whole traceback block
                tb_lines = [lines[i]]
                j = i + 1
                last_file_match: Optional[re.Match] = None
                error_type = ""
                error_message = ""

                while j < len(lines):
                    line = lines[j]
                    tb_lines.append(line)

                    fm = _FILE_LINE.search(line)
                    if fm:
                        last_file_match = fm

                    em = _ERROR_LINE.match(line.strip())
                    if em:
                        error_type = em.group("etype")
                        error_message = em.group("msg")
                        j += 1
                        break

                    # End of traceback if blank line or next Traceback
                    if line.strip() == "" or _TB_START.search(line):
                        break
                    j += 1

                if not error_type:
                    i = j
                    continue

                filepath = ""
                lineno = 0
                func = ""
                if last_file_match:
                    filepath = last_file_match.group("filepath")
                    lineno = int(last_file_match.group("lineno"))
                    func = last_file_match.group("func")

                context_lines = self._read_source_context(filepath, lineno)

                errors.append({
                    "filepath": filepath,
                    "lineno": lineno,
                    "func": func,
                    "error_type": error_type,
                    "error_message": error_message,
                    "context_lines": context_lines,
                    "raw_traceback": "\n".join(tb_lines),
                })
                i = j
            else:
                i += 1

        return errors

    async def _generate_fix(self, error: dict) -> str:
        """
        Call OpenAI GPT-4o for a minimal fix.
        Returns the suggested fix as a string.
        Falls back to empty string if API key is missing or call fails.
        """
        if not self._api_key:
            logger.warning("OpenAI API key not set — skipping fix generation")
            return ""

        try:
            import openai  # type: ignore
        except ImportError:
            logger.warning("openai package not installed — skipping fix generation")
            return ""

        context_str = "\n".join(error.get("context_lines") or [])
        prompt = (
            f"Here is a Python error in our production system. "
            f"Write a minimal fix. Return only the corrected code snippet.\n\n"
            f"Error type: {error['error_type']}\n"
            f"Error message: {error['error_message']}\n"
            f"File: {error['filepath']}, line {error['lineno']}, in {error['func']}\n\n"
            f"Surrounding code context:\n```python\n{context_str}\n```\n\n"
            f"Full traceback:\n```\n{error['raw_traceback']}\n```"
        )

        try:
            client = openai.AsyncOpenAI(api_key=self._api_key)
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            fix: str = response.choices[0].message.content or ""
            return fix.strip()
        except Exception as exc:
            logger.error("OpenAI fix generation failed: %s", exc)
            return ""

    async def _write_cursor_prompt(self, error: dict, fix: str) -> str:
        """
        Write an auto-fix Cursor prompt to .cursor/prompts/.

        Returns
        -------
        str
            Absolute path to the written prompt file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"auto-fix-{timestamp}.md"
        prompt_path = CURSOR_PROMPTS_DIR / filename

        context_str = "\n".join(error.get("context_lines") or [])
        content = f"""# Auto-Fix: {error['error_type']} in {Path(error['filepath']).name}

> Generated by SelfHealer at {timestamp} UTC

## Error Details

| Field | Value |
|-------|-------|
| **Error Type** | `{error['error_type']}` |
| **Message** | {error['error_message']} |
| **File** | `{error['filepath']}` |
| **Line** | {error['lineno']} |
| **Function** | `{error['func']}` |

## Full Traceback

```
{error['raw_traceback']}
```

## Source Context

```python
{context_str}
```

## Suggested Fix

```python
{fix}
```

## Instructions

1. Review the suggested fix above.
2. Apply the change to `{error['filepath']}` around line {error['lineno']}.
3. Run tests to confirm the fix.
4. Close the corresponding Linear issue once deployed.
"""
        try:
            prompt_path.write_text(content, encoding="utf-8")
            logger.info("Cursor prompt written: %s", prompt_path)
        except OSError as exc:
            logger.error("Failed to write Cursor prompt: %s", exc)

        return str(prompt_path)

    async def _create_linear_issue(self, error: dict, fix: str) -> None:
        """Create a Linear issue with the error context and suggested fix."""
        if self._linear is None:
            logger.debug("No linear_sync provided — skipping Linear issue creation")
            return

        filename = Path(error.get("filepath") or "unknown").name
        title = f"[Auto-Fix] {error['error_type']} in {filename}"
        description = (
            f"**Detected by SelfHealer**\n\n"
            f"**Error:** `{error['error_type']}: {error['error_message']}`\n"
            f"**File:** `{error['filepath']}` line {error['lineno']}\n"
            f"**Function:** `{error['func']}`\n\n"
            f"### Traceback\n```\n{error['raw_traceback']}\n```\n\n"
            f"### Suggested Fix\n```python\n{fix}\n```"
        )

        try:
            # LinearSync.create_issue(title, description) or similar
            create_fn = getattr(self._linear, "create_issue", None)
            if callable(create_fn):
                await create_fn(title=title, description=description)
                logger.info("Linear issue created: %s", title)
            else:
                logger.warning(
                    "linear_sync has no create_issue method — skipping"
                )
        except Exception as exc:
            logger.error("Failed to create Linear issue: %s", exc)

    def _error_fingerprint(self, error: dict) -> str:
        """
        Return a stable 16-char hex hash for dedup.
        Based on: error_type + filepath + lineno (ignores message churn).
        """
        key = f"{error.get('error_type')}|{error.get('filepath')}|{error.get('lineno')}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_notification(self, error: dict) -> None:
        """Send iMessage via notify_fn if configured."""
        if self._notify_fn is None:
            return
        filename = Path(error.get("filepath") or "unknown").name
        message = (
            f"Bob: Auto-fix ready for {error['error_type']} in {filename} "
            f"— check Linear for details"
        )
        try:
            await self._notify_fn(message)
        except Exception as exc:
            logger.warning("notify_fn failed: %s", exc)

    @staticmethod
    def _read_source_context(filepath: str, lineno: int, radius: int = 8) -> list[str]:
        """Return `radius` lines of source code around `lineno`."""
        if not filepath:
            return []
        try:
            source_lines = Path(filepath).read_text(errors="replace").splitlines()
            start = max(0, lineno - radius - 1)
            end = min(len(source_lines), lineno + radius)
            context = []
            for idx, line in enumerate(source_lines[start:end], start=start + 1):
                marker = ">>>" if idx == lineno else "   "
                context.append(f"{marker} {idx:4d} | {line}")
            return context
        except OSError:
            return []

    @staticmethod
    def _read_docker_logs(container: str, tail: int = 200) -> str:
        """Fetch the last `tail` lines from a Docker container's logs."""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(tail), container],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout + result.stderr
        except FileNotFoundError:
            logger.debug("docker binary not found — cannot read container logs")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning("Timed out reading logs from container: %s", container)
            return ""
        except OSError as exc:
            logger.warning("Error reading Docker logs for %s: %s", container, exc)
            return ""
