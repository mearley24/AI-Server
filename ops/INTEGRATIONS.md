# External Integrations — AI-Server

Single matrix of every external service this repo talks to in production,
with the auth mechanism, env var(s), code path, and health check if any.
Maintained by hand — update when a new integration lands.

## Matrix

| Service | Used for | Auth | Env vars | Code path | Health |
|---|---|---|---|---|---|
| **OpenAI API** | GPT-4o / Whisper / Realtime (voice) | Bearer | `OPENAI_API_KEY` | voice-receptionist, cortex, x-intake transcript_analyst | — |
| **Ollama (local)** | qwen3:8b local LLM for transcript analysis + autobuilder | none (local) | `OLLAMA_HOST` (optional) | integrations/x_intake/transcript_analyst, cortex_autobuilder | `api/host_modules/ollama_health.py` |
| **Zoho Mail (IMAP + REST)** | Email polling + send | OAuth refresh + IMAP app password | `ZOHO_REFRESH_TOKEN`, `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_EMAIL`, `ZOHO_PASSWORD` | `openclaw/zoho_auth.py`, `email-monitor/monitor.py` | email-monitor `/health` |
| **Zoho Calendar** | Calendar sync + daily briefing | same as mail | same | `calendar-agent/` | calendar-agent `/health` |
| **D-Tools Cloud** | Projects, opportunities, proposals | Basic + `X-API-Key` | `DTOOLS_API_KEY` | `integrations/dtools/dtools_client.py` | dtools-bridge `/health` → `{"dtools":"ready","status":"healthy"}` |
| **D-Tools SI API** | SI (installer) data (catalog etc.) | same as Cloud | same | `integrations/dtools/dtools_client.py` | — |
| **Twilio (Media Streams)** | Voice receptionist | Account SID + Auth Token | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER` | `voice_receptionist/` | voice-receptionist `/health` |
| **Polymarket (CLOB + Gamma)** | Prediction-market trading | Wallet signing | `POLYGON_PRIVATE_KEY`, `POLY_FUNDER_ADDRESS` | `polymarket-bot/src/` | polymarket-bot `/health` via VPN |
| **Kraken (spot)** | MM signals, BTC/ETH quotes | HMAC | `KRAKEN_API_KEY`, `KRAKEN_SECRET` | `polymarket-bot/src/kraken_*` | `/kraken/status` |
| **Kalshi** | Prediction markets (demo) | API key + RSA priv | `KALSHI_API_KEY_ID`, `data/kalshi_private_key.pem` | `polymarket-bot` (Kalshi adapters) | — |
| **Perplexity API** | Research queries | Bearer | `PERPLEXITY_API_KEY` | `tools/perplexity_research.py` | — |
| **Dropbox** | Client file sharing (scl/fi links) | signed-link only (client-side) | — | Paths referenced in proposals + email flows | host-side Dropbox sync |
| **Cloudflare** | DNS + Pages (symphonysh website) | API token | `CLOUDFLARE_API_TOKEN` | `scripts/` (ad-hoc) | — |
| **RSSHub** | X account RSS proxy | internal only | — | `docker-compose.yml` | rsshub (internal) |
| **BuildingConnected (email)** | Bid invitations | IMAP parsing | (uses Zoho inbound) | `email-monitor/bid_triage.py` | email-monitor `/health` |
| **Twitter/X (via RSSHub)** | Account monitoring | none (scrape via RSSHub) | — | `x-alpha-collector`, `x-intake` | — |
| **Tailscale** | Inter-host VPN (Bob ↔ Bert) | machine keys | system-level | `ops/task_runner/remote_scripts/bert-hostkey-pin.sh` | `tailscale status` |
| **Telegram** | Bot interactions (research, queue, daily digest) | Bot tokens | `TELEGRAM_BOT_TOKEN` (+ per-employee) | `telegram-*`, `notification-hub/` | — |
| **BlueBubbles** | iMessage bridge over Tailscale | credentials file | `BLUEBUBBLES_URL`, `BLUEBUBBLES_PASSWORD` | `scripts/imessage-server.py`, Symphony Ops dashboard tile | `api/symphony/bluebubbles/health` |
| **GitHub (origin)** | Git remote | SSH (default) / HTTPS token | — | `scripts/pull.sh`, task-runner | — |
| **Snap One portal** | Product docs / CSV catalog | none (public docs) | — | `tools/snapav_scraper.py` | — |
| **WireGuard (VPN container)** | Fronts polymarket-bot | WG config | mounted via compose | `vpn/` service | compose-level only |

## Rules

1. **All secrets go in `.env`** — never hardcoded. Use `scripts/set-env.sh
   KEY value` to set/update (the `echo >>` pattern ignores duplicates).
2. **.env is in `.gitignore`** — verify before commits.
3. **Per-employee secrets** live in `/Volumes/HomebaseConfig/<employee>.env`
   (AGENTS.md rule, not in this repo).
4. **Dropbox links:** use `scl/fi/...` share links, NEVER `/preview/` (Lesson #4).
5. **Health endpoints:** every containerized service has `GET /health`.
   External services that expose health checks are reached via their
   respective client code.
6. **Rotation:** no automated rotation exists today. High-risk keys
   (KRAKEN_SECRET, POLYGON_PRIVATE_KEY) are rotated manually after any
   suspected exposure.

## Seeing what's really there

- `cat .env | grep -E '^[A-Z]'` (on Bob only) — lists all env keys.
- `grep -rl "os.environ\\[\\|os.getenv" --include='*.py'` — finds env
  consumers.
- `docker compose config` — prints resolved compose config with env
  substitution.
