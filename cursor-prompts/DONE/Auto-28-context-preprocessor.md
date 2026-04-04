# Auto-28: Context Preprocessor — Credit-Saving Middleware for Perplexity Computer

## The Problem

Perplexity Computer charges credits per message, and the cost scales with conversation context length. A 4-hour marathon thread with 100+ messages costs 37,000 credits. The same work split into focused threads would cost ~5,000. Raw terminal output, full log dumps, and unstructured pastes inflate the context window with noise.

## The Vision

A local tool running on Bob (or as a web app on the local network) that acts as a clipboard preprocessor. Matt pastes raw content → tool compresses, formats, and structures it → Matt copies the clean version into Computer. Same information, fraction of the tokens.

Also: a session manager that helps break work into focused threads with pre-built context summaries.

## Context Files to Read First
- CONTEXT.md
- scripts/imessage-server.py (local HTTP server pattern)
- AGENTS.md

## Prompt

Build the context preprocessor and session manager:

### 1. Preprocessor Service (`tools/context_preprocessor/server.py`)

FastAPI web app on port 8850, accessible from any device on the local network:

**Input:** Raw text paste (terminal output, email, log dump, code, anything)
**Output:** Compressed, formatted version optimized for LLM consumption

Processing pipeline:
a) **Strip noise:**
   - Remove ANSI color codes
   - Remove duplicate blank lines (collapse to single)
   - Remove Docker/timestamp prefixes from log lines (keep the message)
   - Remove pip install output, progress bars, download indicators
   - Strip email headers (keep From, To, Subject, Date, body only)
   - Remove base64 blobs, long hashes, JWT tokens (replace with `[REDACTED_TOKEN]`)

b) **Compress:**
   - If input > 100 lines: summarize repeated patterns ("X appeared 47 times" instead of 47 identical lines)
   - Deduplicate identical log entries (show once with count)
   - For JSON: collapse to key structure + first values (not full arrays)
   - For terminal sessions: keep commands and key output, strip prompts and path prefixes

c) **Format for LLM:**
   - Wrap in appropriate markdown code blocks
   - Add a 1-line summary at top: "Terminal output: 47 lines from polymarket-bot container, 3 errors found"
   - Highlight errors/warnings (move them to top)
   - If it's an email: structure as From/To/Subject/Body cleanly

d) **Size indicator:**
   - Show original size vs compressed size
   - Show estimated token count
   - Show estimated credit cost: "This paste would cost ~X credits in a long thread vs ~Y credits in a fresh thread"

### 2. Web UI (`tools/context_preprocessor/static/index.html`)

Simple dark-mode web page:
- Large text area: "Paste anything here"
- "Process" button
- Output area with the cleaned version
- "Copy to Clipboard" button
- Stats bar: "Compressed 247 lines → 23 lines (91% reduction, ~45 tokens saved)"
- Toggle: "Aggressive" vs "Gentle" compression

Accessible at `http://bobs-mac-mini:8850` from any device on the network.

### 3. Session Manager (`tools/context_preprocessor/session_manager.py`)

Helps break work into focused threads:

a) **Context summary generator:**
   - Takes the current CONTEXT.md + recent session history
   - Generates a compressed "session brief" (<500 words) that can be pasted at the start of a new Computer thread
   - Includes: active project status, recent decisions, what was just completed, what's next
   - Output formatted as the `[CONTEXT SUMMARY]` block that Computer understands

b) **Task splitter:**
   - Input: "I need to fix the trading bot, research mounts for Steve, and write cursor prompts"
   - Output: Recommended thread breakdown with pre-written first messages for each:
     ```
     Thread 1: "Fix Polymarket exit bug"
     Context: [compressed summary of bot state]
     First message: "The exit engine on the Polymarket bot is stuck in a loop..."
     
     Thread 2: "Research ceiling mounts for Hisense 100" U8"  
     Context: [compressed summary of Topletz project]
     First message: "I need a ceiling mount for..."
     ```
   - Each thread gets only the context it needs, not everything

c) **Auto-update CONTEXT.md:**
   - After each session, generate an updated CONTEXT.md from what was accomplished
   - Commit and push to repo so the next session starts with fresh context
   - This replaces the manual context summary at the top of threads

### 4. Clipboard Integration (macOS)

For faster workflow without opening the web UI:

```bash
# Pipe clipboard through preprocessor
pbpaste | python3 tools/context_preprocessor/compress.py | pbcopy
```

Create a macOS keyboard shortcut or Alfred/Raycast workflow:
- Cmd+Shift+P → preprocesses clipboard contents in place
- Matt copies terminal output → hits shortcut → pastes clean version into Computer

### 5. Smart Paste Rules (by content type)

| Content Type | Detection | Compression Strategy |
|-------------|-----------|---------------------|
| Docker logs | Timestamp + JSON format | Dedup, keep errors, summarize repeated events |
| Terminal session | `$` or `%` prompts | Keep commands + key output only |
| Email | From/To/Subject headers | Strip threading, keep latest body only |
| JSON API response | `{` or `[` opening | Collapse arrays, show structure + first item |
| Git diff | `diff --git` | Keep changed lines only, strip context |
| Python traceback | `Traceback` | Keep full traceback (important), strip surrounding output |
| Config file | KEY=VALUE or YAML | Keep as-is (already compact) |
| Markdown | `#` headers | Keep as-is (already structured) |
| Code | Detected by extension/syntax | Keep as-is but strip comments if > 200 lines |

### 6. Credit Calculator

Show estimated credit impact:
- "This message in the current thread (~50k context): ~150 credits"
- "This message in a fresh thread (~2k context): ~15 credits"
- "Recommendation: Start a new thread for this task"

Threshold alert: If current thread is estimated at >20,000 credits, suggest starting fresh.

### 7. Docker Service

Add to docker-compose.yml as `context-preprocessor`, port 8850. Lightweight — just FastAPI + static HTML. No external dependencies except Python stdlib + regex.

### 8. Integration with Bob's Brain (API-11)

When the context engine is built, the session manager can pull live context from Bob's Brain instead of relying on CONTEXT.md:
- Current trading status (positions, P/L)
- Active project status (Topletz phase, pending emails)
- System health (which services are running)
- Recent events (last 24h activity)

This makes the auto-generated session brief always current.

Use standard logging.
