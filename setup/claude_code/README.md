# Claude Code Integration — Symphony AI Server

This directory contains everything needed to use **Claude Code** (Anthropic's agentic coding tool) with the Symphony AI Server repository.

---

## What's Here

| File | Purpose |
|---|---|
| `CLAUDE.md` | Auto-loaded project context for every Claude Code session |
| `claude_code_config.json` | Tool configuration and available-tool registry |
| `claude_code_workflows.md` | 7 pre-built workflow templates for common tasks |
| `install_claude_code.sh` | One-command installer for Mac Mini M4 |
| `openclaw_claude_code_tool.json` | OpenClaw MCP tool definition with 3 scope profiles |

---

## Quick Start

### Install Claude Code

```bash
bash setup/claude_code/install_claude_code.sh
```

This installs Claude Code via npm, sets up the OpenClaw tool config, and verifies the installation.

### Start a Session

```bash
cd /path/to/AI-Server
claude
```

Claude will automatically read `CLAUDE.md` and load the project context.

### Use a Workflow

See `claude_code_workflows.md` for 7 ready-to-use workflow templates covering:

- Code review
- Feature development
- Debugging
- Docker deployment
- Client node onboarding
- D-Tools data import
- Knowledge model generation
