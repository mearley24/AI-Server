# Auto-27: X/Twitter Autoposter — Bob Runs @symphonysmart

## The Vision

Bob posts to @symphonysmart on autopilot — project completion photos, industry tips, smart home insights, and engagement with the local community. Not spam, not AI slop. Curated, professional content that builds Symphony's brand while Matt focuses on installations.

## Context Files to Read First
- integrations/x_intake/pipeline.py (existing X intake — reads posts, this is the output side)
- integrations/x_intake/analyzer.py
- .env.example (X API keys section)
- knowledge/products/*.md
- AGENTS.md

## Prompt

Build the X/Twitter autoposter for @symphonysmart:

### 1. Content Pipeline (`integrations/x_post/content_generator.py`)

Generate post content from multiple sources:

a) **Project completions**: When a project is marked "Complete" in Linear → generate a post with:
   - "Just finished a [scope] install at a home in [city] — [highlight feature]"
   - Attach 1-2 best photos from the project (from Notes sync / iCloud)
   - Hashtags: #smarthome #control4 #homeautomation #[city]
   - Never include client name or full address

b) **Industry tips** (weekly): Generate from knowledge base:
   - "Pro tip: Always run dual Cat6 to every TV location — one for the TV, one for a streaming device"
   - "Why we use Araknis over consumer networking: managed VLANs, PoE budget control, and 5-year warranty"
   - Rotate through categories: networking, audio, lighting, security, automation

c) **Product highlights** (biweekly): Feature a product from the catalog:
   - "The Control4 Halo Remote — the best universal remote in the game. Backlit, rechargeable, custom buttons."
   - Link to manufacturer page

d) **Local engagement** (as detected): When intel feeds or news monitor detects relevant local news:
   - New construction boom in Vail Valley → "Exciting to see new builds going up in [area]. If you're building, now's the time to plan your low-voltage infrastructure."

### 2. Approval Queue (`integrations/x_post/approval_queue.py`)

Bob never posts without approval (initially):

- Generated posts go to a queue stored in SQLite `data/x_posts/queue.db`
- Bob sends the draft to Matt via iMessage: "Draft post: [content]. Reply YES to post, EDIT to modify, SKIP to drop."
- Matt replies YES → Bob posts immediately
- Matt replies with edits → Bob updates and reposts for approval
- After 50 approved posts with <3 edits, switch to auto-post with a 1-hour delay (Matt can cancel via iMessage during the window)

### 3. Posting Engine (`integrations/x_post/poster.py`)

- Use Twitter API v2 (already have keys in .env)
- Post text + up to 4 images
- Thread support: multi-tweet posts for longer content
- Schedule: max 1 post per day, vary timing (8-10am or 5-7pm MT)
- Never post on weekends (unless project completion — those are timely)
- Track engagement: likes, retweets, replies per post (fetch via API 24h after posting)

### 4. Analytics (`integrations/x_post/analytics.py`)

- Track per-post: impressions, likes, retweets, replies, link clicks
- Weekly report via iMessage: "X this week: 5 posts, 342 impressions, 23 likes, best post: [topic]"
- Monthly trend: follower growth, engagement rate, best-performing content type
- Store in SQLite `data/x_posts/analytics.db`

### 5. Content Calendar

- Monday: industry tip
- Wednesday: product highlight or project photo
- Friday: local engagement or smart home lifestyle post
- Completions: posted within 24h of project completion regardless of day

### 6. Safety Rails

- Every post screened for: client names, full addresses, pricing, internal details
- Block any post containing: dollar amounts, phone numbers, email addresses, street numbers
- Rate limit: max 1 post per day, max 7 per week
- If Twitter API returns an error, don't retry spam — wait 24 hours

### 7. Integration

- Publish post events to event bus (API-11)
- X analytics visible in Mission Control
- Content generation uses local Ollama when available (Auto-15/Auto-23)

Use standard logging.
