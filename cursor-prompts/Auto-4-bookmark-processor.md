# Auto-4: Bookmark Processor + Knowledge Categorizer

## Context Files to Read First
- integrations/x_intake/bookmark_scraper.py
- integrations/x_intake/video_transcriber.py

## Prompt

Build a bookmark batch processor that categorizes everything into 10 folders:

Create integrations/x_intake/bookmark_processor.py:

1. Read bookmarks from a JSON file (output of bookmark_scraper.py)
2. For each bookmark, analyze the content and auto-categorize into one of 10 folders:
   - Trading Strategies — anything about trading bots, algorithms, backtesting, market making
   - Prediction Markets — Polymarket, Kalshi, prediction market analysis
   - AI/Automation — AI agents, LLMs, automation tools, coding with AI
   - Smart Home/AV — Control4, home automation, AV integration, product reviews
   - Business — entrepreneurship, client management, proposals, sales
   - Crypto — cryptocurrency, DeFi, blockchain, NFTs
   - Development — coding, GitHub repos, tools, frameworks
   - Finance — markets, investing, economics, Fed, macro
   - Marketing — social media, content creation, branding
   - Reference — everything else worth saving

3. Use GPT-4o-mini to categorize based on the post text/transcript
4. Save categorized bookmarks to data/bookmarks/[folder_name]/ as individual markdown files
5. Generate a master index: data/bookmarks/INDEX.md listing all bookmarks by category with links
6. For video bookmarks, the transcript should already exist in data/transcripts/ — link to it

CLI: python bookmark_processor.py --input bookmarks.json --categorize
Output: categorized files in data/bookmarks/ + INDEX.md

Commit and push.
