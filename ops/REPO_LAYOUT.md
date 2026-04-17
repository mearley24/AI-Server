# Repo Layout — AI-Server

Single source of truth for what each top-level directory is, whether it is
in `docker-compose.yml`, and what agents should assume.

Last reconciled: 2026-04-17 (Category 3 audit). Regenerate by running
`bash scripts/compose-drift-check.sh` — any drift produces a report.

## Legend

| Tag | Meaning |
|---|---|
| `service` | Live service; present in `docker-compose.yml`; health probed. |
| `tooling` | Source-only; no container. Imported by scripts/ or launchd. |
| `content` | Markdown / JSON knowledge base; no code executed on Bob. |
| `external` | Tracked in this repo but built/deployed elsewhere (e.g., iOS, symphonysh web). |
| `runtime` | Data, logs, caches — typically gitignored. |
| `stale` | No compose entry; preserved on disk with a DECOMMISSIONED.md marker. |
| `ignored` | In `.gitignore`; may exist locally, not in repo. |

## Services (docker-compose.yml — 19 entries)

| Dir / name | Tag | Notes |
|---|---|---|
| `openclaw/` | service | Orchestrator, bind-mounted (`./openclaw:/app`). Port 8099. |
| `cortex/` | service | Brain + dashboard; bind-mounted. Port 8102. |
| `email-monitor/` | service | Zoho IMAP. Port 8092. |
| `notification-hub/` | service | iMessage / Telegram / email dispatch. Port 8095. |
| `proposals/` | service | Proposal PDF + approval flow. Port 8091. |
| `client-portal/` | service | E-sign, per-client pages. Internal port 8096. |
| `integrations/dtools/` (dtools-bridge) | service | D-Tools Cloud API bridge. 5050 internal / 8096 host. |
| `calendar-agent/` | service | Zoho calendar. Port 8094. |
| `voice_receptionist/` (voice-receptionist) | service | Twilio voice. 3000 internal / 8093 host. |
| `clawwork/` | service | Background workflow runner. Port 8097. |
| `integrations/x_intake/` (x-intake) | service | X/Twitter link analysis. Port 8101. |
| `integrations/x_intake/` (x-intake-lab) | service | Lab/sandbox of x-intake — separate container. |
| `integrations/cortex_autobuilder/` | service | Bob/Betty research loop. Port 8115. |
| `polymarket-bot/` | service | Trading. 8430 via VPN. |
| `intel-feeds/` (image) | service | Intel RSS aggregator. Port 8765. |
| `rsshub/` (image) | service | RSS feed proxy. Internal 1200. |
| `x-alpha-collector/` (image) | service | Watches 40+ X accounts. No HTTP surface. |
| `redis/` (image) | service | Auth required, static IP 172.18.0.100. |
| `vpn/` (image) | service | WireGuard fronting polymarket-bot. |

## Tooling (no compose entry; drives host-side automation)

| Dir | Role |
|---|---|
| `scripts/` | Bash + Python helpers (pull.sh, ship.sh, verify-*.sh, task-*). |
| `ops/` | Agent verification protocol, task runner, preflight, audit, launchd plists, work_queue. |
| `tools/` | Host utilities (photo harvest, notes sync, knowledge bridge, etc.). |
| `symphony/` | Browser + email helpers used by tooling; not a container. |
| `agents/` | YAML persona + routing definitions for internal agent roles. |
| `setup/` | Install / bootstrap scripts (nodes, launchd, ollama). |
| `data/` | Runtime DBs, logs, caches. Mostly gitignored. |
| `knowledge/` | Content + scripts (NOT a pip package). Heavily gitignored inside. |
| `api/` | host-side Flask/FastAPI endpoints (voice-webhook, trading-api, gateway). |
| `dashboard/` | Vanilla JS/HTML dashboard assets. |
| `docs/` | Operator-facing documentation. |
| `operations/` | Ops runbooks (separate from `ops/`). |
| `orchestrator/` | Legacy scheduler + task-board bits; used by some tools. |
| `core/` | Small shared helpers (LOW usage; seed-state only). |
| `services/` | Small shared service helpers (LOW usage; unclear purpose — flagged). |
| `templates/` | HTML / email templates. |

## External (built/deployed outside AI-Server)

| Dir | Role |
|---|---|
| `ios-app/` | iOS client source. No compose. |
| `apps/vault-pwa/` | PWA companion app. No compose. |
| `client_ai/` | Symphony Concierge appliance (client-side Mac Minis). |
| `telegram-bob-remote/` | Separate compose; telegram-only profile. |
| `telegram-interface/` | Telegram bridge ancillary. |
| `portfolio-site/` | Staged for future website project. |

## Stale (preserved on disk, DECOMMISSIONED.md marker)

| Dir | Replaced by |
|---|---|
| `mission_control/` | `cortex/` (Prompt S — 2026-04-12). |
| `context-preprocessor/` | Cortex memory + x-intake pipeline. |
| `knowledge-scanner/` | cortex-autobuilder + transcript_analyst. |
| `remediator/` | `scripts/bob-watchdog.sh` + per-service watchdogs. |

## Ignored (gitignore)

| Dir | Why |
|---|---|
| `backups/` | Local-only. |
| `logs/` | Local-only. |
| `scratch/` | Drafts; not shared. |
| `symphonysh-web/` | Sibling repo checked in here for convenience. |
| `redis/` | Redis dump files. |
| `models/` | Large binary models. |
| `cursor-prompts/` | IDE workspace artifacts. |
| `.cursor/local/` | IDE local scratch. |
| `.backups/` | Rotation artifacts. |

## How to keep this file honest

```bash
bash scripts/compose-drift-check.sh
```

The check lists any top-level directory with a Dockerfile that is not in
compose, any service-shaped directory without a DECOMMISSIONED.md marker,
and any drift between CLAUDE.md's claimed count and the compose reality.
