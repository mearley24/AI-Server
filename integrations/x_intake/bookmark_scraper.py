"""X Bookmark Scraper — extracts all bookmarks from your X/Twitter account.

Uses Playwright to scroll through the bookmarks page and collect all post URLs.
Requires you to be logged into X in the browser.

Usage:
    python bookmark_scraper.py [--max 500] [--output bookmarks.json]

Outputs JSON with: post_id, url, author, text preview, has_video, timestamp
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path


async def scrape_bookmarks(max_bookmarks: int = 500, output_path: str = "bookmarks.json", profile_dir: str = None):
    """Scrape bookmarks from X using Playwright.
    
    Uses your existing browser session (cookies) so you don't need to log in.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Installing playwright...")
        os.system("pip3 install --break-system-packages playwright")
        os.system("python3 -m playwright install chromium")
        from playwright.async_api import async_playwright

    bookmarks = []
    seen_ids = set()

    async with async_playwright() as p:
        # Use persistent context to keep cookies/login
        if not profile_dir:
            profile_dir = os.path.expanduser("~/.x_profile")

        browser = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,  # Needs to be visible first time for login
            viewport={"width": 1280, "height": 900},
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        print("Navigating to X bookmarks...")
        await page.goto("https://x.com/i/bookmarks", wait_until="networkidle", timeout=30000)

        # Check if we need to log in
        if "login" in page.url.lower():
            print("\n⚠️  You need to log in to X first.")
            print("The browser window is open — log in manually, then press Enter here.")
            input("Press Enter after logging in...")
            await page.goto("https://x.com/i/bookmarks", wait_until="networkidle", timeout=30000)

        print("Scrolling and collecting bookmarks...")
        last_count = 0
        no_new_count = 0

        while len(bookmarks) < max_bookmarks and no_new_count < 5:
            # Extract tweet links from the page
            tweets = await page.query_selector_all('article[data-testid="tweet"]')

            for tweet in tweets:
                try:
                    # Get the permalink
                    links = await tweet.query_selector_all('a[href*="/status/"]')
                    post_url = None
                    post_id = None
                    for link in links:
                        href = await link.get_attribute("href")
                        if href and "/status/" in href and "/photo/" not in href and "/analytics" not in href:
                            post_url = f"https://x.com{href}" if href.startswith("/") else href
                            # Extract ID
                            parts = href.split("/status/")
                            if len(parts) > 1:
                                post_id = parts[1].split("/")[0].split("?")[0]
                            break

                    if not post_id or post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    # Get author
                    author_el = await tweet.query_selector('div[data-testid="User-Name"] a')
                    author = ""
                    if author_el:
                        author_href = await author_el.get_attribute("href")
                        author = author_href.strip("/") if author_href else ""

                    # Get text preview
                    text_el = await tweet.query_selector('div[data-testid="tweetText"]')
                    text = ""
                    if text_el:
                        text = await text_el.inner_text()

                    # Check for video
                    video_el = await tweet.query_selector('video, div[data-testid="videoPlayer"]')
                    has_video = video_el is not None

                    # Check for images
                    img_els = await tweet.query_selector_all('img[src*="pbs.twimg.com/media"]')
                    has_images = len(img_els) > 0

                    bookmarks.append({
                        "post_id": post_id,
                        "url": post_url,
                        "author": author,
                        "text": text[:500],
                        "has_video": has_video,
                        "has_images": has_images,
                        "scraped_at": time.time(),
                    })

                    if len(bookmarks) % 10 == 0:
                        print(f"  Collected {len(bookmarks)} bookmarks...")

                except Exception as e:
                    continue

            # Check if we found new ones
            if len(bookmarks) == last_count:
                no_new_count += 1
            else:
                no_new_count = 0
            last_count = len(bookmarks)

            # Scroll down
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await asyncio.sleep(2)

        await browser.close()

    # Save results
    output = {
        "total": len(bookmarks),
        "scraped_at": time.time(),
        "bookmarks": bookmarks,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    # Stats
    with_video = sum(1 for b in bookmarks if b["has_video"])
    with_images = sum(1 for b in bookmarks if b["has_images"])
    text_only = len(bookmarks) - with_video - with_images

    print(f"\nDone! Collected {len(bookmarks)} bookmarks:")
    print(f"  Videos: {with_video}")
    print(f"  Images: {with_images}")
    print(f"  Text only: {text_only}")
    print(f"  Saved to: {output_path}")

    return bookmarks


async def process_bookmarks(bookmarks_path: str = "bookmarks.json", batch_size: int = 5):
    """Process all bookmarks — fetch full text, transcribe videos, analyze."""
    from video_transcriber import process_x_video

    with open(bookmarks_path) as f:
        data = json.load(f)

    bookmarks = data.get("bookmarks", [])
    print(f"Processing {len(bookmarks)} bookmarks...")

    results = []
    for i, bm in enumerate(bookmarks):
        print(f"\n[{i+1}/{len(bookmarks)}] @{bm['author']} — {bm['text'][:60]}")

        if bm.get("has_video"):
            print("  Downloading + transcribing video...")
            result = process_x_video(
                post_url=bm["url"],
                post_id=bm["post_id"],
                author=bm["author"],
                post_text=bm["text"],
            )
            results.append(result)
            if "error" not in result:
                print(f"  ✓ Transcribed — {result.get('transcript_length', 0)} chars")
            else:
                print(f"  ✗ {result['error']}")
        else:
            print("  Text-only post — analyzing...")
            # For text posts, just analyze the text directly
            from video_transcriber import analyze_transcript, save_transcript, format_imessage_summary
            analysis = analyze_transcript(bm["text"], bm["author"], bm["text"])
            if "error" not in analysis:
                path = save_transcript(bm["post_id"], bm["author"], bm["text"], analysis)
                results.append({
                    "post_id": bm["post_id"],
                    "author": bm["author"],
                    "summary": format_imessage_summary(bm["author"], analysis),
                    "transcript_path": path,
                })
                print(f"  ✓ Analyzed — {len(analysis.get('flags', []))} flags")

        # Rate limit
        if (i + 1) % batch_size == 0:
            print(f"\n  Pausing 10s to avoid rate limits...")
            await asyncio.sleep(10)

    # Save master summary
    summary_path = Path(os.environ.get("TRANSCRIPT_DIR", "/data/transcripts")) / "_master_summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with open(summary_path, "w") as f:
        f.write("# Bookmark Analysis — Master Summary\n\n")
        f.write(f"Total bookmarks processed: {len(results)}\n\n")
        for r in results:
            if "summary" in r:
                f.write(f"---\n{r['summary']}\n\n")

    print(f"\nMaster summary saved to: {summary_path}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="X Bookmark Scraper")
    parser.add_argument("--max", type=int, default=500, help="Max bookmarks to collect")
    parser.add_argument("--output", default="bookmarks.json", help="Output file")
    parser.add_argument("--process", action="store_true", help="Process after scraping")
    parser.add_argument("--process-only", type=str, help="Process existing bookmarks file")
    args = parser.parse_args()

    if args.process_only:
        asyncio.run(process_bookmarks(args.process_only))
    else:
        bookmarks = asyncio.run(scrape_bookmarks(args.max, args.output))
        if args.process:
            asyncio.run(process_bookmarks(args.output))
