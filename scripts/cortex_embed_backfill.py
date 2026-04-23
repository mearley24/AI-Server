#!/usr/bin/env python3
"""One-shot backfill: compute embeddings for memories that lack them.

Usage:
    python3 scripts/cortex_embed_backfill.py [--db PATH] [--model MODEL]
        [--provider ollama|openai|null] [--dry-run] [--apply]
        [--batch 100]

Defaults to --dry-run. Pass --apply to write.

Exit codes:
    0   success
    1   argument / config error
    3   unexpected error
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.embeddings import NullProvider, OllamaProvider, OpenAIProvider, pack_vector


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _resolve_db(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg)
    try:
        from cortex.config import DB_PATH
        return DB_PATH
    except Exception:
        return REPO_ROOT / "data" / "cortex" / "brain.db"


def _build_provider(name: str, model: str):
    if name == "null":
        return NullProvider()
    if name == "openai":
        ok = __import__("os").environ.get("CORTEX_EMBED_OPENAI_OK", "0") == "1"
        if not ok:
            print("ERROR: CORTEX_EMBED_OPENAI_OK not set to 1", file=sys.stderr)
            sys.exit(1)
        return OpenAIProvider()
    # default: ollama
    try:
        from cortex.config import CORTEX_EMBED_OLLAMA_HOST
        host = CORTEX_EMBED_OLLAMA_HOST
    except Exception:
        host = __import__("os").environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    return OllamaProvider(host=host, model=model)


async def _run(db_path: Path, dry_run: bool, provider, batch_size: int) -> dict:
    stamp = _now_stamp()
    backup_cmd = f"cp {db_path} {db_path}.bak.{stamp}"
    print(f"Backup command (run manually before --apply):\n  {backup_cmd}\n")

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")

    # Find memories without embeddings for this model
    existing = {
        row[0] for row in conn.execute(
            "SELECT memory_id FROM memory_embeddings WHERE model=?",
            (provider.model_name,),
        ).fetchall()
    }

    rows = conn.execute(
        "SELECT id, content FROM memories WHERE importance > 0 ORDER BY created_at"
    ).fetchall()
    missing = [(r[0], r[1]) for r in rows if r[0] not in existing]

    print(f"Memories total: {len(rows)}")
    print(f"Already embedded ({provider.model_name}): {len(existing)}")
    print(f"Missing: {len(missing)}")

    if not missing:
        print("Nothing to embed.")
        conn.close()
        return {"total": len(rows), "already_done": len(existing), "missing": 0,
                "written": 0, "failed": 0, "dry_run": dry_run}

    if dry_run:
        print(f"\nDRY RUN — would embed {len(missing)} row(s). Pass --apply to write.")
        conn.close()
        return {"total": len(rows), "already_done": len(existing), "missing": len(missing),
                "written": 0, "failed": 0, "dry_run": True}

    written = 0
    failed = 0
    now = datetime.now(timezone.utc).isoformat()

    for i in range(0, len(missing), batch_size):
        batch = missing[i: i + batch_size]
        print(f"  Batch {i // batch_size + 1}: {len(batch)} rows …", end=" ", flush=True)
        for memory_id, content in batch:
            try:
                vec = await asyncio.wait_for(provider.embed(content[:4096]), timeout=10.0)
                blob = pack_vector(vec)
                digest = hashlib.sha256(content[:4096].encode()).hexdigest()
                conn.execute(
                    """INSERT OR REPLACE INTO memory_embeddings
                       (memory_id, embedding, dim, model, content_digest, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (memory_id, blob, len(vec), provider.model_name, digest, now, now),
                )
                written += 1
            except Exception as exc:
                print(f"\n    WARN {memory_id}: {exc!s:.80}")
                failed += 1
        conn.commit()
        print(f"done (+{len(batch) - failed})")

    conn.close()

    summary = {
        "timestamp": now, "db": str(db_path), "model": provider.model_name,
        "total": len(rows), "already_done": len(existing), "missing": len(missing),
        "written": written, "failed": failed, "dry_run": False,
    }
    verif_dir = REPO_ROOT / "ops" / "verification"
    verif_dir.mkdir(parents=True, exist_ok=True)
    verif_path = verif_dir / f"{stamp}-cortex-embed-backfill.json"
    verif_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {written} embeddings. Summary: {verif_path}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Cortex embedding backfill")
    parser.add_argument("--db", default=None)
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--provider", choices=["ollama", "openai", "null"], default="ollama")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()

    dry_run = not args.apply
    db_path = _resolve_db(args.db)

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    provider = _build_provider(args.provider, args.model)

    try:
        asyncio.run(_run(db_path, dry_run=dry_run, provider=provider, batch_size=args.batch))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
