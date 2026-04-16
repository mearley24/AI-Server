"""
tools/social_content.py — X/Twitter content generator for @symphonysmart
Generates smart home tips, project stories, video prompts, and weekly series.
Uses Ollama (llama3.2:3b on Bob) with OpenAI fallback.
"""

import os
import sys
import json
import sqlite3
import random
import argparse
import datetime
import requests
from pathlib import Path

AI_SERVER_DIR = Path(__file__).parent.parent
DATA_DIR = AI_SERVER_DIR / "data" / "x_posts"
DB_PATH = DATA_DIR / "queue.db"
PROJECTS_POSTED = DATA_DIR / "projects_posted.json"

OLLAMA_BOB_URL = "http://192.168.1.189:11434"
OLLAMA_MODEL = "llama3.2:3b"

TIP_CATEGORIES = [
    "networking",
    "audio",
    "lighting",
    "security",
    "automation",
    "pre-wire",
    "maintenance",
    "general",
]

CATEGORY_CONTEXT = {
    "networking": "Run dual Cat6 to every TV location — one for the TV, one for a streaming box. Saves a headache later.",
    "audio": "In-ceiling speakers sound best when placed at the 1/3 point of the room, not dead center. Small detail, big difference.",
    "lighting": "Lutron shades + smart lighting scenes = the best way to manage glare in a mountain home with floor-to-ceiling windows.",
    "security": "Wi-Fi cameras are fine for a doorbell. For real security, run PoE cameras on a dedicated VLAN with local NVR storage.",
    "automation": "The best smart home is one you forget about. If you're pulling out your phone to turn on lights, the programming needs work.",
    "pre-wire": "Building new? Get your AV integrator involved at framing — not after drywall. It's the cheapest decision you'll make.",
    "maintenance": "Firmware updates aren't optional. Half the 'my system stopped working' calls we get are a missed firmware update.",
    "general": "The difference between a good install and a great one is cable management. If the rack looks clean, the system runs clean.",
}

HASHTAG_OPTIONS = [
    "#control4",
    "#homeautomation",
    "#vailvalley",
    "#hometheater",
    "#networking",
    "#prewire",
    "#audiovisual",
]

BLOCKED_PATTERNS = [
    r"\$\d",
    r"\d{3}[-.\s]\d{3}[-.\s]\d{4}",
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    r"\d+\s+[A-Z][a-z]+\s+(St|Ave|Rd|Blvd|Dr|Ln|Way|Ct|Pl)",
]


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS post_queue (
            id INTEGER PRIMARY KEY,
            content TEXT,
            post_type TEXT,
            category TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            scheduled_for TEXT,
            posted_at TEXT,
            x_post_id TEXT,
            media_paths TEXT
        )
    """)
    conn.commit()
    return conn


def call_ollama(prompt, model=OLLAMA_MODEL, base_url=OLLAMA_BOB_URL):
    """Try Ollama first, return None if unavailable."""
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass
    return None


def call_openai(prompt):
    """Fall back to OpenAI GPT-4o-mini."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a smart home technician at Symphony Smart Homes in Vail Valley, Colorado. "
                        "Write concise, authentic posts for @symphonysmart on X/Twitter. "
                        "Sound like a real technician, not marketing copy. No emojis except 🔧 or 💡 occasionally."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=150,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


def call_llm(prompt):
    """Try Ollama, fall back to OpenAI, fall back to template."""
    result = call_ollama(prompt)
    if result:
        return result
    result = call_openai(prompt)
    if result:
        return result
    return None


def pick_hashtags(category=None, count=2):
    """Pick 2-3 hashtags, always including smarthome."""
    options = list(HASHTAG_OPTIONS)
    if category:
        cat_map = {
            "networking": "#networking",
            "audio": "#audiovisual",
            "lighting": "#homeautomation",
            "security": "#homeautomation",
            "automation": "#homeautomation",
            "pre-wire": "#prewire",
            "maintenance": "#homeautomation",
            "general": "#homeautomation",
        }
        preferred = cat_map.get(category)
        if preferred and preferred in options:
            options.remove(preferred)
            chosen = random.sample(options, min(count - 1, len(options)))
            chosen.append(preferred)
        else:
            chosen = random.sample(options, min(count, len(options)))
    else:
        chosen = random.sample(options, min(count, len(options)))
    return "#smarthome " + " ".join(chosen)


def truncate_to_limit(text, limit=280):
    """Truncate text to X character limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def add_to_queue(conn, content, post_type, category=None):
    """Insert post into queue.db."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO post_queue (content, post_type, category, status, created_at) VALUES (?,?,?,?,?)",
        (content, post_type, category, "pending", now),
    )
    conn.commit()


def generate_tip(category=None, queue=False):
    """Generate a smart home tip post."""
    if not category:
        category = random.choice(TIP_CATEGORIES)

    example = CATEGORY_CONTEXT.get(category, CATEGORY_CONTEXT["general"])
    hashtags = pick_hashtags(category)

    prompt = (
        f"Write a single X/Twitter post (tip) about smart home {category} for @symphonysmart. "
        f"Here is an example of the style: '{example}' "
        f"Rules: under 200 characters (hashtags added separately), conversational tone like a real AV technician, "
        f"no emojis except occasionally 🔧 or 💡, no pricing, no client names, no addresses, "
        f"Vail Valley Colorado context when relevant. "
        f"Output only the post text, no quotes, no explanation."
    )

    generated = call_llm(prompt)
    if generated:
        body = generated.strip().strip('"').strip("'")
    else:
        body = example

    post = truncate_to_limit(f"{body} {hashtags}")

    if queue:
        conn = get_db()
        add_to_queue(conn, post, "tip", category)
        conn.close()
        print(f"Generated tip ({category}):\n{post}\n\nAdded to queue.")
    else:
        print(post)

    return post


def generate_story(queue=False):
    """Generate a project story post."""
    ensure_data_dir()

    posted = {}
    if PROJECTS_POSTED.exists():
        with open(PROJECTS_POSTED) as f:
            posted = json.load(f)

    scopes = [
        "full home theater + distributed audio",
        "whole-home networking + Control4 automation",
        "outdoor audio + lighting control",
        "Lutron shading + lighting overhaul",
        "network redesign + camera system",
        "home theater + Control4 integration",
        "multi-room audio + Sonos setup",
    ]
    cities = [
        "Vail", "Beaver Creek", "Avon", "Eagle", "Edwards", "Minturn", "Arrowhead"
    ]
    details = [
        "Custom rack build, every cable labeled front to back.",
        "Lutron + Control4 integration — one button does the whole house.",
        "Ran fresh Cat6 to every room during a partial remodel window.",
        "Old system ripped out, new one built right from the ground up.",
        "Client said it was the cleanest rack they'd ever seen. We'll take it.",
        "Outdoor audio now reaches the hot tub — mountain summer sorted.",
        "Pre-wire during framing saved the homeowner a major headache.",
    ]

    scope = random.choice(scopes)
    city = random.choice(cities)
    detail = random.choice(details)
    hashtags = pick_hashtags(count=2)

    prompt = (
        f"Write a brief X/Twitter project story post for @symphonysmart. "
        f"Project scope: {scope} in {city}, Colorado. "
        f"Interesting detail: {detail} "
        f"Format: 'Just wrapped [scope] in [city]. [detail] Clean wire, clean install.' "
        f"Keep it under 200 characters (hashtags added separately). "
        f"No client names, no addresses, no pricing. Sound like a real AV technician. "
        f"Output only the post text, no quotes."
    )

    generated = call_llm(prompt)
    if generated:
        body = generated.strip().strip('"').strip("'")
    else:
        body = f"Just wrapped a {scope} in {city}. {detail} Clean wire, clean install."

    post = truncate_to_limit(f"{body} {hashtags}")

    if queue:
        conn = get_db()
        add_to_queue(conn, post, "story", "project")
        conn.close()
        project_key = f"{scope}_{city}"
        posted[project_key] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(PROJECTS_POSTED, "w") as f:
            json.dump(posted, f, indent=2)
        print(f"Generated story:\n{post}\n\nAdded to queue.")
    else:
        print(post)

    return post


def generate_video_prompt(queue=False):
    """Generate a short video idea + caption."""
    video_ideas = [
        ("30-second rack build before/after", "Before and after: what a properly built AV rack looks like. Every cable labeled, every connection tested."),
        ("in-ceiling speaker install timelapse", "From bare ceiling to music in every room. This is what a proper in-ceiling speaker install looks like."),
        ("Control4 scene demo", "One button. Lights, shades, audio, TV — all set for movie night. This is home automation done right."),
        ("cable management close-up", "This is what the back of your rack should look like. Clean cables, labeled connections, room to breathe."),
        ("outdoor speaker placement walkthrough", "Where you put outdoor speakers matters more than which ones you buy. Here's how we do it."),
        ("network rack build timelapse", "Building a proper network rack for a mountain home. Every switch, every cable, every label."),
    ]

    idea, caption_base = random.choice(video_ideas)
    hashtags = pick_hashtags(count=2)

    prompt = (
        f"Write an X/Twitter caption for a short video about: {idea}. "
        f"Use this as inspiration: '{caption_base}' "
        f"Keep it under 200 characters (hashtags added separately). "
        f"Conversational tone, sounds like a real AV technician, no emojis except 🔧 or 💡 occasionally. "
        f"Output only the caption text, no quotes."
    )

    generated = call_llm(prompt)
    if generated:
        caption = generated.strip().strip('"').strip("'")
    else:
        caption = caption_base

    post = truncate_to_limit(f"{caption} {hashtags}")

    video_idea_text = f"VIDEO IDEA: {idea}"

    if queue:
        conn = get_db()
        add_to_queue(conn, post, "video", "video")
        conn.close()
        print(f"{video_idea_text}\n\nGenerated caption:\n{post}\n\nAdded to queue.")
    else:
        print(f"{video_idea_text}\n\n{post}")

    return post


def generate_series(queue=False):
    """Generate 5 posts for the week (Mon-Fri content calendar)."""
    posts = []

    day_configs = [
        ("Monday", "tip", None),
        ("Tuesday", "engagement", None),
        ("Wednesday", "story", None),
        ("Thursday", "tip", "general"),
        ("Friday", "local", None),
    ]

    engagement_questions = [
        "What's the one smart home feature you can't live without?",
        "Control4 or Savant — what are you running? Drop it below.",
        "What's the biggest AV mistake you've seen in a new build?",
        "How many zones of audio do you have in your home? Be honest.",
        "Best part of a fully automated mountain home? We'll start: waking up to the right lighting scene every morning.",
    ]

    local_posts = [
        f"Getting your outdoor audio ready for summer in the Vail Valley. Now's the time to test those outdoor speakers before the deck fills up. {pick_hashtags('audio', 2)}",
        f"Ski season means dusty racks and forgotten firmware updates. Spring is a good time to run a full system checkup. {pick_hashtags('maintenance', 2)}",
        f"Mountain home humidity swings are hard on electronics. Make sure your equipment rack has ventilation — not just a closed cabinet door. {pick_hashtags('general', 2)}",
        f"If you're building in the Vail Valley this summer, now is the time to get your AV integrator involved. Don't wait for drywall. {pick_hashtags('pre-wire', 2)}",
    ]

    conn = get_db() if queue else None

    for day, content_type, category in day_configs:
        if content_type == "tip":
            post = generate_tip(category, queue=False)
            post_type = "tip"
            cat = category or "general"
        elif content_type == "engagement":
            q = random.choice(engagement_questions)
            hashtags = pick_hashtags(count=2)
            post = truncate_to_limit(f"{q} {hashtags}")
            post_type = "engagement"
            cat = "engagement"
        elif content_type == "story":
            post = generate_story(queue=False)
            post_type = "story"
            cat = "project"
        elif content_type == "local":
            post = random.choice(local_posts)
            post_type = "local"
            cat = "local"
        else:
            continue

        posts.append((day, post_type, post))
        print(f"{day} ({post_type}):\n{post}\n")

        if queue and conn:
            add_to_queue(conn, post, post_type, cat)

    if queue and conn:
        conn.close()
        print(f"Added {len(posts)} posts to queue.")

    return posts


def main():
    parser = argparse.ArgumentParser(description="X/Twitter content generator for @symphonysmart")
    parser.add_argument("--tip", action="store_true", help="Generate a smart home tip")
    parser.add_argument("--story", action="store_true", help="Generate a project story")
    parser.add_argument("--video-prompt", action="store_true", help="Generate a video idea + caption")
    parser.add_argument("--series", action="store_true", help="Generate a full week of content")
    parser.add_argument("--queue", action="store_true", help="Add generated content to queue.db")
    parser.add_argument("--category", type=str, help="Tip category override")
    args = parser.parse_args()

    dotenv_path = AI_SERVER_DIR / ".env"
    if dotenv_path.exists():
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    if args.tip:
        generate_tip(category=args.category, queue=args.queue)
    elif args.story:
        generate_story(queue=args.queue)
    elif args.video_prompt:
        generate_video_prompt(queue=args.queue)
    elif args.series:
        generate_series(queue=args.queue)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
