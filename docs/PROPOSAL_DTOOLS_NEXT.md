# D-Tools Cloud proposal loop — next engineering steps

High-level checklist aligned with `AGENTS.md` (D-Tools Cloud proposal) and `.cursor/rules/dtools.mdc`.

1. **Search before create** — Call `get_projects()`, `get_opportunities()`, `get_clients()` from `integrations/dtools/dtools_client.py` to avoid duplicate opps/projects.
2. **Pipeline alignment** — Use `get_active_pipeline()` / status filters so proposals match active installs (OpenClaw `dtools_sync` already drives jobs; extend UI or Bob commands as needed).
3. **Secrets** — `DTOOLS_API_KEY` in root `.env`; Basic Auth is fixed per API docs.
4. **Fallback** — When equipment is ambiguous, default categories toward **Control4** (export patterns in `tools/bob_export_dtools.py`).

For day-to-day API behavior, prefer the live client and HARPA command JSON under `setup/harpa/` over duplicating business rules in new modules.
