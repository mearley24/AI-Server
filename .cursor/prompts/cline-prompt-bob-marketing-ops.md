# Cline Prompt: Bob Runs Marketing Ops — GBP, Ads Monitoring, Weekly Reports

**Repo:** `mearley24/AI-Server` (on Bob)
**Goal:** Make Bob the owner of all ongoing marketing operations — automated Google Business Profile posting, Google Ads/Analytics monitoring, and weekly performance reports via iMessage. Commit and push when done.

---

## IMPORTANT RULES
- Do NOT use the hash/pound character in any bash scripts
- Use Ollama for content generation (Bob's llama3.2:3b at http://192.168.1.189:11434)
- Fall back to OpenAI if Ollama is unavailable
- All times in Mountain Time (America/Denver)
- Store credentials in `.env` — never hardcode them
- iMessage notifications go through the existing bridge at `http://host.docker.internal:8199`

---

## 1. GOOGLE BUSINESS PROFILE AUTO-POSTER (`tools/gbp_poster.py`)

Bob posts to the Google Business Profile weekly. The GBP API requires OAuth2, which is more setup than it's worth for one location. Instead, use the simpler approach:

### Option A: GBP API (if Matt sets up OAuth)

Add these to `.env.example` under a new section:

```
# Google Business Profile API
GBP_ACCOUNT_ID=your_account_id
GBP_LOCATION_ID=your_location_id
GBP_OAUTH_CLIENT_ID=your_client_id
GBP_OAUTH_CLIENT_SECRET=your_client_secret
GBP_OAUTH_REFRESH_TOKEN=your_refresh_token
```

Create `tools/gbp_poster.py`:
- CLI: `python3 tools/gbp_poster.py --post "content"` or `--auto` (generate and post)
- Uses Google Business Profile API v4 to create LocalPosts
- Post types: STANDARD with summary text + optional CTA button ("LEARN_MORE" linking to symphonysh.com/scheduling)
- If GBP credentials are not set, skip gracefully and log a warning

### Option B: Content-only mode (always works, no API needed)

If GBP API credentials are not configured, `gbp_poster.py --auto` should:
1. Generate a GBP-ready post (same content pipeline as X but formatted for GBP — longer, 1500 char limit, more descriptive)
2. Save it to `data/gbp_posts/` as a markdown file with the date
3. Send it to Matt via iMessage: "GBP post ready — copy/paste to your Google Business Profile:\n\n[content]"
4. Matt copies it into GBP manually (takes 10 seconds)

This is the fallback and should always work. Content types for GBP:
- **Week 1:** Project spotlight — "Just completed a [type] install in [city]. [detail]. Schedule a consultation: symphonysh.com/scheduling"
- **Week 2:** Smart home tip — longer version of the X tips, more educational
- **Week 3:** Seasonal/local post — "Getting ready for [season] in the Vail Valley? Here's what to think about for your smart home."
- **Week 4:** Service highlight — deep description of one service with CTA

Create `data/gbp_posts/` directory.

---

## 2. GOOGLE ADS MONITOR (`tools/ads_monitor.py`)

A lightweight script that checks Google Ads performance and alerts Matt if something needs attention.

### Add to `.env.example`:
```
# Google Ads API (for monitoring only)
GOOGLE_ADS_CUSTOMER_ID=your_customer_id
GOOGLE_ADS_DEVELOPER_TOKEN=your_developer_token
GOOGLE_ADS_OAUTH_CLIENT_ID=your_client_id
GOOGLE_ADS_OAUTH_CLIENT_SECRET=your_client_secret
GOOGLE_ADS_OAUTH_REFRESH_TOKEN=your_refresh_token
```

### Create `tools/ads_monitor.py`:

CLI: `python3 tools/ads_monitor.py --check` or `--report`

**--check** (runs daily):
- If Google Ads API credentials are not set, fall back to a simple spend reminder via iMessage: "Reminder: Google Ads are running. Check performance at ads.google.com. Budget: $10-15/day."
- If credentials ARE set, use the Google Ads API to pull:
  - Spend today / this week / this month
  - Clicks and impressions
  - Cost per click
  - Conversions (if tracking is set up)
- Alert via iMessage if:
  - Daily spend exceeds $20 (budget overrun)
  - Click-through rate drops below 1% (ad fatigue)
  - Zero clicks in 24 hours (something broken)
  - Monthly spend approaching $500 (budget cap warning)

**--report** (runs weekly):
- Generate a summary of the week's Ads performance
- Compare to previous week
- Send via iMessage

### Graceful degradation:
If no Google Ads API credentials, the monitor just sends a weekly iMessage reminder: "Weekly check-in: Review your Google Ads at ads.google.com — you're on a $X/day budget. Look at: clicks, cost per click, and whether you got any calls from ads."

---

## 3. SEARCH CONSOLE MONITOR (`tools/search_console_monitor.py`)

### Add to `.env.example`:
```
# Google Search Console
GSC_SITE_URL=https://symphonysh.com
GSC_OAUTH_CLIENT_ID=your_client_id
GSC_OAUTH_CLIENT_SECRET=your_client_secret
GSC_OAUTH_REFRESH_TOKEN=your_refresh_token
```

### Create `tools/search_console_monitor.py`:

CLI: `python3 tools/search_console_monitor.py --check`

**If credentials are set:**
- Pull top queries, impressions, clicks, average position for the week
- Check for crawl errors
- Alert if any pages drop out of index
- Report top-performing keywords

**If credentials are NOT set:**
- Remind Matt via iMessage: "Search Console check: Visit search.google.com/search-console to see how symphonysh.com is ranking. Submit sitemap if not done: https://symphonysh.com/sitemap.xml"

---

## 4. WEEKLY MARKETING REPORT (`tools/marketing_report.py`)

Unified weekly report sent every Monday at 9am MT via iMessage.

CLI: `python3 tools/marketing_report.py`

Pulls together data from all sources:

```
📊 Weekly Marketing Report — Symphony Smart Homes
Week of April 14-20, 2026

🐦 X (@symphonysmart):
  Posts this week: 5
  [list of posts with content preview]
  
📍 Google Business Profile:
  Post published: "Just completed a home theater in Beaver Creek..."
  [or] "No GBP post this week — generate one: python3 tools/gbp_poster.py --auto"

💰 Google Ads:
  [stats if available, or reminder to check manually]

🔍 Organic Search:
  [Search Console stats if available, or reminder]

📋 Action Items:
  - [any reviews to respond to]
  - [any blog posts due]
  - [any content to approve]
```

If most APIs aren't configured yet, the report still works — it just shows X stats (from the local queue.db) and reminders for the manual stuff.

---

## 5. LAUNCHD SCHEDULER

Create `scripts/launchd/com.symphony.marketing-ops.plist`:

Runs `tools/marketing_ops_scheduler.py` which handles the schedule:

```python
#!/usr/bin/env python3
"""Marketing ops scheduler — runs daily, handles weekly tasks on the right days."""
import os, sys, subprocess
from datetime import datetime

now = datetime.now()
day = now.strftime('%A')
hour = now.hour

AI_SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run(script, args=""):
    cmd = f"python3 {AI_SERVER}/tools/{script} {args}"
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True, cwd=AI_SERVER)

# Daily: Ads check (if configured)
run("ads_monitor.py", "--check")

# Monday 9am: Weekly marketing report
if day == "Monday" and 8 <= hour <= 10:
    run("marketing_report.py")

# Wednesday: GBP post
if day == "Wednesday":
    run("gbp_poster.py", "--auto")

# Friday: Search Console check
if day == "Friday":
    run("search_console_monitor.py", "--check")
```

Schedule: runs daily at 9am MT.

Create `scripts/install-marketing-ops.sh`:
- Copies plist to `~/Library/LaunchAgents/`
- Loads with `launchctl load`
- Prints confirmation

---

## 6. TELEGRAM BOT INTEGRATION

Add marketing ops commands to the existing SEO menu in `telegram-bob-remote/main.py`:

Add buttons:
- "📍 GBP Post" → `action_gbp_post` → runs `python3 tools/gbp_poster.py --auto`
- "📊 Ads Check" → `action_ads_check` → runs `python3 tools/ads_monitor.py --check`
- "📈 Weekly Report" → `action_marketing_report` → runs `python3 tools/marketing_report.py`

Wire these into the existing `menu_seo` callback section alongside the existing X posting buttons.

---

## 7. INSTALL AND TEST

1. `mkdir -p data/gbp_posts`
2. `bash scripts/install-marketing-ops.sh`
3. Test: `python3 tools/gbp_poster.py --auto` — should generate a GBP post and send via iMessage
4. Test: `python3 tools/marketing_report.py` — should generate and send the weekly report
5. Test: `python3 tools/ads_monitor.py --check` — should send a reminder (no API keys expected yet)

---

## COMMIT MESSAGE
```
feat: Bob runs marketing ops — GBP poster, Ads monitor, Search Console, weekly reports
```

Push to main when done.
