# Perplexity Computer — Mission Control & AI-Server handoff prompt

**Copy everything below the line into Perplexity Computer** (adjust repo path if needed).

---

## Role

You are helping finish and verify **Symphony Mission Control** and related **AI-Server** Docker services on a Mac Mini. Repo: **`AI-Server`** at the project root. Mission Control is a **single-file** vanilla dashboard: `mission_control/static/index.html`, API in `mission_control/main.py` + `mission_control/event_server.py`, default port **8098**.

## Original spec (source of truth)

`.cursor/prompts/mission-control-final.md` lists the full polish checklist (§1–§10). Use it to see intended UX.

---

## Done in-repo (recent work — verify nothing regressed)

These are **implemented in code**; they may still need **visual QA** after `docker compose build mission-control && docker compose up -d mission-control`:

| Area | Status |
|------|--------|
| §1 Invalid Date | **`parseDate()`**, **`formatEventWhen()`** for event lists; guards for odd date strings |
| §2 Font sizing | CSS variables (`--fs-label`, `--fs-body`, `--fs-secondary`, `--fs-hero`, `--fs-badge`, `--fs-sys`, `--fs-strip`) with `clamp()` in `:root` |
| §3 Row padding | Email/calendar/follow-up rows **8px / 40px min-height**, service pills **8px 10px** |
| §4 Sidebar | Collapsible nav, hamburger, `localStorage` for collapsed state, views: Dashboard / Trading / Events / Digest / Settings |
| §5 Quick actions | Refresh All, Bot Status (**toast** + summary, not `alert`), View Logs (slide panel), Daily Digest (modal) |
| §6 Tile expand | Single expanded tile; expanded tables for services/trading/email/calendar/followups/system |
| §7 Toasts | WS-driven toasts, stack max 3, dismiss on click |
| §8 Topbar | **Last refresh** label, **WS dot pulse** on events, **portfolio line** (` · +$net · Open $…` when trading loads) |
| §9 Service sparklines | Last **10** health checks per service, dot row |
| §10 Trading position tag | **`#trading-positions`** next to hero; bot `/status` preferred for open count |

**Polymarket bot:** A root-level **`polymarket-bot/structlog.py` was deleted** — it shadowed the real `structlog` package and crashed the bot (`AttributeError: structlog.configure`). Bot must use **`structlog` from `requirements.txt` only**. Do not reintroduce a file named `structlog.py` in `polymarket-bot/`.

**OpenClaw orchestrator:** HTTP client uses **`trust_env=False`** so host `HTTP_PROXY` does not break internal `http://vpn:8430` calls. Trading URL tries **`vpn:8430`** then **`host.docker.internal:8430`**.

---

## Still thin / not finished (priority for you)

1. **Settings view (`#view-settings`)**  
   Still mostly **placeholder** (timezone note, compose rebuild hint, `/ws`). No real settings editing, env editor, or links to docs.

2. **Daily Digest presentation**  
   **§5** asked for **“formatted markdown”** in the modal. Current behavior is largely **plain `textContent`** (`loadDigestFullPanel`, digest modal). **No client-side markdown renderer** is wired unless added (would need a small sanitizer + library or server-rendered HTML).

3. **Trading nav view**  
   `loadTradingView()` is **more than a JSON dump** now (positions table, category P&amp;L, bot JSON block), but it can still be **polished**: better hierarchy, mobile tables, error states when `vpn:8430` is down.

4. **Expanded tile details vs spec**  
   Cross-check **§6** bullets (e.g. **checked_at** on services if API returns it, **container uptime** in system expanded, **full email subjects** when expanded). Some columns may be **partial** depending on API payloads.

5. **`cursor-prompts/VERIFICATION_REPORT.md`**  
   Mentions removed **`structlog.py`** shim — keep verification docs aligned with reality if you edit reports.

---

## Known failure modes (still possible in production)

| Symptom | Likely cause |
|--------|----------------|
| **OpenClaw:** “Trading bot unreachable” | **`polymarket-bot` not running**, stuck in restart, or not listening on **8430** in **`vpn`** network namespace. Fix bot first; then verify `docker exec openclaw curl -sS http://vpn:8430/health`. |
| **Host:** `curl 127.0.0.1:8430` → empty reply / refused | Bot down or port not bound; **`127.0.0.1:8430:8430`** maps to **`vpn`** container shared with bot. |
| **Mission Control:** `/api/events-log` → `unavailable` or empty | **OpenClaw** not up, or **Redis** not reachable from OpenClaw; orchestrator must publish to **`events:log`**. |
| **Proxy env vars** | Rare: if something sets **`trust_env=True`** again for internal clients, proxies can break Docker DNS URLs. |

---

## What to do next (suggested order)

1. Re-read **`mission-control-final.md`** and diff against **`mission_control/static/index.html`** for any **§4–§10** gap (especially **digest markdown** and **settings**).  
2. Run Mission Control locally or in Docker and **click every nav item, quick action, tile expand, and WS path**.  
3. Optionally add **safe markdown** for digest (or server-side HTML from `GET /digest`).  
4. Flesh out **Settings** with non-secret references (service ports, compose service names, links to runbooks in repo).

---

## Constraints

- **No TypeScript / no React** for this dashboard — vanilla JS only per project rules.  
- **Timezone:** **America/Denver** for display.  
- **Security:** do not embed secrets in the dashboard; settings remain env/Docker.

---

**End of handoff — use the sections above to plan, test, and implement what’s left.**
