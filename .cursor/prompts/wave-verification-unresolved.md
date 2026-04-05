# Verification Pass + Unresolved Items

**Priority:** Run this AFTER all wave prompts are complete. This is the cleanup sweep.
**Purpose:** Verify everything that was built actually works, and resolve the open items from the April 5 marathon session.

---

## Context Files to Read First

- `cursor-prompts/VERIFICATION_REPORT.md` — existing verification status
- `CONTEXT.md` — current system state
- `AGENTS.md` — architecture overview
- `.cursor/prompts/DONE/` — all three completed prompts from today
- `polymarket-bot/strategies/` — all strategy files
- `openclaw/` — all business automation files
- `email-monitor/` — email processing
- `integrations/x_intake/` — X pipeline

---

## Part 1: Verify Tonight's Three Fixes

These were applied earlier today. Confirm they're solid:

### Fix 1: X Intake Pipeline (Redis Bridge)

- **What was fixed**: `integrations/x_intake/bridge.py` was not publishing to Redis
- **Verify**: Check that `bridge.py` calls `redis.publish()` on the correct channel after processing each X post
- **Test**: Run `python -c "from integrations.x_intake.bridge import XIntakeBridge; print('OK')"`
- **Confirm**: Redis channel name matches what downstream consumers subscribe to

### Fix 2: Kraken Avellaneda Market Maker

- **What was fixed**: `dry_run=True` was hardcoded, `connect()` was never called
- **Verify**: Check that `dry_run` reads from env/config (not hardcoded True)
- **Verify**: Check that `connect()` is called during initialization
- **Test**: `python -c "from strategies.kraken_mm import AvellanedaMarketMaker; print('OK')"`

### Fix 3: Email Monitor Duplicates

- **What was fixed**: `BODY.PEEK` instead of `BODY[]` (was marking emails as read), unstable message_id generation
- **Verify**: Check `email-monitor/main.py` uses `BODY.PEEK[]` for fetching
- **Verify**: Check message_id is generated from stable fields (Message-ID header, not UID)
- **Test**: `python -c "from email_monitor.main import EmailMonitor; print('OK')"`

---

## Part 2: Unresolved Items from Tonight's Session

These were flagged but never fixed:

### 1. Testimonial Collection Flow

A prompt exists at `.cursor/prompts/testimonial-collection-flow.md` but was never run.

- Read the prompt
- Evaluate: is the implementation realistic and useful?
- If yes: execute it (create the testimonial collection workflow)
- If incomplete or unclear: flag what's missing

### 2. Weather Trader — Price Enrichment Verification

- Price enrichment was deployed but never verified
- Check: does the weather trader actually fetch and use enriched price data?
- Check: is the enrichment source (weather API or market data) accessible from Docker?
- Run: start the weather trader briefly, check logs for enrichment activity
- If broken: fix the data pipeline

### 3. Spread Arb — Sizing Issues

- Spread arb has sizing issues with ~$50 free wallet balance
- Check `strategies/spread_arb.py` for minimum position size requirements
- If minimum order size > available balance → adjust minimums or add a "low-balance mode"
- The bot should gracefully handle low bankroll instead of erroring

### 4. D-Tools Cloud API Key

- D-Tools integration exists in `integrations/dtools/` but the API key was never generated
- This blocks: proposal → D-Tools project creation (Auto-16), equipment import
- **Action**: Add a placeholder in `.env.example` for `DTOOLS_API_KEY` and `DTOOLS_API_SECRET`
- Make all D-Tools calls gracefully degrade when key is missing (log warning, skip step, don't crash)

### 5. Email Auto-Responder — Draft vs Send Clarity

- `openclaw/auto_responder.py` exists but unclear if it's actually drafting replies
- Check: is it configured to draft only (save to Redis for Matt review) or send automatically?
- **Correct behavior**: DRAFT only — save to Redis queue `email:drafts` with proposed response. Matt reviews via Mission Control or iMessage before any email goes out.
- If it's currently auto-sending: disable auto-send, switch to draft mode
- If it's not doing anything: wire it into the email-monitor pipeline

---

## Part 3: Global Health Checks

Run these to verify the entire stack is coherent:

### Import Verification

```bash
# All strategy imports
python -c "
from strategies.polymarket_copytrade import PolymarketCopytrade
from strategies.strategy_manager import StrategyManager
from strategies.weather_trader import CheapBracketStrategy
from strategies.spread_arb import SpreadArbScanner
from strategies.exit_engine import ExitEngine
from strategies.kelly_sizing import KellySizer
from strategies.wallet_scoring import WalletScorer
from strategies.correlation_tracker import CorrelationTracker
from strategies.rbi_pipeline import RBIPipeline
print('All strategy imports OK')
"

# All openclaw imports
python -c "
from openclaw.auto_responder import AutoResponder
from openclaw.daily_briefing import DailyBriefing
from openclaw.sow_assembler import SOWAssembler
from openclaw.proposal_checker import ProposalChecker
from openclaw.preflight_check import PreflightCheck
print('All openclaw imports OK')
"

# Email monitor
python -c "from email_monitor.main import EmailMonitor; print('Email monitor OK')"

# Notification hub
python -c "from notification_hub.main import app; print('Notification hub OK')"
```

### Docker Service Health

```bash
# Check all 18 services are running
docker ps --format "{{.Names}}: {{.Status}}" | sort

# Check Redis connectivity from each container
for container in $(docker ps --format "{{.Names}}"); do
    echo -n "$container → Redis: "
    docker exec $container redis-cli -h 172.18.0.100 -a d1fff1065992d132b000c01d6012fa52 ping 2>/dev/null || echo "FAILED"
done

# Check VPN connectivity
docker exec gluetun ping -c 1 1.1.1.1
```

### Redis Data Integrity

```bash
redis-cli -h 172.18.0.100 -a d1fff1065992d132b000c01d6012fa52 <<'EOF'
# Portfolio snapshot exists and is recent
GET portfolio:snapshot

# Strategy signals are publishing
LLEN signals:weather_trader
LLEN signals:copytrade

# System health keys
GET system:health
KEYS bob:context:*

# Briefing data
GET briefing:daily
EOF
```

---

## Part 4: Lessons Learned — Update AGENT_LEARNINGS.md

Append to `AGENT_LEARNINGS.md`:

```markdown
## April 5, 2026 — Marathon Session Lessons

### Bugs Found and Fixed
1. X intake bridge was not publishing to Redis — always verify pub/sub channel connectivity
2. Kraken MM had dry_run=True hardcoded — never hardcode mode flags, always use config/env
3. Email monitor used BODY[] which marks emails as read — always use BODY.PEEK[]
4. Email message_id was generated from unstable UID — always use Message-ID header

### Architecture Observations
- Redis is the nervous system — if a service isn't publishing to Redis, downstream consumers silently get nothing
- All strategies need paper_runner.py integration BEFORE going live
- VPN is a critical dependency for trading — any VPN downtime = trading halt
- The auto-responder should NEVER auto-send — always draft and queue for human review

### Process Notes
- Shell scripts for targeted fixes, Cursor for larger builds
- Always use `bash scripts/pull.sh` on Bob to avoid rebase conflicts
- Config file updates baked into Docker images need `docker compose up -d --build [service]`
- All ports bind 127.0.0.1 except Mission Control 8098
```

---

## Part 5: Report

After all checks, update `cursor-prompts/VERIFICATION_REPORT.md`:

- Each check: PASS or FAIL
- Fixes applied in this run
- Unresolved items that need manual intervention (e.g., D-Tools API key)
- Overall status: READY or NEEDS ATTENTION

Commit everything. Push to origin main.
