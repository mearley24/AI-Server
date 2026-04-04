# Ultra Runbook — Session Protocol

## Session Start
1. Read `AGENTS.md` for persistent context
2. Read `orchestrator/WORK_IN_PROGRESS.md` for current state
3. Check `openclaw/task_board.py list` for queued work
4. Run `./scripts/smoke-test.sh` to verify system health

## Model Selection
- **Opus 4.6**: multi-file wiring, orchestrator changes, complex debugging
- **GPT-5.4 High**: greenfield feature code, new modules
- **Composer 2 Fast**: quick fixes, small edits, file creation
- **Sonnet 4.6**: general coding, React components

## Handoff
Before ending a session:
1. Update `orchestrator/WORK_IN_PROGRESS.md` with current state
2. Commit all changes
3. Run `./scripts/smoke-test.sh`
4. Note any unfinished items via `python3 openclaw/task_board.py add "..." --priority high`

## Key Commands
```bash
./scripts/symphony-ship.sh          # Build + deploy
./scripts/symphony-ship.sh verify   # Health check only
./scripts/smoke-test.sh             # Full smoke test
python3 openclaw/task_board.py list  # Pending tasks
python3 tools/bob_maintenance.py --dry  # Maintenance preview
```
