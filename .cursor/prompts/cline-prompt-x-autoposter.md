# Cline Prompt: Build X/Twitter Autoposter for @symphonysmart

**Repo:** `mearley24/AI-Server` (on Bob)
**Goal:** Build the missing tools that the Telegram bot and API already reference. Create `tools/social_content.py`, `tools/x_poster.py`, and a cron-based auto-posting service. Content = smart home tips, project spotlights, industry insights for Vail Valley. Commit and push when done.

---

## IMPORTANT RULES
- Do NOT use the hash/pound character in any bash scripts (confuses Mac Terminal)
- The Telegram bot (`telegram-bob-remote/main.py`) already calls these tools — match the expected CLI interface exactly
- Use Ollama for content generation (Bob's `llama3.2:3b` at `http://192.168.1.189:11434` or Bert's `llama3.1:8b` at Bert's Tailscale IP)
- Fall back to OpenAI if Ollama is unavailable (key is in `.env` as `OPENAI_API_KEY`)
- X API credentials are in `.env`: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`
- Use `tweepy` for the X/Twitter API v2 (add to requirements if needed)
- Store data in `data/x_posts/` directory
- All times in Mountain Time (America/Denver)

---

## 1. CREATE `tools/social_content.py`

Content generator that creates posts for @symphonysmart. The Telegram bot calls it with these flags:

```
python3 tools/social_content.py --story --queue    (project story)
python3 tools/social_content.py --tip --queue      (daily tip)
python3 tools/social_content.py --video-prompt --queue  (video idea + tweet)
python3 tools/social_content.py --series --queue   (full week of content)
```

### Content Types

**a) Tips & Tricks (`--tip`)**
Generate smart home tips from these rotating categories. Use Ollama to generate, then clean/edit for tone.

Categories and example posts (generate variations, never repeat):
- **Networking:** "Pro tip: Run dual Cat6 to every TV location — one for the TV, one for a streaming box. Saves a headache later."
- **Audio:** "In-ceiling speakers sound best when placed at the 1/3 point of the room, not dead center. Small detail, big difference."
- **Lighting:** "Lutron shades + smart lighting scenes = the best way to manage glare in a mountain home with floor-to-ceiling windows."
- **Security:** "Wi-Fi cameras are fine for a doorbell. For real security, run PoE cameras on a dedicated VLAN with local NVR storage."
- **Automation:** "The best smart home is one you forget about. If you're pulling out your phone to turn on lights, the programming needs work."
- **Pre-wire:** "Building new? Get your AV integrator involved at framing — not after drywall. It's the cheapest decision you'll make."
- **Maintenance:** "Firmware updates aren't optional. Half the 'my system stopped working' calls we get are a missed firmware update."
- **General:** "The difference between a good install and a great one is cable management. If the rack looks clean, the system runs clean."

Rules for generated tips:
- 280 characters max (X limit with room for hashtags)
- Conversational tone — sounds like a real technician, not marketing
- No emojis except occasionally 🔧 or 💡
- Include 2-3 hashtags at the end: always `#smarthome` + 1-2 from: `#control4`, `#homeautomation`, `#vailvalley`, `#hometheater`, `#networking`, `#prewire`, `#audiovisual`
- Never include pricing, client names, or addresses

**b) Project Stories (`--story`)**
Read from project data. If `data/x_posts/projects_posted.json` doesn't have a project, generate a post:
- "Just wrapped a [scope] in [city]. [one interesting detail]. Clean wire, clean install."
- Pull from the symphonysh project data if accessible, or use generic templates for now
- Placeholder for photo attachment (the poster will handle actual media upload later)

**c) Video Prompts (`--video-prompt`)**
Generate a short video idea + caption:
- Video idea: "30-second walkthrough of a rack build — before and after"
- Caption: "Behind the scenes: what a properly built AV rack looks like. Every cable labeled, every connection tested. [hashtags]"

**d) Weekly Series (`--series`)**
Generate 5 posts for the week following the content calendar:
- Monday: Industry tip
- Tuesday: Engagement question ("What's the one smart home feature you can't live without?")
- Wednesday: Product spotlight or project photo
- Thursday: Behind-the-scenes / process tip
- Friday: Local/seasonal post ("Getting your outdoor audio ready for summer in the Vail Valley")

### Queue Storage

All generated posts go to SQLite: `data/x_posts/queue.db`

Table: `post_queue`
- `id` INTEGER PRIMARY KEY
- `content` TEXT (the post text)
- `post_type` TEXT (tip/story/video/series)
- `category` TEXT (networking/audio/lighting/etc)
- `status` TEXT DEFAULT 'pending' (pending/approved/posted/skipped)
- `created_at` TEXT (ISO timestamp)
- `scheduled_for` TEXT (ISO timestamp, nullable)
- `posted_at` TEXT (nullable)
- `x_post_id` TEXT (nullable, the tweet ID after posting)
- `media_paths` TEXT (nullable, JSON array of local image paths)

Output to stdout: the generated post text + queue confirmation.

---

## 2. CREATE `tools/x_poster.py`

The actual X/Twitter poster. Telegram bot calls it with:

```
python3 tools/x_poster.py --queue     (show pending posts)
python3 tools/x_poster.py --auto      (post next approved/pending item)
python3 tools/x_poster.py --usage     (show API usage stats)
python3 tools/x_poster.py --post-id N (post a specific queue item by ID)
```

### Implementation

Use `tweepy` with OAuth 1.0a (User Authentication):
```python
import tweepy

auth = tweepy.OAuth1UserHandler(
    os.environ['X_API_KEY'],
    os.environ['X_API_SECRET'],
    os.environ['X_ACCESS_TOKEN'],
    os.environ['X_ACCESS_TOKEN_SECRET']
)
client = tweepy.Client(
    consumer_key=os.environ['X_API_KEY'],
    consumer_secret=os.environ['X_API_SECRET'],
    access_token=os.environ['X_ACCESS_TOKEN'],
    access_token_secret=os.environ['X_ACCESS_TOKEN_SECRET']
)
```

### Safety Rails
- Max 1 post per 4 hours (configurable via `X_POST_INTERVAL_HOURS` env var, default 4)
- Max 3 posts per day
- Never post between 10pm-7am Mountain Time
- Block posts containing: dollar amounts, phone numbers, email addresses, street addresses
- If X API returns rate limit error, log it and don't retry for 24 hours
- Log every post to `data/x_posts/post_log.json` with timestamp, content, and X post ID

### --queue output format:
```
Pending Posts (3):
  [1] 💡 Tip: "Pro tip: Run dual Cat6..." (created 2h ago)
  [2] 📖 Story: "Just wrapped a home theater..." (created 1h ago)  
  [3] 💡 Tip: "Firmware updates aren't..." (created 30m ago)

Posted Today: 1/3
Last Post: 2h ago
```

### --usage output format:
```
X API Usage (@symphonysmart):
  Posts today: 1/3
  Posts this week: 5/21
  Posts this month: 18/500
  Last post: 2026-04-16 10:30 MDT
  Next allowed: 2026-04-16 14:30 MDT
```

---

## 3. CREATE AUTO-POST CRON SERVICE

Create `tools/x_auto_scheduler.py` — a lightweight scheduler that runs as a launchd service on Bob (not Docker):

### What it does:
1. Runs every 2 hours
2. Checks `data/x_posts/queue.db` for pending posts
3. If a post is pending AND enough time has passed since last post AND it's within posting hours → post it
4. Generate new content if the queue is running low (< 3 pending posts)
5. Log activity to `data/x_posts/scheduler.log`

### Content Calendar Logic:
```
if day == Monday:    generate tip
if day == Tuesday:   generate engagement question  
if day == Wednesday: generate project spotlight
if day == Thursday:  generate process/behind-scenes tip
if day == Friday:    generate local/seasonal post
```

### Create launchd plist: `scripts/launchd/com.symphony.x-autoposter.plist`

Schedule: every 2 hours from 8am to 8pm Mountain Time.

The plist should:
- Run `python3 /path/to/AI-Server/tools/x_auto_scheduler.py`
- Set working directory to AI-Server root
- Log stdout/stderr to `data/x_posts/scheduler.log`
- Use `StartCalendarInterval` with multiple entries for 8,10,12,14,16,18,20 hours

Also create `scripts/install-x-autoposter.sh` that:
- Copies plist to `~/Library/LaunchAgents/`
- Loads it with `launchctl load`
- Prints confirmation

---

## 4. CREATE `tools/seo_manager.py`

The Telegram bot also calls this for SEO tasks:

```
python3 tools/seo_manager.py --keywords    (keyword research)
python3 tools/seo_manager.py --local       (local SEO audit)
python3 tools/seo_manager.py --backlinks   (backlink opportunities)
python3 tools/seo_manager.py --meta        (generate meta tags)
```

### --keywords
Use Ollama to generate a keyword research report:
- Primary keywords: "smart home Vail", "home automation Eagle County", "Control4 dealer Vail Valley"
- Long-tail variations: "smart home pre-wire cost Vail", "TV mounting Beaver Creek", etc.
- Output formatted for readability

### --local
Check and report on local SEO factors:
- Is symphonysh.com loading? (HTTP check)
- Does the homepage have proper meta tags? (fetch and parse)
- List known directory listings status
- Recommendations

### --backlinks
Generate a list of potential backlink sources:
- Local business directories
- Industry associations (CEDIA, etc.)
- Builder/contractor partner sites
- Local media (Vail Daily, etc.)

### --meta
Generate optimized meta tags for key pages:
- Homepage, Services, About, Contact, each service page
- Output as JSON with title, description, keywords per page

---

## 5. WIRE UP DEPENDENCIES

### Add to requirements files:
If `tools/requirements.txt` exists, add:
```
tweepy>=4.14.0
```

If not, create `tools/requirements.txt` with:
```
tweepy>=4.14.0
```

### Create data directory:
```
mkdir -p data/x_posts
```

### Verify .env has X credentials:
Add a check at the top of `x_poster.py` that prints a clear error if X_API_KEY is not set:
```
if not os.environ.get('X_API_KEY'):
    print("ERROR: X_API_KEY not set in .env. See .env.example section 12.")
    sys.exit(1)
```

---

## COMMIT MESSAGE
```
feat: build X autoposter + SEO tools — social_content.py, x_poster.py, x_auto_scheduler.py, seo_manager.py
```

Push to main when done.

---

## 6. POST-BUILD STEPS (DO THESE BEFORE COMMITTING)

These are part of the prompt — execute all of them:

1. **Install tweepy:** Run `pip install tweepy` (or `pip3 install tweepy`) on Bob. If a venv is in use, install there.
2. **Create data directory:** `mkdir -p data/x_posts`
3. **Check .env for X credentials:** Read the `.env` file and verify `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` are set (not placeholder values). If they are still `your_api_key_here` or missing, print a clear warning to the terminal: "WARNING: X API credentials not set in .env — see .env.example section 12. Auto-posting will not work until these are configured."
4. **Install the launchd scheduler:** Run `bash scripts/install-x-autoposter.sh` to copy the plist and load it.
5. **Test content generation:** Run `python3 tools/social_content.py --tip --queue` and verify it outputs a generated tip and confirms it was queued.
6. **Test queue display:** Run `python3 tools/x_poster.py --queue` and verify it shows the pending post.
7. **If X credentials are set**, run `python3 tools/x_poster.py --auto` to post the first test tweet. If credentials are not set, skip this step and print the warning again.
