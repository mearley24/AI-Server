# Cline Prompt: Verify X Autoposter + Test Post

**Repo:** `mearley24/AI-Server` (on Bob)
**Goal:** Verify the X autoposter tools built by the previous prompt are working, check credentials, and fire a test post.

---

## Steps

1. **Verify files exist:**
   - `tools/social_content.py`
   - `tools/x_poster.py`
   - `tools/x_auto_scheduler.py`
   - `tools/seo_manager.py`
   - `scripts/launchd/com.symphony.x-autoposter.plist`
   - `scripts/install-x-autoposter.sh`
   - `data/x_posts/` directory (create if missing: `mkdir -p data/x_posts`)

   If any tool files are missing, report which ones and stop.

2. **Check tweepy is installed:** Run `python3 -c "import tweepy; print(tweepy.__version__)"`. If missing, run `pip3 install tweepy`.

3. **Check X API credentials in .env:** Verify these are set and NOT placeholder values:
   - `X_API_KEY`
   - `X_API_SECRET`
   - `X_ACCESS_TOKEN`
   - `X_ACCESS_TOKEN_SECRET`

   Print a summary: "X credentials: OK" or list which ones are missing/placeholder.

4. **Test content generation:** Run `python3 tools/social_content.py --tip --queue` — verify it generates a tip and queues it.

5. **Show the queue:** Run `python3 tools/x_poster.py --queue` — verify the pending post shows up.

6. **Test post (if credentials are OK):** Run `python3 tools/x_poster.py --auto` — post the queued tip to @symphonysmart. Report the result.

7. **Check launchd scheduler:** Run `launchctl list | grep symphony.x` to see if the auto-poster plist is loaded. If not, run `bash scripts/install-x-autoposter.sh`.

8. **Report results** — print a summary of what passed and what needs attention.

No commit needed unless you fix something.
