# CLAUDE.md — Symphony AI Server

This file is automatically read by Claude Code at the start of every session.
It gives Claude context about this repository and defines the working rules.

---

## Project Overview

This is the **Symphony AI Server** — the AI infrastructure for Symphony Smart Homes, a Denver-based residential AV and smart-home integration company.

### What's In This Repo

| Folder | Description |
|---|---|
| `voice_receptionist/` | Bob the Conductor — AI voice receptionist (Twilio + OpenAI Realtime API) |
| `client_ai/` | Symphony Concierge — local LLM appliance for client homes (Ollama) |
| `setup/claude_code/` | Claude Code tooling and workflow templates |
| `.cursor/rules/` | Cursor IDE rule files (`.mdc`) |
| `dashboard/` | Mission Control deployment UI |

---

## Working Rules for Claude

### Coding Standards

- **JavaScript**: `'use strict'`, CommonJS, 2-space indent, single quotes.
- **Python**: PEP 8, type hints on public functions, docstrings.
- **Shell**: `#!/usr/bin/env bash`, `set -euo pipefail`, comment every step.
- No TypeScript. No frontend frameworks (React, Vue, etc.).

### File Conventions

- Never modify `.env` files — read them, suggest changes, but do not write.
- Never commit secrets or API keys.
- When adding a new file, update the README for that folder.

### Git Workflow

- Commit messages: imperative mood, ≤72 chars subject.
- Feature branches: `feature/<short-name>`
- Always `git fetch && git status` before pushing.

### Tool Usage (OpenClaw)

- Default to `read_only` profile unless changes are needed.
- Use `dev` profile for code changes.
- Use `admin` profile only for Docker/deployment operations — always confirm.

---

## Key Files

| File | Purpose |
|---|---|
| `voice_receptionist/server.js` | Bob's main server — Twilio ↔ OpenAI bridge |
| `voice_receptionist/system_prompt.md` | Bob's AI persona and instructions |
| `client_ai/client_knowledge_builder.py` | Builds custom Ollama models from D-Tools data |
| `client_ai/client_registry.json` | Registry of all deployed Concierge nodes |
| `dashboard/index.html` | Mission Control deployment dashboard |

---

## Running the Project

```bash
# Bob the Conductor
cd voice_receptionist && npm install && node server.js

# Symphony Concierge (Docker)
cd client_ai && docker compose up -d

# Build client knowledge model
python3 client_ai/client_knowledge_builder.py --client "The Andersons" --dtools-csv /path/to/data.csv
```
