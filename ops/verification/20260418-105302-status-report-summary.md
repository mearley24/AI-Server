# STATUS_REPORT summary

_Generated: 2026-04-18 10:53 MDT · repo commit: `684889efd905` · STATUS_REPORT last touched: 2026-04-18_

This digest is produced by `ops/status_report_summarizer.py` from `STATUS_REPORT.md`. See `ops/AGENT_VERIFICATION_PROTOCOL.md` for the tagging conventions (`[FOLLOWUP]`, `[NEEDS_MATT]`).

## Headline

- **Open items:** 11 across 3 actionable sections
- **Follow-ups:** 9
- **Needs Matt:** 1
- **Completed (in Done section):** 24

## What changed since last summary

_No prior snapshot or no detectable changes._

## Current open items by category

### Now (1)

- 🧑 [NEEDS_MATT] **Fund Polymarket wallet** — deposit $50+ USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. Wallet holds $4.56 USDC.e (as of 2026-04-17); all strategie…

### Next (1)

- **Verify Prompt I runtime** — all code changes for redeem-cleanup are confirmed present; what's unverified is runtime execution. Run `docker compose logs --tail=100 polymarket-bot…

### Later (9)

- 🔁 **client-portal `/health` endpoint** — container reports unhealthy because `client-portal/main.py` has no `GET /health` route. Add one returning `{"status":"ok"}` to fix the compo…
- 🔁 **pull.sh hardening** — current `scripts/pull.sh` is 50 lines (stash + pull + conflict scan). Target ~90 lines: add `py_compile` check per service dir, `--verify` flag for smoke t…
- 🔁 **Dropbox link validator** — lesson #4 (links must use `scl/fi/` not `/preview/`) has no automated validator; still "unknown" from the April 4 audit.
- 🔁 **Sell haircut rounding** — lesson #17 (exit loops from rounding) is unverified in `polymarket-bot`. Check and confirm or fix.
- 🔁 **imessage-server `_re` NameError** — `scripts/imessage-server.py::handle_reset_command` references `_re` which is not defined at module level (only `_idea_re = re` is). Low sever…
- 🔁 **Supabase cleanup (AI-Server)** — env vars `SUPABASE_*` exist in `.env` but zero Docker services use them; `integrations/supabase/` is an empty shell. Safe to remove vars and uni…
- 🔁 **Supabase → Bob migration (symphonysh)** — contact form, appointment booking, confirmation emails, and Matterport upload all depend on Supabase. Not urgent while the free tier co…
- 🔁 **Kalshi live mode** — `KALSHI_DRY_RUN=true` / `KALSHI_ENVIRONMENT=demo`. Set to production once API key is verified. See §Z9.
- 🔁 **Vite/esbuild upgrade (symphonysh)** — `npm audit` reports 2 moderate findings (esbuild ≤0.24.2 via vite ≤6.4.1); dev-server only, not in production build. Requires `vite@8` upgr…

## Follow-ups

- _Later_: **client-portal `/health` endpoint** — container reports unhealthy because `client-portal/main.py` has no `GET /health` route. Add one returning `{"status":"ok"}` to fix the compo…
- _Later_: **pull.sh hardening** — current `scripts/pull.sh` is 50 lines (stash + pull + conflict scan). Target ~90 lines: add `py_compile` check per service dir, `--verify` flag for smoke t…
- _Later_: **Dropbox link validator** — lesson #4 (links must use `scl/fi/` not `/preview/`) has no automated validator; still "unknown" from the April 4 audit.
- _Later_: **Sell haircut rounding** — lesson #17 (exit loops from rounding) is unverified in `polymarket-bot`. Check and confirm or fix.
- _Later_: **imessage-server `_re` NameError** — `scripts/imessage-server.py::handle_reset_command` references `_re` which is not defined at module level (only `_idea_re = re` is). Low sever…
- _Later_: **Supabase cleanup (AI-Server)** — env vars `SUPABASE_*` exist in `.env` but zero Docker services use them; `integrations/supabase/` is an empty shell. Safe to remove vars and uni…
- _Later_: **Supabase → Bob migration (symphonysh)** — contact form, appointment booking, confirmation emails, and Matterport upload all depend on Supabase. Not urgent while the free tier co…
- _Later_: **Kalshi live mode** — `KALSHI_DRY_RUN=true` / `KALSHI_ENVIRONMENT=demo`. Set to production once API key is verified. See §Z9.
- _Later_: **Vite/esbuild upgrade (symphonysh)** — `npm audit` reports 2 moderate findings (esbuild ≤0.24.2 via vite ≤6.4.1); dev-server only, not in production build. Requires `vite@8` upgr…

## Needs Matt

_Items that require Matt's real-world decision or input._

- _Now_: [NEEDS_MATT] **Fund Polymarket wallet** — deposit $50+ USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. Wallet holds $4.56 USDC.e (as of 2026-04-17); all strategies skip with `low_bankroll`. No code chan…

## Top 3 next actions

1. _Now_ (🧑 needs Matt): [NEEDS_MATT] **Fund Polymarket wallet** — deposit $50+ USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. Wallet holds $4.56 USDC.e (as of 2026-04-17); all strategies skip with `low_ban…
2. _Next_: **Verify Prompt I runtime** — all code changes for redeem-cleanup are confirmed present; what's unverified is runtime execution. Run `docker compose logs --tail=100 polymarket-bot 2>&1 | grep redeeme…
3. _Later_ (🔁 follow-up): **client-portal `/health` endpoint** — container reports unhealthy because `client-portal/main.py` has no `GET /health` route. Add one returning `{"status":"ok"}` to fix the compose healthcheck. See…

## Reference sections (historical)

STATUS_REPORT.md contains 19 reference sections (detailed incident reports / historical snapshots). They are not enumerated here; run `grep '^## Reference' STATUS_REPORT.md` to list them.

---

_Produced by `ops/status_report_summarizer.py`. Snapshot written to `data/status_report_summarizer/last_snapshot.json`; next run will diff against it._
