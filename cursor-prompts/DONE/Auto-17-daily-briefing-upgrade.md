# Auto-17: Daily Briefing — Unified Morning Report

## Context Files to Read First
- openclaw/daily_briefing.py
- polymarket-bot/heartbeat/briefing.py
- integrations/telegram/daily_digest.py
- email-monitor/main.py
- calendar-agent/main.py

## Prompt

Build a unified daily briefing that Matt receives via iMessage every morning at 6:00 AM MT:

1. **Trading summary** (from polymarket-bot heartbeat):
   - Yesterday's P/L by strategy (weather, copytrade, spread/arb)
   - Total portfolio value and bankroll remaining
   - Best and worst trades
   - Any positions needing attention (near stop loss, approaching resolution)
   - Paper trading results if running

2. **Business summary** (from email-monitor + calendar-agent):
   - Unread emails requiring response (count + top 3 subjects)
   - Today's calendar events with times
   - Any new leads or bid invitations
   - Pending follow-ups due today
   - Active project status from Linear (any blocked issues)

3. **System health** (from Docker + Redis):
   - All services status (green/yellow/red one-liner)
   - Any containers that restarted overnight
   - VPN status
   - Disk usage if >70%

4. **Intelligence** (from intel feeds if running):
   - Top signals detected overnight
   - Any markets with big moves relevant to our positions
   - New high-volume markets worth watching

5. **Format**: Clean, scannable, no fluff. Use bullet points. Keep total briefing under 20 lines. Link to Mission Control for details.

6. **Implementation**:
   - Create `openclaw/daily_briefing_v2.py` that aggregates all sources
   - Query Redis for trading data, Docker for health, email-monitor API for inbox
   - Format as a single iMessage
   - Schedule via heartbeat runner at 6:00 AM MT (13:00 UTC)
   - Also publish to Redis `briefing:daily` for Mission Control history

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
