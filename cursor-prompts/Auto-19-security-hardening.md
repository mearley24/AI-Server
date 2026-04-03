# Auto-19: Security Hardening — Secrets, Auth, Audit

## Context Files to Read First
- polymarket-bot/src/security/vault.py
- polymarket-bot/src/security/audit.py
- polymarket-bot/src/security/sandbox.py
- .env (current secrets storage)
- docker-compose.yml

## Prompt

Bob handles real money (Polymarket), client data (proposals, agreements), and business communications. Harden the security:

1. **Secrets management**:
   - Move all secrets from `.env` to Docker secrets or a local vault
   - `polymarket-bot/src/security/vault.py` exists — wire it up as the single source for all secrets
   - Private keys (Polymarket wallet) should NEVER be in `.env` — use encrypted file with passphrase
   - Rotate Zoho OAuth tokens automatically before expiry
   - API keys should be loaded from vault at runtime, not baked into Docker images

2. **API authentication**:
   - All internal APIs (trading API, mobile API, mission control, voice webhook) need auth
   - Simple approach: shared API key per service, stored in vault
   - External-facing endpoints (Twilio webhooks): verify Twilio signature
   - Mission Control: basic auth (username/password) since it's a web UI
   - Rate limiting: 100 req/min per IP on all API endpoints

3. **Audit logging** (`polymarket-bot/src/security/audit.py` — expand):
   - Log every: trade execution, email sent, iMessage sent, proposal generated, Docker command
   - Include: timestamp, action, actor (which service), target, result
   - Store in append-only SQLite database `security/audit.db`
   - Rotate monthly, compress old months
   - CLI: `python3 audit.py --last 24h` to review recent actions

4. **Network security**:
   - Docker services should NOT expose ports to 0.0.0.0 — bind to localhost or Tailscale IP only
   - Review docker-compose.yml: change all `ports: "8XXX:8XXX"` to `ports: "127.0.0.1:8XXX:8XXX"`
   - Exception: services that need Tailscale access (voice webhook, mission control) bind to Tailscale IP
   - VPN container: verify kill switch (if WireGuard goes down, all traffic stops, no IP leak)

5. **Wallet security**:
   - Polymarket wallet private key: encrypt at rest, decrypt only in memory when signing
   - Max single trade size: $25 (hard limit in code, not just config)
   - Daily loss limit: $50 (if daily P/L hits -$50, pause all strategies and alert Matt)
   - Weekly loss limit: $150

6. **Backup**: daily encrypted backup of all SQLite databases + Redis dump to a local encrypted volume.

Use standard logging.
