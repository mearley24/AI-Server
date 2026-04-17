# symphony/browser/

Intended as the home of `autonomous.py`, a Playwright/browser-use wrapper
referenced in `AGENTS.md` under "Browser Automation — Full Autonomous
Control" (the D-Tools preset + generic browser tasks).

**Current state (2026-04-17): the source file is missing from the repo.**
Only a compiled `__pycache__/autonomous.cpython-314.pyc` remains, which
means Python can still `import symphony.browser.autonomous` on machines
where the pyc was produced, but any fresh checkout will fail to import.

## Likely scenarios

- The source file was previously tracked, then removed without a
  `__pycache__` sweep.
- Or, the source lives on a specific machine (Bob) and was never
  committed.

## What you should do

- If you are wiring a new browser automation task, prefer:
  - `agents/dtools_browser_agent.py` for D-Tools automation, or
  - `tools/snapav_scraper.py` for Snap One product scraping.
- If `symphony.browser.autonomous` is the right entry point, restore
  a source file and commit it here. The expected shape is a small
  wrapper exposing:
  - `autonomous_task(task_prompt: str) -> dict`
  - `dtools_project(name: str, client: str, address: str) -> dict`

## References

- `AGENTS.md` → "Browser Automation — Full Autonomous Control"
- `ops/INTEGRATIONS.md` → matrix of external services in use
- `.cursor/mcp.json` → Playwright MCP server config (if present)
