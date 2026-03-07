#!/usr/bin/env python3
"""
cortex_curator.py - Curate Cortex facts with dedupe, confidence, contradiction checks,
and smart-home professional reasoning/troubleshooting signals.

Pipeline:
1) Read markdown under knowledge/cortex/
2) Extract fact-like lines
3) Deduplicate into SQLite facts table
4) Flag contradictions (same subject, conflicting numeric values)
5) Score confidence using Outline Creator principles:
   - Domain specificity
   - Reasoning quality
   - Troubleshooting usefulness
6) Promote to trusted/review

Usage:
    python3 tools/cortex_curator.py --run --json
    python3 tools/cortex_curator.py --status
    python3 tools/cortex_curator.py --run --limit 20 --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CORTEX_DIR = BASE_DIR / "knowledge" / "cortex"
DB_PATH = BASE_DIR / "data" / "cortex_curator.db"

SKIP_DIR_NAMES = {"connections"}
MIN_FACT_LEN = 24
MAX_FACT_LEN = 350
MIN_FACT_WORDS = 6
MAX_FACT_WORDS = 60
MIN_CANDIDATE_PROFESSIONAL_SCORE = 0.25
DEFAULT_MIN_REVIEW_PROFESSIONAL_SCORE = 0.25

# Outline Creator foundation: teach smart-home professional thinking.
# We score facts for domain relevance, reasoning quality, and troubleshooting utility.
DOMAIN_KEYWORDS = {
    "control4", "lutron", "sonos", "zigbee", "zwave", "vlan", "poe", "edid",
    "hdmi", "audio", "video", "amplifier", "keypad", "processor", "driver",
    "network", "latency", "onnvif", "onvif", "pre-amp", "preamp", "relay",
}
REASONING_PATTERNS = {
    "because", "therefore", "so that", "which means", "tradeoff", "if", "then",
    "when", "unless", "depends", "due to", "root cause",
}
TROUBLESHOOTING_PATTERNS = {
    "check", "verify", "test", "reboot", "restart", "ping", "logs", "symptom",
    "failure", "timeout", "offline", "no signal", "fallback", "isolate",
    "diagnose", "step", "first", "next", "last",
}


def now_iso() -> str:
    return datetime.now().isoformat()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            content_hash TEXT,
            mtime REAL,
            last_indexed TEXT
        );

        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_text TEXT NOT NULL UNIQUE,
            representative_text TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 1,
            contradiction_count INTEGER NOT NULL DEFAULT 0,
            domain_score REAL NOT NULL DEFAULT 0.0,
            reasoning_score REAL NOT NULL DEFAULT 0.0,
            troubleshooting_score REAL NOT NULL DEFAULT 0.0,
            confidence REAL NOT NULL DEFAULT 0.45,
            status TEXT NOT NULL DEFAULT 'review',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(fact_id, source_id, raw_text),
            FOREIGN KEY(fact_id) REFERENCES facts(id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS contradictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id_a INTEGER NOT NULL,
            fact_id_b INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(fact_id_a, fact_id_b, reason),
            FOREIGN KEY(fact_id_a) REFERENCES facts(id),
            FOREIGN KEY(fact_id_b) REFERENCES facts(id)
        );

        CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_key);
        CREATE INDEX IF NOT EXISTS idx_fact_sources_fact_id ON fact_sources(fact_id);
        """
    )
    # Lightweight migration for existing DBs.
    for col in ("domain_score", "reasoning_score", "troubleshooting_score"):
        try:
            conn.execute(f"ALTER TABLE facts ADD COLUMN {col} REAL NOT NULL DEFAULT 0.0")
        except sqlite3.OperationalError:
            pass
    conn.commit()


def get_cortex_markdown_files() -> list[Path]:
    if not CORTEX_DIR.exists():
        return []

    files: list[Path] = []
    for fpath in CORTEX_DIR.rglob("*.md"):
        if any(skip in fpath.parts for skip in SKIP_DIR_NAMES):
            continue
        files.append(fpath)
    return sorted(files)


def file_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def canonicalize(text: str) -> str:
    txt = text.lower().strip()
    txt = re.sub(r"[`*_~\[\]()]", "", txt)
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r"\s*([,:;.!?])\s*", r"\1 ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def subject_key(text: str) -> str:
    txt = canonicalize(text)
    txt = re.sub(r"[^a-z0-9\s-]", "", txt)
    words = [w for w in txt.split() if w]
    if not words:
        return "unknown"
    return " ".join(words[:6])


def extract_numbers(text: str) -> list[float]:
    nums: list[float] = []
    for m in re.findall(r"\b\d+(?:\.\d+)?\b", text):
        try:
            nums.append(float(m))
        except ValueError:
            continue
    return nums


def extract_fact_candidates(content: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("http://") or line.startswith("https://"):
            continue
        # Skip markdown table rows/separators and obvious formatting lines.
        if line.startswith("|") or re.match(r"^\|?[-:\s|]+\|?$", line):
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        if line.startswith("*") and line.endswith("*"):
            continue

        line = re.sub(r"^[-*•]\s+", "", line).strip()
        if not line or line.endswith(":"):
            continue

        if len(line) < MIN_FACT_LEN:
            continue

        parts = re.split(r"(?<=[.!?])\s+", line)
        for part in parts:
            sentence = part.strip()
            if len(sentence) < MIN_FACT_LEN:
                continue
            if len(sentence) > MAX_FACT_LEN:
                continue
            if sentence.startswith("http://") or sentence.startswith("https://"):
                continue
            # Skip code/config-ish fragments.
            if any(sym in sentence for sym in ("{", "}", "=>", "();", "import ", "SELECT ", "FROM ")):
                continue
            alpha_words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", sentence)
            if len(alpha_words) < MIN_FACT_WORDS or len(alpha_words) > MAX_FACT_WORDS:
                continue
            alpha_chars = len(re.findall(r"[A-Za-z]", sentence))
            ratio = alpha_chars / max(len(sentence), 1)
            if ratio < 0.55:
                continue
            domain_score, reasoning_score, troubleshooting_score = professional_signal_scores(sentence)
            if (domain_score + reasoning_score + troubleshooting_score) < MIN_CANDIDATE_PROFESSIONAL_SCORE:
                continue
            key = canonicalize(sentence)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(sentence)

    return candidates


def professional_signal_scores(text: str) -> tuple[float, float, float]:
    """Score a fact by smart-home domain, reasoning, and troubleshooting depth."""
    lower = canonicalize(text)

    domain_hits = sum(1 for k in DOMAIN_KEYWORDS if k in lower)
    reasoning_hits = sum(1 for k in REASONING_PATTERNS if re.search(rf"\b{re.escape(k)}\b", lower))
    troubleshoot_hits = sum(1 for k in TROUBLESHOOTING_PATTERNS if re.search(rf"\b{re.escape(k)}\b", lower))

    domain_score = min(1.0, domain_hits / 4.0)
    reasoning_score = min(1.0, reasoning_hits / 3.0)
    troubleshooting_score = min(1.0, troubleshoot_hits / 3.0)
    return round(domain_score, 3), round(reasoning_score, 3), round(troubleshooting_score, 3)


def confidence_for(
    source_count: int,
    contradiction_count: int,
    domain_score: float = 0.0,
    reasoning_score: float = 0.0,
    troubleshooting_score: float = 0.0,
) -> tuple[float, str]:
    # Base trust from corroboration and contradiction handling.
    score = 0.40 + min(max(source_count - 1, 0), 4) * 0.12 - contradiction_count * 0.25
    # Outline Creator mindset boost: reward professional quality of thought.
    score += (domain_score * 0.10) + (reasoning_score * 0.08) + (troubleshooting_score * 0.10)
    score = max(0.05, min(0.99, score))
    status = "trusted" if (score >= 0.85 and contradiction_count == 0 and source_count >= 2) else "review"
    return round(score, 3), status


def is_numeric_contradiction(a: str, b: str) -> bool:
    nums_a = extract_numbers(a)
    nums_b = extract_numbers(b)
    if not nums_a or not nums_b:
        return False

    set_a = {round(n, 4) for n in nums_a}
    set_b = {round(n, 4) for n in nums_b}
    return set_a.isdisjoint(set_b)


def source_row(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE path = ?", (path,)).fetchone()


def ensure_source(conn: sqlite3.Connection, path: str, mtime: float, content_hash: str) -> int:
    row = source_row(conn, path)
    now = now_iso()
    if row is None:
        cur = conn.execute(
            "INSERT INTO sources(path, content_hash, mtime, last_indexed) VALUES (?, ?, ?, ?)",
            (path, content_hash, mtime, now),
        )
        return int(cur.lastrowid)

    conn.execute(
        "UPDATE sources SET content_hash = ?, mtime = ?, last_indexed = ? WHERE id = ?",
        (content_hash, mtime, now, int(row["id"])),
    )
    return int(row["id"])


def upsert_fact(conn: sqlite3.Connection, raw_text: str, source_id: int) -> tuple[int, bool]:
    canon = canonicalize(raw_text)
    s_key = subject_key(raw_text)
    now = now_iso()

    row = conn.execute("SELECT * FROM facts WHERE canonical_text = ?", (canon,)).fetchone()
    created = False

    if row is None:
        cur = conn.execute(
            """
            INSERT INTO facts(canonical_text, representative_text, subject_key, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (canon, raw_text, s_key, now, now),
        )
        fact_id = int(cur.lastrowid)
        created = True
    else:
        fact_id = int(row["id"])
        conn.execute("UPDATE facts SET last_seen = ? WHERE id = ?", (now, fact_id))

    conn.execute(
        """
        INSERT OR IGNORE INTO fact_sources(fact_id, source_id, raw_text, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (fact_id, source_id, raw_text, now),
    )

    sc = conn.execute(
        "SELECT COUNT(DISTINCT source_id) AS c FROM fact_sources WHERE fact_id = ?",
        (fact_id,),
    ).fetchone()
    source_count = int(sc["c"]) if sc else 1

    cc = conn.execute("SELECT contradiction_count FROM facts WHERE id = ?", (fact_id,)).fetchone()
    contradiction_count = int(cc["contradiction_count"]) if cc else 0

    domain_score, reasoning_score, troubleshooting_score = professional_signal_scores(raw_text)
    conf, status = confidence_for(
        source_count,
        contradiction_count,
        domain_score=domain_score,
        reasoning_score=reasoning_score,
        troubleshooting_score=troubleshooting_score,
    )
    conn.execute(
        """
        UPDATE facts
        SET source_count = ?,
            domain_score = ?,
            reasoning_score = ?,
            troubleshooting_score = ?,
            confidence = ?,
            status = ?
        WHERE id = ?
        """,
        (source_count, domain_score, reasoning_score, troubleshooting_score, conf, status, fact_id),
    )

    return fact_id, created


def maybe_record_contradictions(conn: sqlite3.Connection, fact_id: int) -> list[int]:
    changed_ids: list[int] = []

    current = conn.execute(
        "SELECT id, representative_text, subject_key FROM facts WHERE id = ?", (fact_id,)
    ).fetchone()
    if current is None:
        return changed_ids

    subject = str(current["subject_key"])
    text = str(current["representative_text"])
    if not extract_numbers(text):
        return changed_ids

    peers = conn.execute(
        "SELECT id, representative_text FROM facts WHERE subject_key = ? AND id != ?",
        (subject, fact_id),
    ).fetchall()

    for peer in peers:
        peer_id = int(peer["id"])
        peer_text = str(peer["representative_text"])
        if not is_numeric_contradiction(text, peer_text):
            continue

        a, b = sorted((fact_id, peer_id))
        try:
            conn.execute(
                """
                INSERT INTO contradictions(fact_id_a, fact_id_b, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (a, b, "numeric mismatch", now_iso()),
            )
        except sqlite3.IntegrityError:
            continue

        for fid in (fact_id, peer_id):
            conn.execute(
                "UPDATE facts SET contradiction_count = contradiction_count + 1 WHERE id = ?",
                (fid,),
            )
            changed_ids.append(fid)

    return changed_ids


def rescore_fact(conn: sqlite3.Connection, fact_id: int) -> None:
    row = conn.execute(
        """
        SELECT source_count, contradiction_count, domain_score, reasoning_score, troubleshooting_score
        FROM facts
        WHERE id = ?
        """,
        (fact_id,),
    ).fetchone()
    if row is None:
        return

    source_count = int(row["source_count"])
    contradiction_count = int(row["contradiction_count"])
    domain_score = float(row["domain_score"])
    reasoning_score = float(row["reasoning_score"])
    troubleshooting_score = float(row["troubleshooting_score"])
    conf, status = confidence_for(
        source_count,
        contradiction_count,
        domain_score=domain_score,
        reasoning_score=reasoning_score,
        troubleshooting_score=troubleshooting_score,
    )
    conn.execute(
        "UPDATE facts SET confidence = ?, status = ? WHERE id = ?",
        (conf, status, fact_id),
    )


def run_curator(limit: int | None = None, force: bool = False, contains: str | None = None) -> dict[str, Any]:
    conn = connect_db()
    init_db(conn)

    files = get_cortex_markdown_files()
    scanned = 0
    indexed = 0
    skipped = 0
    new_facts = 0
    updated_facts = 0
    affected_ids: set[int] = set()

    for fpath in files:
        rel_path = str(fpath.relative_to(BASE_DIR))
        if contains and contains.lower() not in rel_path.lower():
            continue

        scanned += 1
        if limit and indexed >= limit:
            break

        content = fpath.read_text(encoding="utf-8", errors="ignore")
        content_hash = file_sha256(content)
        mtime = fpath.stat().st_mtime

        existing = source_row(conn, rel_path)
        if existing and not force and str(existing["content_hash"] or "") == content_hash:
            skipped += 1
            continue

        source_id = ensure_source(conn, rel_path, mtime, content_hash)

        candidates = extract_fact_candidates(content)
        if not candidates:
            indexed += 1
            continue

        for candidate in candidates:
            fact_id, created = upsert_fact(conn, candidate, source_id)
            if created:
                new_facts += 1
            else:
                updated_facts += 1
            affected_ids.add(fact_id)
            for changed in maybe_record_contradictions(conn, fact_id):
                affected_ids.add(changed)

        indexed += 1

    for fact_id in affected_ids:
        rescore_fact(conn, fact_id)

    conn.commit()

    totals = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM facts) AS total_facts,
            (SELECT COUNT(*) FROM facts WHERE status = 'trusted') AS trusted_facts,
            (SELECT COUNT(*) FROM facts WHERE status = 'review') AS review_facts,
            (SELECT COUNT(*) FROM contradictions) AS contradiction_pairs,
            (SELECT COUNT(*) FROM sources) AS total_sources
        """
    ).fetchone()

    result = {
        "success": True,
        "timestamp": now_iso(),
        "outline_creator_principles": {
            "domain": "smart-home domain specificity",
            "reasoning": "cause/effect and design tradeoff quality",
            "troubleshooting": "stepwise diagnostic usefulness",
        },
        "scanned_files": scanned,
        "indexed_files": indexed,
        "skipped_unchanged": skipped,
        "new_facts": new_facts,
        "updated_facts": updated_facts,
        "total_facts": int(totals["total_facts"]) if totals else 0,
        "trusted_facts": int(totals["trusted_facts"]) if totals else 0,
        "review_facts": int(totals["review_facts"]) if totals else 0,
        "contradiction_pairs": int(totals["contradiction_pairs"]) if totals else 0,
        "total_sources": int(totals["total_sources"]) if totals else 0,
        "db_path": str(DB_PATH.relative_to(BASE_DIR)),
    }
    conn.close()
    return result


def get_curator_status() -> dict[str, Any]:
    conn = connect_db()
    init_db(conn)

    totals = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM facts) AS total_facts,
            (SELECT COUNT(*) FROM facts WHERE status = 'trusted') AS trusted_facts,
            (SELECT COUNT(*) FROM facts WHERE status = 'review') AS review_facts,
            (SELECT COUNT(*) FROM contradictions) AS contradiction_pairs,
            (SELECT COUNT(*) FROM sources) AS total_sources,
            (SELECT MAX(last_indexed) FROM sources) AS last_indexed
        """
    ).fetchone()

    top_review = conn.execute(
        """
        SELECT
            id, representative_text, confidence, source_count, contradiction_count,
            domain_score, reasoning_score, troubleshooting_score
        FROM facts
        WHERE status = 'review' AND representative_text NOT LIKE 'http%'
        ORDER BY contradiction_count DESC, confidence ASC
        LIMIT 10
        """
    ).fetchall()

    result = {
        "success": True,
        "timestamp": now_iso(),
        "outline_creator_principles": {
            "domain": "smart-home domain specificity",
            "reasoning": "cause/effect and design tradeoff quality",
            "troubleshooting": "stepwise diagnostic usefulness",
        },
        "db_path": str(DB_PATH.relative_to(BASE_DIR)),
        "total_facts": int(totals["total_facts"]) if totals else 0,
        "trusted_facts": int(totals["trusted_facts"]) if totals else 0,
        "review_facts": int(totals["review_facts"]) if totals else 0,
        "contradiction_pairs": int(totals["contradiction_pairs"]) if totals else 0,
        "total_sources": int(totals["total_sources"]) if totals else 0,
        "last_indexed": totals["last_indexed"] if totals else None,
        "review_queue": [
            {
                "id": int(r["id"]),
                "fact": str(r["representative_text"])[:180],
                "confidence": float(r["confidence"]),
                "source_count": int(r["source_count"]),
                "contradictions": int(r["contradiction_count"]),
                "domain_score": float(r["domain_score"]),
                "reasoning_score": float(r["reasoning_score"]),
                "troubleshooting_score": float(r["troubleshooting_score"]),
            }
            for r in top_review
        ],
    }
    conn.close()
    return result


def list_review_facts(
    status: str = "review",
    limit: int = 50,
    offset: int = 0,
    min_confidence: float | None = None,
    min_professional_score: float | None = DEFAULT_MIN_REVIEW_PROFESSIONAL_SCORE,
    subject_contains: str | None = None,
) -> dict[str, Any]:
    """List facts for curation queue with filters."""
    conn = connect_db()
    init_db(conn)

    where = ["status = ?", "representative_text NOT LIKE 'http%'"]
    params: list[Any] = [status]

    if min_confidence is not None:
        where.append("confidence >= ?")
        params.append(float(min_confidence))
    if min_professional_score is not None:
        where.append("(domain_score + reasoning_score + troubleshooting_score) >= ?")
        params.append(float(min_professional_score))
    if subject_contains:
        where.append("subject_key LIKE ?")
        params.append(f"%{subject_contains.lower()}%")

    where_sql = " AND ".join(where)
    count_row = conn.execute(
        f"SELECT COUNT(*) AS c FROM facts WHERE {where_sql}",
        params,
    ).fetchone()
    total = int(count_row["c"]) if count_row else 0

    rows = conn.execute(
        f"""
        SELECT
            id, representative_text, subject_key, confidence, source_count, contradiction_count,
            domain_score, reasoning_score, troubleshooting_score, status, last_seen
        FROM facts
        WHERE {where_sql}
        ORDER BY contradiction_count DESC, confidence ASC, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, int(limit), int(offset)],
    ).fetchall()

    conn.close()
    return {
        "success": True,
        "status_filter": status,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": int(r["id"]),
                "fact": str(r["representative_text"]),
                "subject": str(r["subject_key"]),
                "confidence": float(r["confidence"]),
                "source_count": int(r["source_count"]),
                "contradictions": int(r["contradiction_count"]),
                "domain_score": float(r["domain_score"]),
                "reasoning_score": float(r["reasoning_score"]),
                "troubleshooting_score": float(r["troubleshooting_score"]),
                "professional_score": round(
                    float(r["domain_score"]) + float(r["reasoning_score"]) + float(r["troubleshooting_score"]),
                    3,
                ),
                "status": str(r["status"]),
                "last_seen": str(r["last_seen"]),
            }
            for r in rows
        ],
    }


def set_fact_status(fact_ids: list[int], status: str) -> dict[str, Any]:
    """Manually set facts to trusted/review for curation workflow."""
    if status not in {"trusted", "review"}:
        return {"success": False, "error": "status must be 'trusted' or 'review'"}
    if not fact_ids:
        return {"success": False, "error": "No fact IDs provided"}

    conn = connect_db()
    init_db(conn)

    updated = 0
    missing: list[int] = []
    for fact_id in fact_ids:
        row = conn.execute("SELECT id FROM facts WHERE id = ?", (int(fact_id),)).fetchone()
        if row is None:
            missing.append(int(fact_id))
            continue
        conn.execute("UPDATE facts SET status = ? WHERE id = ?", (status, int(fact_id)))
        updated += 1

    conn.commit()
    summary = get_curator_status()
    conn.close()
    return {
        "success": True,
        "updated": updated,
        "missing_ids": missing,
        "status_set_to": status,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate Cortex facts")
    parser.add_argument("--run", action="store_true", help="Run curation pipeline")
    parser.add_argument("--status", action="store_true", help="Show curator status")
    parser.add_argument("--limit", type=int, default=0, help="Max files to index in this run")
    parser.add_argument("--force", action="store_true", help="Reindex even unchanged files")
    parser.add_argument("--contains", type=str, default="", help="Only index paths containing this string")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--set-status", choices=["trusted", "review"], help="Set status for selected IDs")
    parser.add_argument("--ids", type=str, default="", help="Comma-separated fact IDs for --set-status")
    parser.add_argument("--list-review", action="store_true", help="List review/trusted facts with filters")
    parser.add_argument("--status-filter", choices=["review", "trusted"], default="review")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-confidence", type=float, default=-1.0)
    parser.add_argument("--min-professional", type=float, default=DEFAULT_MIN_REVIEW_PROFESSIONAL_SCORE)
    args = parser.parse_args()

    if args.set_status:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        result = set_fact_status(ids, args.set_status)
    elif args.list_review:
        result = list_review_facts(
            status=args.status_filter,
            limit=args.limit if args.limit > 0 else 50,
            offset=max(0, args.offset),
            min_confidence=(None if args.min_confidence < 0 else float(args.min_confidence)),
            min_professional_score=(None if args.min_professional < 0 else float(args.min_professional)),
            subject_contains=(args.contains or None),
        )
    elif args.run:
        result = run_curator(
            limit=args.limit if args.limit > 0 else None,
            force=args.force,
            contains=args.contains or None,
        )
    else:
        result = get_curator_status()

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("Cortex Curator")
    print(f"Facts: {result.get('total_facts', 0)} (trusted {result.get('trusted_facts', 0)}, review {result.get('review_facts', 0)})")
    print(f"Contradictions: {result.get('contradiction_pairs', 0)}")
    if args.run:
        print(
            f"Indexed {result.get('indexed_files', 0)} files, "
            f"new facts {result.get('new_facts', 0)}, updated {result.get('updated_facts', 0)}"
        )


if __name__ == "__main__":
    main()
