"""
preprocessor.py — Core processing logic for Auto-28 Context Preprocessor.

Pipeline:
  1. ANSI stripping
  2. Whitespace normalization
  3. Smart truncation (>100 lines)
  4. Format detection
  5. Docker/structlog-specific extraction (with deduplication)
  6. Prompt wrapping
"""

import re
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 1. ANSI stripping
# ---------------------------------------------------------------------------

_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text."""
    return _ANSI_ESCAPE.sub('', text)


# ---------------------------------------------------------------------------
# 2. Whitespace normalization
# ---------------------------------------------------------------------------

def normalize_whitespace(text: str) -> str:
    """
    - Strip trailing whitespace from every line.
    - Collapse runs of 3+ blank lines down to a single blank line.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        if line == '':
            blank_run += 1
            if blank_run <= 1:
                normalized.append('')
        else:
            blank_run = 0
            normalized.append(line)
    # Strip leading/trailing blank lines from the whole block
    while normalized and normalized[0] == '':
        normalized.pop(0)
    while normalized and normalized[-1] == '':
        normalized.pop()
    return '\n'.join(normalized)


# ---------------------------------------------------------------------------
# 3. Smart truncation
# ---------------------------------------------------------------------------

_SIGNAL_PATTERN = re.compile(
    r'(error|warning|warn|fail|failed|failure|success|succeeded|traceback|exception|critical|fatal)',
    re.IGNORECASE,
)

TRUNCATION_THRESHOLD = 100
HEAD_LINES = 10
TAIL_LINES = 10


def smart_truncate(lines: list[str]) -> tuple[list[str], int]:
    """
    If len(lines) > TRUNCATION_THRESHOLD:
      - Keep first HEAD_LINES
      - Keep last TAIL_LINES
      - From the middle, keep only signal lines (error/warning/fail/etc.)
      - Insert a placeholder indicating how many lines were trimmed.

    Returns (processed_lines, trimmed_count).
    """
    if len(lines) <= TRUNCATION_THRESHOLD:
        return lines, 0

    head = lines[:HEAD_LINES]
    tail = lines[-TAIL_LINES:]
    middle = lines[HEAD_LINES:-TAIL_LINES]

    signal_lines = [l for l in middle if _SIGNAL_PATTERN.search(l)]
    trimmed = len(middle) - len(signal_lines)

    result = head[:]
    if trimmed > 0:
        result.append(f'[...{trimmed} lines trimmed...]')
    result.extend(signal_lines)
    result.append('')  # separator
    result.extend(tail)
    return result, trimmed


# ---------------------------------------------------------------------------
# 4. Format detection
# ---------------------------------------------------------------------------

@dataclass
class FormatHints:
    name: str
    confidence: float


def detect_format(text: str, lines: list[str]) -> str:
    """
    Detect the format of the input text.
    Returns a human-readable label string.
    """
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return 'general text'

    scores: dict[str, float] = {
        'JSON': 0,
        'Python traceback': 0,
        'Docker logs': 0,
        'git output': 0,
        'email': 0,
        'terminal output': 0,
        'general text': 0,
    }

    # JSON
    stripped = text.strip()
    if stripped.startswith(('{', '[', '"')):
        try:
            json.loads(stripped)
            scores['JSON'] += 10
        except json.JSONDecodeError:
            pass
    # Multiline JSON-per-line (structlog/docker)
    json_line_count = 0
    for l in non_empty[:20]:
        try:
            obj = json.loads(l.strip())
            if isinstance(obj, dict):
                json_line_count += 1
        except Exception:
            pass
    if json_line_count >= 3:
        scores['Docker logs'] += json_line_count * 1.5

    # Python traceback
    if any('Traceback (most recent call last)' in l for l in lines):
        scores['Python traceback'] += 10
    if any(re.match(r'\s+File ".*", line \d+', l) for l in lines):
        scores['Python traceback'] += 5

    # Docker logs — timestamps + container patterns
    docker_ts = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}')
    ts_count = sum(1 for l in non_empty[:30] if docker_ts.search(l))
    if ts_count >= 3:
        scores['Docker logs'] += ts_count * 0.8

    # git output
    git_patterns = [
        r'^(commit [0-9a-f]{40})',
        r'^(diff --git)',
        r'^(\+\+\+|---) [ab]/',
        r'^@@.*@@',
        r'^(Author|Date): ',
        r'^(On branch|HEAD detached)',
        r'^(Your branch|Changes|Untracked)',
    ]
    git_matches = sum(
        1 for l in lines
        if any(re.match(p, l) for p in git_patterns)
    )
    if git_matches >= 2:
        scores['git output'] += git_matches * 2

    # email
    email_headers = ['From:', 'To:', 'Subject:', 'Date:', 'Cc:', 'Reply-To:', 'Message-ID:']
    header_count = sum(1 for l in lines[:20] if any(l.startswith(h) for h in email_headers))
    if header_count >= 2:
        scores['email'] += header_count * 3

    # terminal output — prompts, commands, shell artifacts
    terminal_patterns = [
        r'^\$\s+\S',
        r'^#\s+\S',
        r'^(root|user|ubuntu|admin|bob)@\S+',
        r'^>>> ',         # Python REPL
        r'^\(venv\)',
        r'^\[\d+\]',     # zsh history
    ]
    term_count = sum(
        1 for l in lines
        if any(re.match(p, l) for p in terminal_patterns)
    )
    if term_count >= 1:
        scores['terminal output'] += term_count * 2

    # Bump terminal if many lines look like command output
    if len(non_empty) > 5 and scores['terminal output'] == 0:
        scores['terminal output'] += 1  # slight prior

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return 'general text'
    return best


# ---------------------------------------------------------------------------
# 5. Docker / structlog specific processing
# ---------------------------------------------------------------------------

def process_docker_logs(lines: list[str]) -> list[str]:
    """
    For JSON-per-line structlog format:
    - Parse each line as JSON dict.
    - Extract: event, level, timestamp, error fields.
    - Deduplicate repeated events (show count).
    - Fall back to raw line if not parseable.
    """
    KEEP_FIELDS = {'event', 'level', 'severity', 'timestamp', 'time', 'ts',
                   'error', 'err', 'exception', 'msg', 'message'}

    event_counter: Counter = Counter()
    parsed_entries: list[dict] = []
    raw_lines: list[str] = []
    is_structlog = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            if not isinstance(obj, dict):
                raw_lines.append(line)
                continue
            is_structlog = True
            # Extract relevant fields only
            entry = {k: v for k, v in obj.items() if k in KEEP_FIELDS}
            # Build a dedup key from event + level
            event = str(obj.get('event', obj.get('msg', obj.get('message', ''))))
            level = str(obj.get('level', obj.get('severity', '')))
            key = f'{level}|{event}'
            event_counter[key] += 1
            if event_counter[key] == 1:
                parsed_entries.append(entry)
            else:
                # Update count on first occurrence marker
                pass
        except (json.JSONDecodeError, ValueError):
            raw_lines.append(line)

    if not is_structlog:
        return lines  # Nothing parsed, return unchanged

    result: list[str] = []
    seen_keys: dict[str, int] = {}
    entry_index = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            if not isinstance(obj, dict):
                result.append(line)
                continue
            event = str(obj.get('event', obj.get('msg', obj.get('message', ''))))
            level = str(obj.get('level', obj.get('severity', '')))
            key = f'{level}|{event}'
            count = event_counter[key]
            if key not in seen_keys:
                seen_keys[key] = 1
                entry = {k: v for k, v in obj.items() if k in KEEP_FIELDS}
                line_repr = json.dumps(entry, separators=(', ', '='))
                # Reformat as readable key=value
                parts = [f'{k}={v}' for k, v in entry.items()]
                line_out = '  '.join(parts)
                if count > 1:
                    line_out += f'  [×{count}]'
                result.append(line_out)
        except (json.JSONDecodeError, ValueError):
            result.append(line)

    # Append any fully non-JSON raw lines at the end
    if raw_lines and not is_structlog:
        result.extend(raw_lines)

    return result


# ---------------------------------------------------------------------------
# 6. Prompt wrapping
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
Context: {format_type}
---
{content}
---
Task: \
"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@dataclass
class ProcessResult:
    output: str
    format_type: str
    input_chars: int
    output_chars: int
    input_lines: int
    output_lines: int
    trimmed_lines: int
    reduction_pct: float


def process(raw_text: str) -> ProcessResult:
    """
    Full pipeline: strip → normalize → detect → truncate/docker → wrap.
    Returns a ProcessResult with the cleaned prompt and metadata.
    """
    input_chars = len(raw_text)

    # Step 1: ANSI stripping
    text = strip_ansi(raw_text)

    # Step 2: Whitespace normalization
    text = normalize_whitespace(text)

    # Work with lines from here
    lines = text.splitlines()
    input_lines = len(lines)

    # Step 4: Format detection (before truncation, on full content)
    fmt = detect_format(text, lines)

    # Step 5: Docker-specific processing (before truncation)
    if fmt == 'Docker logs':
        lines = process_docker_logs(lines)
        text = '\n'.join(lines)

    # Step 3: Smart truncation
    lines, trimmed = smart_truncate(lines)
    content = '\n'.join(lines)

    # Step 6: Prompt wrapping
    output = PROMPT_TEMPLATE.format(format_type=fmt, content=content)

    output_chars = len(output)
    output_lines = len(output.splitlines())
    reduction_pct = round((1 - output_chars / input_chars) * 100, 1) if input_chars > 0 else 0.0

    return ProcessResult(
        output=output,
        format_type=fmt,
        input_chars=input_chars,
        output_chars=output_chars,
        input_lines=input_lines,
        output_lines=output_lines,
        trimmed_lines=trimmed,
        reduction_pct=reduction_pct,
    )
