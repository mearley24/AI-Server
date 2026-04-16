"""
tools/seo_manager.py — SEO tools for Symphony Smart Homes
Keyword research, local SEO audit, backlink opportunities, meta tag generation.
Uses Ollama with OpenAI fallback.
"""

import os
import sys
import json
import argparse
import requests
from pathlib import Path

AI_SERVER_DIR = Path(__file__).parent.parent

OLLAMA_BOB_URL = "http://192.168.1.189:11434"
OLLAMA_MODEL = "llama3.2:3b"

SITE_URL = "https://symphonysh.com"


def load_env():
    dotenv_path = AI_SERVER_DIR / ".env"
    if dotenv_path.exists():
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def call_ollama(prompt, model=OLLAMA_MODEL, base_url=OLLAMA_BOB_URL):
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=45,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass
    return None


def call_openai(prompt, system=None):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=800,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


def call_llm(prompt, system=None):
    result = call_ollama(prompt)
    if result:
        return result
    return call_openai(prompt, system)


def cmd_keywords():
    """Generate keyword research report for Symphony Smart Homes."""
    prompt = (
        "Generate a keyword research report for Symphony Smart Homes, a residential AV and smart home integration "
        "company serving the Vail Valley / Eagle County, Colorado area. "
        "Include: 5 primary keywords, 10 long-tail keywords, 5 question-based keywords, and 5 local competitor terms. "
        "Format clearly with sections. Focus on buyer-intent keywords. Examples to build on:\n"
        "Primary: 'smart home Vail', 'home automation Eagle County', 'Control4 dealer Vail Valley'\n"
        "Long-tail: 'smart home pre-wire cost Vail', 'TV mounting Beaver Creek', 'outdoor audio Vail Valley'\n"
        "Output the full report with search intent notes for each keyword."
    )

    print("Keyword Research Report — Symphony Smart Homes")
    print("=" * 60)

    result = call_llm(prompt)
    if result:
        print(result)
    else:
        print("\nPrimary Keywords:")
        print("  1. smart home Vail (high intent, local)")
        print("  2. home automation Eagle County (high intent, local)")
        print("  3. Control4 dealer Vail Valley (transactional)")
        print("  4. AV integrator Vail (transactional)")
        print("  5. smart home installation Colorado mountain (informational)")

        print("\nLong-Tail Keywords:")
        print("  1. smart home pre-wire cost Vail Valley")
        print("  2. TV mounting Beaver Creek")
        print("  3. outdoor audio system Vail")
        print("  4. home theater setup Eagle County")
        print("  5. Lutron lighting control Vail")
        print("  6. Control4 programming Avon Colorado")
        print("  7. whole home audio Edwards CO")
        print("  8. security camera installation Vail")
        print("  9. home automation during new construction Colorado")
        print(" 10. smart home Arrowhead Village")

        print("\nQuestion Keywords:")
        print("  1. how much does a smart home cost in Vail")
        print("  2. what is pre-wire for smart home")
        print("  3. best home automation system for mountain home")
        print("  4. how to add outdoor speakers to deck Vail")
        print("  5. Control4 vs Savant which is better")


def cmd_local():
    """Local SEO audit — check site, meta tags, directory listings."""
    print("Local SEO Audit — Symphony Smart Homes")
    print("=" * 60)

    print(f"\n1. Site Health Check: {SITE_URL}")
    try:
        resp = requests.get(SITE_URL, timeout=10)
        print(f"   Status: {resp.status_code} {'OK' if resp.status_code == 200 else 'ERROR'}")
        print(f"   Response time: {resp.elapsed.total_seconds():.2f}s")

        html = resp.text.lower()

        title_start = html.find("<title>")
        title_end = html.find("</title>")
        if title_start != -1 and title_end != -1:
            title = resp.text[title_start + 7:title_end].strip()
            print(f"   Title tag: {title[:80]}")
        else:
            print("   Title tag: NOT FOUND")

        if 'name="description"' in html:
            desc_start = html.find('name="description"')
            content_start = html.find('content="', desc_start)
            if content_start != -1:
                content_end = html.find('"', content_start + 9)
                desc = resp.text[content_start + 9:content_end]
                print(f"   Meta description: {desc[:100]}")
        else:
            print("   Meta description: NOT FOUND — add one!")

        if "vail" in html or "eagle county" in html or "vail valley" in html:
            print("   Local keywords: FOUND in page content")
        else:
            print("   Local keywords: NOT FOUND — add 'Vail Valley' to homepage")

        if 'schema.org' in html or 'localBusiness' in html.lower():
            print("   Schema markup: FOUND")
        else:
            print("   Schema markup: NOT FOUND — add LocalBusiness schema")

    except Exception as e:
        print(f"   ERROR: Could not reach {SITE_URL} — {e}")

    print("\n2. Directory Listings Status:")
    directories = [
        ("Google Business Profile", "https://business.google.com", "CRITICAL — verify and keep updated"),
        ("Yelp", "https://biz.yelp.com", "Claim listing if not done"),
        ("Bing Places", "https://www.bingplaces.com", "Mirror Google listing"),
        ("HomeAdvisor / Angi", "https://pro.angi.com", "High local intent traffic"),
        ("Houzz", "https://www.houzz.com/for-professionals", "Key for luxury home market"),
        ("CEDIA Member Directory", "https://cedia.net/find-a-member", "Trust signal for AV"),
        ("BBB (Better Business Bureau)", "https://www.bbb.org", "Trust signal"),
        ("Nextdoor for Business", "https://nextdoor.com/business", "Hyper-local, Vail neighborhoods"),
    ]
    for name, url, note in directories:
        print(f"   - {name}: {note}")

    print("\n3. Recommendations:")
    print("   a. Add LocalBusiness + Service schema to homepage")
    print("   b. Create location pages: /vail, /beaver-creek, /avon, /edwards")
    print("   c. Add Google Business Profile posts weekly (use X content calendar)")
    print("   d. Build citations: NAP (Name, Address, Phone) consistent across all directories")
    print("   e. Get reviews on Google — target 20+ with 4.8+ rating")
    print("   f. Add FAQ schema with common smart home questions")


def cmd_backlinks():
    """Generate backlink opportunity list."""
    print("Backlink Opportunities — Symphony Smart Homes")
    print("=" * 60)

    categories = {
        "Local Business Directories": [
            "Vail Daily Business Directory (vaildaily.com)",
            "Eagle County Business Journal",
            "Vail Valley Partnership — member directory",
            "Town of Vail business listings",
            "Town of Avon business directory",
        ],
        "Industry Associations": [
            "CEDIA (cedia.net) — certified member listing",
            "Control4 Dealer Locator — register as certified dealer",
            "Snap One / SnapAV dealer directory",
            "Lutron Pro dealer locator",
            "Sonos Professional installer directory",
            "CompTIA member directory",
        ],
        "Builder & Contractor Partners": [
            "Slifer Smith & Frampton Real Estate — preferred vendors",
            "Vail Valley local home builders association",
            "Interior designers in Vail/Beaver Creek — referral partnerships",
            "Luxury home builders in Eagle County — co-marketing",
            "Renovation contractors — cross-referral agreements",
        ],
        "Local Media & Community": [
            "Vail Daily (vaildaily.com) — editorial features on smart home tech",
            "Colorado Public Radio — tech segment opportunities",
            "Vail Valley Magazine — luxury home features",
            "Elevation Outdoors — mountain lifestyle publication",
            "Denver Business Journal — Mountain region edition",
        ],
        "HOA & Community Resources": [
            "Vail homeowners associations — vendor referral lists",
            "Beaver Creek Resort HOA preferred vendors",
            "Arrowhead Village HOA",
            "Bachelor Gulch community resources",
        ],
        "Content & Guest Post Targets": [
            "Home automation forums (cepro.com, residentialsystems.com)",
            "Colorado home design blogs",
            "Mountain living lifestyle blogs",
            "CEDIA blog — submit case studies",
        ],
    }

    for category, links in categories.items():
        print(f"\n{category}:")
        for link in links:
            print(f"   - {link}")

    prompt = (
        "For a smart home AV integration company in Vail Valley, Colorado called Symphony Smart Homes, "
        "suggest 5 creative non-obvious backlink sources that most AV companies miss. "
        "Think local partnerships, niche directories, and content opportunities specific to luxury mountain towns."
    )

    result = call_llm(prompt)
    if result:
        print("\nAI-Suggested Additional Opportunities:")
        print(result)


def cmd_meta():
    """Generate optimized meta tags for key site pages."""
    pages = [
        {
            "page": "Homepage",
            "focus": "smart home integration company serving Vail Valley and Eagle County Colorado",
        },
        {
            "page": "Services",
            "focus": "AV integration services: home theater, distributed audio, lighting control, networking, Control4",
        },
        {
            "page": "Home Theater",
            "focus": "custom home theater design and installation in Vail Valley Colorado",
        },
        {
            "page": "Home Automation",
            "focus": "Control4 home automation installation and programming in Vail Valley",
        },
        {
            "page": "Networking",
            "focus": "home network design and installation for smart homes in Eagle County Colorado",
        },
        {
            "page": "Outdoor Audio",
            "focus": "outdoor audio and landscape speaker installation in Vail Valley Colorado",
        },
        {
            "page": "About",
            "focus": "Symphony Smart Homes — Vail Valley based AV and smart home integrator",
        },
        {
            "page": "Contact",
            "focus": "contact Symphony Smart Homes for smart home consultation in Vail Valley Colorado",
        },
    ]

    prompt_parts = []
    for p in pages:
        prompt_parts.append(f"Page: {p['page']} | Focus: {p['focus']}")

    prompt = (
        "Generate SEO-optimized meta tags for these pages for Symphony Smart Homes (symphonysh.com), "
        "a smart home AV integration company in Vail Valley / Eagle County, Colorado. "
        "For each page provide: title (50-60 chars), description (140-160 chars), and 5 keywords. "
        "Output as JSON array with fields: page, title, description, keywords.\n\n"
        + "\n".join(prompt_parts)
    )

    result = call_llm(prompt)

    if result:
        try:
            json_start = result.find("[")
            json_end = result.rfind("]") + 1
            if json_start != -1 and json_end > json_start:
                parsed = json.loads(result[json_start:json_end])
                print(json.dumps(parsed, indent=2))
                return
        except Exception:
            pass
        print(result)
    else:
        fallback = [
            {
                "page": "Homepage",
                "title": "Smart Home Installation Vail Valley | Symphony Smart Homes",
                "description": "Symphony Smart Homes designs and installs custom smart home systems in Vail Valley and Eagle County, CO. Control4, home theater, audio, lighting.",
                "keywords": ["smart home Vail", "home automation Eagle County", "Control4 dealer Vail", "AV integrator Vail Valley", "home theater Vail Colorado"],
            },
            {
                "page": "Home Theater",
                "title": "Custom Home Theater Design Vail Valley | Symphony Smart Homes",
                "description": "Professional home theater design and installation in Vail Valley, CO. 4K projection, surround sound, Control4 integration. Call for a free consultation.",
                "keywords": ["home theater Vail", "home theater Eagle County", "custom home theater Colorado", "4K projector installation Vail", "home cinema Beaver Creek"],
            },
            {
                "page": "Home Automation",
                "title": "Control4 Home Automation Vail Valley | Symphony Smart Homes",
                "description": "Certified Control4 dealer serving Vail Valley. Smart lighting, shading, audio, and climate control. One app, whole home.",
                "keywords": ["Control4 Vail Valley", "home automation Eagle County", "smart home control Vail", "Lutron lighting Vail", "smart home programming Colorado"],
            },
        ]
        print(json.dumps(fallback, indent=2))


def main():
    load_env()

    parser = argparse.ArgumentParser(description="SEO tools for Symphony Smart Homes")
    parser.add_argument("--keywords", action="store_true", help="Keyword research report")
    parser.add_argument("--local", action="store_true", help="Local SEO audit")
    parser.add_argument("--backlinks", action="store_true", help="Backlink opportunities")
    parser.add_argument("--meta", action="store_true", help="Generate meta tags")
    args = parser.parse_args()

    if args.keywords:
        cmd_keywords()
    elif args.local:
        cmd_local()
    elif args.backlinks:
        cmd_backlinks()
    elif args.meta:
        cmd_meta()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
