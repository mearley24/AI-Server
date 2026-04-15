"""
X-Intake Lab — Experimental transcript analysis and bookmark organization.

Runs alongside x-intake without interfering with the main pipeline.
Controlled by LAB_MODE=true env var.

Port: 8101 (internal), mapped to 8103 on host.
Redis channel: x-intake-lab
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [x-intake-lab] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')
CORTEX_URL = os.environ.get('CORTEX_URL', 'http://cortex:8102')
TRANSCRIPT_DIR = Path(os.environ.get('TRANSCRIPT_DIR', '/data/transcripts'))
BOOKMARK_DIR = Path('/data/bookmarks')
LAB_DATA_DIR = Path('/data/lab')
PORT = int(os.environ.get('PORT', '8101'))

# ── State ──────────────────────────────────────────────────────────────────
_start_time = time.time()
_processed_transcripts = 0
_processed_bookmarks = 0
_last_transcript_scan: str | None = None
_last_bookmark_scan: str | None = None

app = FastAPI(title='X-Intake Lab', version='1.0.0')


# ── Cortex logging ─────────────────────────────────────────────────────────
async def log_to_cortex(content: str, tags: list | None = None) -> None:
    """Post a memory entry to Cortex."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f'{CORTEX_URL}/remember',
                json={
                    'content': content,
                    'tags': tags or ['x-intake-lab'],
                    'source': 'x-intake-lab',
                },
            )
    except Exception as exc:
        log.warning('Cortex log failed: %s', exc)


# ── Transcript analysis ────────────────────────────────────────────────────
async def analyze_transcript(path: str) -> dict:
    """Analyze a single transcript file and log to Cortex."""
    p = Path(path)
    if not p.exists():
        log.warning('Transcript not found: %s', path)
        return {'error': f'File not found: {path}'}
    content = p.read_text(encoding='utf-8', errors='replace')
    preview = content[:500].replace('\n', ' ')
    log.info('Analyzing transcript: %s (%d chars)', p.name, len(content))
    await log_to_cortex(
        f'X-Intake Lab analyzed transcript: {p.name} — {preview}',
        tags=['transcript', 'x-intake-lab'],
    )
    global _processed_transcripts
    _processed_transcripts += 1
    return {'status': 'analyzed', 'file': p.name, 'chars': len(content)}


async def scan_transcripts() -> None:
    """Find and analyze unprocessed transcript files (*.md) every 5 min."""
    global _last_transcript_scan
    _last_transcript_scan = datetime.now().isoformat()
    if not TRANSCRIPT_DIR.exists():
        return
    LAB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    processed_log = LAB_DATA_DIR / 'processed_transcripts.json'
    processed: set[str] = set()
    if processed_log.exists():
        try:
            processed = set(json.loads(processed_log.read_text()))
        except Exception:
            processed = set()

    new_files = [f for f in TRANSCRIPT_DIR.rglob('*.md') if f.name not in processed]
    if not new_files:
        log.debug('No new transcripts to analyze')
        return

    log.info('Found %d unanalyzed transcript(s)', len(new_files))
    for f in new_files[:10]:  # max 10 per scan cycle
        await analyze_transcript(str(f))
        processed.add(f.name)
    processed_log.write_text(json.dumps(sorted(processed)))


# ── Bookmark organization ──────────────────────────────────────────────────
async def organize_bookmarks(path: str | None = None) -> dict:
    """Parse and log bookmark export files (.json)."""
    global _last_bookmark_scan, _processed_bookmarks
    _last_bookmark_scan = datetime.now().isoformat()
    target = Path(path) if path else BOOKMARK_DIR
    if not target.exists():
        return {'status': 'no bookmarks dir'}
    files = list(target.glob('*.json')) if target.is_dir() else [target]
    if not files:
        return {'status': 'no bookmark files'}

    log.info('Processing %d bookmark file(s)', len(files))
    results = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            count = len(data) if isinstance(data, list) else 1
            await log_to_cortex(
                f'X-Intake Lab organized bookmarks from {f.name} ({count} items)',
                tags=['bookmarks', 'x-intake-lab'],
            )
            _processed_bookmarks += count
            results.append({'file': f.name, 'items': count})
        except Exception as exc:
            log.warning('Bookmark parse error %s: %s', f.name, exc)
            results.append({'file': f.name, 'error': str(exc)})
    return {'status': 'organized', 'files': results}


# ── Background loops ───────────────────────────────────────────────────────
async def transcript_loop() -> None:
    """Check for new transcripts every 5 minutes."""
    while True:
        try:
            await scan_transcripts()
        except Exception as exc:
            log.error('Transcript scan error: %s', exc)
        await asyncio.sleep(300)


async def bookmark_loop() -> None:
    """Check for new bookmark exports every 30 minutes (staggered 60s at start)."""
    await asyncio.sleep(60)
    while True:
        try:
            await organize_bookmarks()
        except Exception as exc:
            log.error('Bookmark scan error: %s', exc)
        await asyncio.sleep(1800)


async def redis_command_loop() -> None:
    """Subscribe to Redis channel 'x-intake-lab' for ad-hoc commands."""
    redis_url = (
        f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}'
        if REDIS_PASSWORD
        else f'redis://{REDIS_HOST}:{REDIS_PORT}'
    )
    while True:
        try:
            import redis.asyncio as aioredis  # noqa: PLC0415

            r = aioredis.from_url(redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe('x-intake-lab')
            log.info('Subscribed to Redis channel: x-intake-lab')
            async for message in pubsub.listen():
                if message['type'] != 'message':
                    continue
                try:
                    cmd = json.loads(message['data'])
                    action = cmd.get('action')
                    if action == 'analyze_transcript':
                        result = await analyze_transcript(cmd.get('path', ''))
                        log.info('analyze_transcript: %s', result)
                    elif action == 'organize_bookmarks':
                        result = await organize_bookmarks(cmd.get('path'))
                        log.info('organize_bookmarks: %s', result)
                    elif action == 'scrape_bookmarks':
                        result = await organize_bookmarks()
                        log.info('scrape_bookmarks: %s', result)
                    else:
                        log.warning('Unknown action: %s', action)
                except Exception as exc:
                    log.error('Command handler error: %s', exc)
        except Exception as exc:
            log.error('Redis connection error: %s — retrying in 10s', exc)
            await asyncio.sleep(10)


# ── FastAPI endpoints ──────────────────────────────────────────────────────
@app.get('/health')
async def health() -> dict:
    return {
        'status': 'ok',
        'service': 'x-intake-lab',
        'uptime_seconds': int(time.time() - _start_time),
        'processed_transcripts': _processed_transcripts,
        'processed_bookmarks': _processed_bookmarks,
        'last_transcript_scan': _last_transcript_scan,
        'last_bookmark_scan': _last_bookmark_scan,
    }


@app.get('/stats')
async def stats() -> dict:
    return await health()


# ── Startup ────────────────────────────────────────────────────────────────
@app.on_event('startup')
async def startup() -> None:
    LAB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(transcript_loop())
    asyncio.create_task(bookmark_loop())
    asyncio.create_task(redis_command_loop())
    log.info(
        'X-Intake Lab started — transcript loop: 5min, bookmark loop: 30min, '
        'Redis channel: x-intake-lab'
    )


if __name__ == '__main__':
    uvicorn.run('lab_main:app', host='0.0.0.0', port=PORT, log_level='info')
