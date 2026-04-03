# Auto-29: Verify All Implementations — API-1, API-2, API-3, and All Completed Autos

## Purpose

Cursor completed API-1 (self-improving trading bot), API-2 (Bob business operator), API-3 (neural map), and the original 5 DONE tasks. This prompt verifies everything was implemented correctly, catches any loose ends, and ensures nothing is broken.

## Prompt

Run a full verification of every completed Cursor prompt. For each one, check that the code exists, imports resolve, and basic functionality works. Fix anything broken.

### 1. Verify DONE-1: Polymarket Strategy Fixes

- [ ] Temperature cluster dedup exists in `strategies/polymarket_copytrade.py`
- [ ] Entry price caps working: weather 25¢, sports 75¢, crypto 60¢
- [ ] Crypto binary filter blocks <30min markets
- [ ] Category blacklist blocks politics/geopolitics
- [ ] Wallet quality floor enforced (70% WR or 60%+3.0 P/L)
- [ ] Run: `python -c "from strategies.polymarket_copytrade import PolymarketCopytrade; print('OK')"`

### 2. Verify DONE-2: RBI Pipeline

- [ ] `strategies/rbi_pipeline.py` exists and imports cleanly
- [ ] `polymarket-bot/ideas.txt` is being read for pending entries
- [ ] Run: `python -c "from strategies.rbi_pipeline import RBIPipeline; print('OK')"`

### 3. Verify DONE-3: Bob Autonomy

- [ ] Auto-responder in `openclaw/auto_responder.py` imports cleanly
- [ ] Email routing config in `email-monitor/routing_config.json` has 21+ routes
- [ ] Run: `python -c "from openclaw.auto_responder import AutoResponder; print('OK')"`

### 4. Verify DONE-4: iCloud File Watcher

- [ ] `integrations/icloud_watch.py` exists
- [ ] Run: `python -c "import integrations.icloud_watch; print('OK')"` or verify syntax: `python -m py_compile integrations/icloud_watch.py`

### 5. Verify DONE-5: X Video Transcription

- [ ] `integrations/x_intake/video_transcriber.py` exists and imports
- [ ] Uses standard logging (not structlog) for anything called from imessage-server.py
- [ ] Run: `python -c "from integrations.x_intake.video_transcriber import VideoTranscriber; print('OK')"`

### 6. Verify API-1: Self-Improving Trading Bot

- [ ] `strategies/rbi_pipeline.py` — monitors ideas.txt, runs paper backtests, auto-promotes after 3 validates
- [ ] `src/order_flow_analyzer.py` or `strategies/crypto/cvd.py` — CVD divergence detector exists
- [ ] `strategies/strategy_manager.py` — starts all 3 strategies (weather 40%, copytrade 35%, CVD/arb 25%)
- [ ] `SharedPositionRegistry` prevents overlap between strategies
- [ ] `src/main.py` initializes StrategyManager
- [ ] Intel feeds auto-feeding ideas when signal score >80
- [ ] Run: `python -c "from strategies.strategy_manager import StrategyManager; print('OK')"`
- [ ] Run: `python -c "from strategies.rbi_pipeline import RBIPipeline; print('OK')"`

### 7. Verify API-2: Bob Business Operator

- [ ] Verify what was implemented — check git log for the API-2 commit
- [ ] Auto-responder drafts client replies autonomously
- [ ] Email workflow handles routing without manual intervention
- [ ] Daily briefing scheduled or callable
- [ ] Run relevant imports to verify no broken dependencies

### 8. Verify API-3: Neural Map

- [ ] Knowledge graph visualization exists
- [ ] Check what files were created/modified in the API-3 commit
- [ ] Verify imports and basic instantiation

### 9. Integration Test

Run the actual bot briefly and check logs:
```bash
# Check the bot starts without import errors
python -c "from src.main import main; print('Main imports OK')"

# Check all strategies import
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

# Check openclaw imports
python -c "
from openclaw.auto_responder import AutoResponder
from openclaw.daily_briefing import DailyBriefing
from openclaw.sow_assembler import SOWAssembler
from openclaw.proposal_checker import ProposalChecker
from openclaw.preflight_check import PreflightCheck
print('All openclaw imports OK')
"
```

### 10. Fix Anything Broken

For each failed check:
1. Read the error message
2. Fix the root cause (missing import, wrong path, syntax error)
3. Re-run the check to confirm
4. Commit the fix with message: "Fix: [description of what was broken]"

### 11. Report

After all checks, create `cursor-prompts/VERIFICATION_REPORT.md` with:
- Each check: PASS or FAIL
- Any fixes applied
- Any known issues that need manual intervention
- Overall status: READY or NEEDS ATTENTION

Commit everything and push to origin main.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
