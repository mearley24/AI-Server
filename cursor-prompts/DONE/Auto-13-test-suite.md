# Auto-13: Comprehensive Test Suite

## Context Files to Read First
- polymarket-bot/tests/ (existing tests)
- polymarket-bot/strategies/*.py
- polymarket-bot/src/*.py
- email-monitor/*.py
- scripts/imessage-server.py

## Prompt

The repo has ~200 Python files and minimal test coverage. Build a proper test suite:

1. **Polymarket bot tests** (`polymarket-bot/tests/`):
   - `test_weather_trader.py`: Mock NOAA/METAR responses, verify bracket selection logic, verify temp clustering blocks duplicates, verify entry price cap (25¢)
   - `test_copytrade.py`: Mock whale trade data, verify wallet scoring filters, verify category blacklist, verify crypto binary filter, verify dedup
   - `test_exit_engine.py`: Verify stop loss triggers at -30%, verify time-based exits, verify the 0.995 sell haircut
   - `test_strategy_manager.py`: Verify bankroll splits (40/35/25), verify SharedPositionRegistry blocks overlaps, verify correlation monitoring
   - `test_paper_runner.py`: Verify paper trades are logged correctly, verify dedup, verify resolution tracking
   - `test_spread_arb.py`: Verify complement arb detection, verify negative risk calculation, verify contrarian bounce logic
   - `test_mean_reversion.py`: Verify fade detection, verify volume threshold, verify exit rules
   - `test_rbi_pipeline.py`: Mock paper backtest, verify promotion logic (3 consecutive validates → live)

2. **Email monitor tests** (`email-monitor/tests/`):
   - `test_router.py`: Verify domain routing (21+ routes), verify auto-learn detection, verify fallback
   - `test_analyzer.py`: Mock OpenAI response, verify email classification (bid, support, vendor, spam)

3. **Integration tests** (`tests/integration/`):
   - `test_redis_connectivity.py`: Verify Redis pub/sub works (publish → subscribe round trip)
   - `test_imessage_bridge.py`: Mock HTTP to port 8199, verify message formatting
   - `test_notification_flow.py`: Verify trade → Redis → iMessage notification pipeline

4. **Test infrastructure**:
   - `conftest.py` with shared fixtures: mock Redis, mock HTTP clients, mock Gamma API responses, test wallet data
   - `pytest.ini` with sensible defaults, markers for `slow`, `integration`, `live`
   - GitHub Actions workflow (`.github/workflows/test.yml`): run `pytest -m "not live"` on every push
   - Coverage target: 60% on strategies/, 40% on everything else

5. **Run command**: `cd polymarket-bot && pytest -v --tb=short`

All tests should be self-contained with mocked external calls. No real API calls, no real Redis, no real money.
