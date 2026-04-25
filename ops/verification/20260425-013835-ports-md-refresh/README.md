# PORTS.md Registry Refresh Receipt
**Timestamp:** 2026-04-25T01:38:35Z  
**Operator:** Cline (docs-only, no runtime actions)  
**Host:** Bobs-Mac-mini.local  
**Prompt:** `.cursor/prompts/2026-04-24-cline-ports-md-registry-refresh.md`  
**Runbook:** `ops/runbooks/2026-04-24-ports-md-registry-refresh.md`

---

## What changed

### 1 — Last updated bump
`2026-04-24` → `2026-04-25`

### 2 — Active Services table: Bind column added + 7 new rows

`Container` column renamed `Container/Process`; `Bind` column inserted.
All 14 existing Docker-container rows labelled `loopback`.

New rows added — Bind values from **live `lsof` run at 2026-04-25T01:26Z**,
not from the stale 2026-04-24 audit (which pre-dated the loopback hardening fixes):

| Port | Service | Bind | Source |
|------|---------|------|--------|
| 1234 | BlueBubbles Server | LAN `*` | live lsof: `*:1234` |
| 8088 | Markup Tool | loopback | live lsof: `127.0.0.1:8088` |
| 8103 | File Watcher | loopback | live lsof: `127.0.0.1:8103` |
| 8199 | iMessage Bridge | loopback | live lsof: `127.0.0.1:8199` — **fixed** from LAN `*` |
| 8421 | Trading API | loopback | live lsof: `127.0.0.1:8421` — **fixed** from LAN `*` |
| 8801 | Vault PWA | loopback | live lsof: `127.0.0.1:8801` |
| 11434 | Ollama | loopback | live lsof: `127.0.0.1:11434` — **fixed** from LAN `*` |

Why the stale audit was not used: by the time this prompt executed, 11434/8199/8421
had been rebound to loopback. Using the stale classification would have incorrectly
labelled them as LAN-exposed. The live `lsof` command in the prompt preamble caught
this before apply.

### 3 — "Localhost-Locked AI Server Services" section removed

That section (14 lines) duplicated data now in the main table and used an
inconsistent column schema. Removed to avoid confusion.

### 4 — Notes section rewritten

Old bullet: *"Docker service ports bind to 127.0.0.1 only. Host services
(BlueBubbles :1234, Ollama :11434, iMessage bridge :8199, trading-api :8421)
bind to all interfaces"* — was accurate at audit time but stale after fixes.

New bullets accurately reflect current state:
- Docker containers → loopback
- Host launchd → only BlueBubbles :1234 is LAN `*`; all others loopback
- Pointer to live `lsof` as source of truth

---

## 6 new rows listed with Bind classifications

| Port | Bind | Confirmed by |
|------|------|-------------|
| 1234 | LAN `*` | `lsof`: `BlueBubbl 768 bob TCP *:1234 (LISTEN)` |
| 8088 | loopback | `lsof`: `Python 762 bob TCP 127.0.0.1:8088 (LISTEN)` |
| 8103 | loopback | `lsof`: `Python 749 bob TCP 127.0.0.1:8103 (LISTEN)` |
| 8199 | loopback | `lsof`: `Python 2421 bob TCP 127.0.0.1:8199 (LISTEN)` |
| 8421 | loopback | `lsof`: `Python 22846 bob TCP 127.0.0.1:8421 (LISTEN)` |
| 8801 | loopback | `lsof`: `Python 778 bob TCP 127.0.0.1:8801 (LISTEN)` |
| 11434 | loopback | `lsof`: `ollama 770 bob TCP 127.0.0.1:11434 (LISTEN)` |

---

## Artifacts

| File | Contents |
|---|---|
| `before.md` | PORTS.md before edit (14 active rows, no Bind column, Localhost-Locked section present) |
| `after.md` | PORTS.md after edit (21 active rows, Bind column, Localhost-Locked section removed) |
| `diff.patch` | 78-line unified diff |

Commit hash: see git log for `docs(PORTS): refresh registry against live 2026-04-25 listener state`
