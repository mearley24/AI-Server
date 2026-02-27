#!/usr/bin/env python3
"""
client_onboarding.py
Symphony Smart Homes — Automated Client Onboarding Flow

Runs on Bob (Symphony HQ) to fully set up a new client's AI knowledge package.
Takes the D-Tools project export, generates a personalized knowledge base,
creates the custom system prompt, and produces a complete onboarding package
including a Getting Started guide for the client.

Usage:
    python client_onboarding.py --project project.json --client-id C0042
    python client_onboarding.py --project project.json --client-id C0042 --deploy 192.168.100.50
    python client_onboarding.py --list-clients

Output:
    /opt/symphony/concierge/onboarding/C0042/
      system_prompt.txt, knowledge_base.md, faq.md,
      getting_started.md, getting_started.html,
      onboarding_complete.json, Modelfile

Dependencies:
    pip install chromadb sentence-transformers jinja2
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("symphony.onboarding")

ONBOARDING_VERSION = "2.0.0"
DEFAULT_OUTPUT_DIR = Path("/opt/symphony/concierge/onboarding")
REGISTRY_PATH = Path(__file__).parent / "client_registry.json"
SYSTEM_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "client_system_prompt.md"

MODEL_BY_TIER = {
    "basic": "llama3.2:3b",
    "standard": "llama3.1:8b",
    "premium": "llama3.1:8b",
    "enterprise": "llama3.1:70b-q4_K_M",
}


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    return {"clients": [], "version": "1.0", "updated_at": None}


def save_registry(registry: dict):
    registry["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2, default=str)
    logger.info(f"Registry saved: {REGISTRY_PATH}")


def register_client(registry: dict, onboarding_record: dict):
    """Add or update a client record in the registry."""
    client_id = onboarding_record["client_id"]
    clients = registry.setdefault("clients", [])
    for i, c in enumerate(clients):
        if c["client_id"] == client_id:
            clients[i] = {**c, **onboarding_record}
            logger.info(f"Updated existing registry entry for {client_id}")
            return
    clients.append(onboarding_record)
    logger.info(f"Added new registry entry for {client_id}")


def generate_system_prompt(project: dict, knowledge_base: str) -> str:
    """Generate a fully personalized system prompt for this client."""
    ai_name = project.get("ai_name", "Aria")
    client_name = project.get("client_name", "your home")
    address = project.get("address", "")
    rooms = [r["name"] for r in project.get("rooms", [])]
    room_list = ", ".join(rooms) if rooms else "your home's rooms"
    tech = project.get("tech_contact", {})
    notes = project.get("notes", "")
    special = project.get("special_instructions", "")

    systems = project.get("systems", {})
    equipment_parts = []
    if systems.get("control4"):
        equipment_parts.append("Control4 automation system")
    if systems.get("lutron"):
        equipment_parts.append("Lutron lighting and motorized shades")
    if systems.get("audio"):
        sonos = systems["audio"].get("sonos", [])
        if sonos:
            equipment_parts.append(f"Sonos audio ({len(sonos)} zones)")
    if systems.get("video"):
        displays = systems["video"].get("displays", [])
        if displays:
            equipment_parts.append(f"{len(displays)} displays")
        if systems["video"].get("projector"):
            equipment_parts.append("home theater projector system")
    if systems.get("cameras"):
        cam_count = len(systems["cameras"].get("cameras", []))
        equipment_parts.append(f"{cam_count} security cameras + NVR")

    equipment_list = ", ".join(equipment_parts) if equipment_parts else "various smart home systems"

    if SYSTEM_PROMPT_TEMPLATE_PATH.exists():
        template = SYSTEM_PROMPT_TEMPLATE_PATH.read_text()
    else:
        template = _default_system_prompt_template()

    prompt = template
    prompt = prompt.replace("{ai_name}", ai_name)
    prompt = prompt.replace("{client_name}", client_name)
    prompt = prompt.replace("{home_address}", address)
    prompt = prompt.replace("{room_list}", room_list)
    prompt = prompt.replace("{equipment_list}", equipment_list)
    prompt = prompt.replace("{knowledge_base}", knowledge_base)

    if notes or special:
        prompt += "\n\n---\n\n## Client-Specific Notes\n\n"
        if notes:
            prompt += f"- {notes}\n"
        if special:
            prompt += f"- {special}\n"

    if tech:
        prompt += f"\n\n## Symphony Contact for This Client\n"
        prompt += f"- Tech: {tech.get('name', 'Symphony Support')}\n"
        prompt += f"- Phone: {tech.get('phone', '(480) 555-0100')}\n"
        prompt += f"- Email: {tech.get('email', 'support@symphonysmarthomes.com')}\n"

    logger.info(f"System prompt generated ({len(prompt)} chars)")
    return prompt


def _default_system_prompt_template() -> str:
    return """You are {ai_name}, a warm and knowledgeable smart home assistant for {client_name}, located at {home_address}.

You were created by Symphony Smart Homes.

## Rooms in This Home
{room_list}

## Installed Systems
{equipment_list}

## Your Role
- Help residents understand and operate their home systems
- Answer questions about devices, scenes, and automations
- Guide troubleshooting with step-by-step instructions
- Know your limits and escalate to Symphony when needed

## Communication Style
- Warm, patient, and conversational
- Plain English - no jargon without explanation
- Concise answers first; detail only if asked
- Honest about what you don't know

## Limits
- You cannot see live system status or control devices directly
- You don't know about changes made after your last knowledge update
- Safety issues (electrical, structural) -> always recommend professionals

{knowledge_base}
"""


def generate_equipment_knowledge_base(project: dict) -> str:
    """Generate a comprehensive markdown knowledge base from project data."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from client_knowledge_builder import generate_equipment_kb  # type: ignore
        return generate_equipment_kb(project)
    except ImportError:
        pass

    systems = project.get("systems", {})
    rooms = project.get("rooms", [])
    client_name = project.get("client_name", "Your Home")
    address = project.get("address", "")
    tech = project.get("tech_contact", {})
    now = datetime.now(timezone.utc).strftime("%B %Y")

    lines = [
        f"# {client_name} - Complete System Knowledge Base",
        f"*Generated by Symphony Smart Homes | {now}*",
        "",
        "---",
        "",
        "## Property",
        f"- **Address**: {address}",
        f"- **Installation Date**: {project.get('installation_date', 'N/A')}",
        "",
    ]

    if tech:
        lines += [
            "## Your Symphony Contact",
            f"- **Name**: {tech.get('name', 'Symphony Support')}",
            f"- **Phone**: {tech.get('phone', '(480) 555-0100')}",
            f"- **Email**: {tech.get('email', 'support@symphonysmarthomes.com')}",
            "",
        ]

    if rooms:
        lines += ["## Rooms", ""]
        for room in rooms:
            lines.append(f"- **{room['name']}** (Zone {room.get('zone_number', '?')}, Floor {room.get('floor', '?')})")
        lines.append("")

    for sys_name, sys_data in systems.items():
        lines.append(f"## {sys_name.replace('_', ' ').title()}")
        lines.append("```json")
        lines.append(json.dumps(sys_data, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def generate_faq(project: dict) -> str:
    """Generate a client-specific FAQ document."""
    ai_name = project.get("ai_name", "Aria")
    client_name = project.get("client_name", "your home")
    systems = project.get("systems", {})
    tech = project.get("tech_contact", {})
    tech_phone = tech.get("phone", "(480) 555-0100")
    tech_email = tech.get("email", "support@symphonysmarthomes.com")

    scenes = systems.get("control4", {}).get("scenes", [])

    lines = [
        f"# {client_name} - Frequently Asked Questions",
        f"*Answers personalized to your exact system by {ai_name}*",
        "",
        "---",
        "",
    ]

    c4 = systems.get("control4", {})
    if c4:
        lines += [
            "## Control4 Automation",
            "",
            "**How do I start the Control4 app?**",
            "Download 'Control4' from the App Store or Google Play. Log in with your household credentials.",
            "",
            "**What scenes are programmed in my home?**",
        ]
        for scene in scenes:
            lines.append(f"- **{scene['name']}**: {scene.get('description', 'Tap in the app to activate')}")
        lines += [
            "",
            "**My touch panel screen is dark - what do I do?**",
            "Tap the screen to wake it. If it doesn't wake, hold the power button for 5 seconds.",
            "",
        ]

    lutron = systems.get("lutron", {})
    if lutron:
        lines += [
            "## Lighting & Shades",
            "",
            "**How do I adjust light brightness?**",
            "Tap and hold the top of a keypad to raise brightness; hold the bottom to lower it.",
            "",
            "**My shades stopped moving.**",
            "Check that the shade motor has power (LED near motor). If LED is on but shades won't move, call Symphony.",
            "",
        ]

    audio = systems.get("audio", {})
    if audio:
        sonos_locs = [s.get("location", "") for s in audio.get("sonos", [])]
        lines += [
            "## Audio",
            "",
            "**How do I play music?**",
            "Open the Sonos app, select a room, and choose a source.",
            "",
            f"**What rooms have Sonos speakers?** {', '.join(sonos_locs) if sonos_locs else 'See your system diagram.'}",
            "",
        ]

    lines += [
        "## General",
        "",
        "**What if something stops working?**",
        f"Try {ai_name} first. For anything that needs a technician, call Symphony: {tech_phone} | {tech_email}",
        "",
        "**Does my smart home work when the internet is down?**",
        "Yes! All local control (Control4, Lutron, audio) works without internet.",
        "",
    ]

    result = "\n".join(lines)
    logger.info(f"FAQ generated ({len(result)} chars)")
    return result


def generate_getting_started_guide(project: dict) -> str:
    """Generate a personalized 'Getting Started with Your Smart Home' guide."""
    ai_name = project.get("ai_name", "Aria")
    client_name = project.get("client_name", "Your Home")
    salutation = project.get("client_salutation", "")
    address = project.get("address", "")
    systems = project.get("systems", {})
    tech = project.get("tech_contact", {})
    tech_phone = tech.get("phone", "(480) 555-0100")
    tech_email = tech.get("email", "support@symphonysmarthomes.com")
    tech_name = tech.get("name", "your Symphony technician")

    scenes = systems.get("control4", {}).get("scenes", [])
    rooms = [r["name"] for r in project.get("rooms", [])]

    aps = systems.get("networking", {}).get("access_points", [])
    ssids = list(dict.fromkeys(ap.get("ssid", "") for ap in aps if ap.get("ssid")))
    primary_ssid = ssids[0] if ssids else "your home WiFi"

    guide = f"""# Welcome to Your Smart Home
## {client_name}

{f"Dear {salutation}," if salutation else ""}

Your Symphony Smart Homes system is installed and ready.

---

## Meet {ai_name} - Your Personal Home AI

**{ai_name}** is your private AI assistant, installed in your AV rack.
Unlike Siri or Alexa, {ai_name} knows your exact system.

**To chat with {ai_name}:**
Open a web browser on any device connected to **{primary_ssid}** and go to:

> **http://concierge** or **http://symphony-concierge**
> *(Your tech will confirm the exact address)*

---

## Your Rooms
{chr(10).join('- ' + r for r in rooms) if rooms else "See your system documentation."}

---

## Your Scenes (Quick-Access Automations)

"""
    for scene in scenes:
        guide += f"**{scene['name']}**\n{scene.get('description', '')}\n\n"

    guide += f"""
---

## The Control4 App

1. Download **Control4** from the App Store or Google Play
2. Make sure you're on WiFi: **{primary_ssid}**
3. The app will find your home system automatically
4. Tap any room to control lights, shades, and AV

---

## Quick Troubleshooting

**Something's not responding?**
1. Ask {ai_name} first
2. Try power-cycling the device
3. If that doesn't work, call Symphony: **{tech_phone}**

---

## Your Symphony Support Contact

| Technician | {tech_name} |
|---|---|
| Phone | {tech_phone} |
| Email | {tech_email} |
| Hours | Mon-Fri, 8 AM-6 PM MST |
| Emergency | 24/7 via phone |

---

## Privacy Note

**{ai_name} is 100% private.**
Every conversation stays inside your home. Nothing is sent to the cloud.

---

*Symphony Smart Homes - {datetime.now().strftime("%B %Y")}*
*{address}*
"""
    logger.info(f"Getting Started guide generated ({len(guide)} chars)")
    return guide


def generate_modelfile(project: dict, system_prompt: str, subscription_tier: str = "standard") -> str:
    """Generate an Ollama Modelfile that bakes the system prompt into the model."""
    ai_name = project.get("ai_name", "Aria")
    client_name = project.get("client_name", "your home")
    client_id = project.get("client_id", "UNKNOWN")
    base_model = MODEL_BY_TIER.get(subscription_tier, MODEL_BY_TIER["standard"])
    escaped_prompt = system_prompt.replace('"""', '\\"\\"\\"')

    return f"""FROM {base_model}

# {ai_name} - Symphony Concierge AI for {client_name}
# Client ID: {client_id} | Tier: {subscription_tier} | Model: {base_model}
# Generated: {datetime.now(timezone.utc).isoformat()}

PARAMETER temperature 0.4
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 8192
PARAMETER num_predict 1024
PARAMETER stop "Human:"
PARAMETER stop "User:"

SYSTEM \"\"\"{escaped_prompt}
\"\"\"
"""


def run_onboarding(
    project: dict,
    output_dir: Path,
    subscription_tier: str = "standard",
    ingest_to_chroma: bool = True,
    chroma_path: Optional[str] = None,
) -> dict:
    """Execute the complete onboarding flow for a client."""
    client_id = project.get("client_id", "UNKNOWN")
    client_name = project.get("client_name", "Unknown Client")
    ai_name = project.get("ai_name", "Aria")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Starting onboarding: {client_name} ({client_id})")
    logger.info(f"Output directory: {output_dir}")

    steps_completed = []

    logger.info("[1/7] Generating equipment knowledge base...")
    kb = generate_equipment_knowledge_base(project)
    kb_path = output_dir / "knowledge_base.md"
    kb_path.write_text(kb, encoding="utf-8")
    steps_completed.append("knowledge_base")

    logger.info("[2/7] Generating personalized system prompt...")
    system_prompt = generate_system_prompt(project, kb)
    prompt_path = output_dir / "system_prompt.txt"
    prompt_path.write_text(system_prompt, encoding="utf-8")
    steps_completed.append("system_prompt")

    logger.info("[3/7] Generating client-specific FAQ...")
    faq = generate_faq(project)
    faq_path = output_dir / "faq.md"
    faq_path.write_text(faq, encoding="utf-8")
    steps_completed.append("faq")

    logger.info("[4/7] Generating Getting Started guide...")
    gs_md = generate_getting_started_guide(project)
    (output_dir / "getting_started.md").write_text(gs_md, encoding="utf-8")
    steps_completed.append("getting_started")

    logger.info("[5/7] Generating Ollama Modelfile...")
    modelfile = generate_modelfile(project, system_prompt, subscription_tier)
    modelfile_path = output_dir / "Modelfile"
    modelfile_path.write_text(modelfile, encoding="utf-8")
    steps_completed.append("modelfile")

    chroma_chunks = 0
    if ingest_to_chroma:
        logger.info("[6/7] Ingesting into ChromaDB vector store...")
        try:
            from knowledge_ingestion import (
                get_chroma_client, get_or_create_collection,
                LocalEmbeddingFunction, ingest_project,
                DEFAULT_CHROMA_PATH, DEFAULT_COLLECTION,
            )
            effective_chroma = chroma_path or DEFAULT_CHROMA_PATH
            embed_fn = LocalEmbeddingFunction()
            chroma_client = get_chroma_client(effective_chroma)
            collection = get_or_create_collection(chroma_client, DEFAULT_COLLECTION, embed_fn)
            chroma_chunks = ingest_project(project, collection, rebuild=True)
            steps_completed.append("chroma_ingest")
            logger.info(f"  ChromaDB: {chroma_chunks} chunks ingested")
        except ImportError:
            logger.warning("  knowledge_ingestion.py not found - skipping ChromaDB ingest")
        except Exception as e:
            logger.warning(f"  ChromaDB ingest failed: {e}")
    else:
        logger.info("[6/7] Skipping ChromaDB ingest")

    logger.info("[7/7] Writing onboarding record...")
    record = {
        "client_id": client_id,
        "client_name": client_name,
        "ai_name": ai_name,
        "address": project.get("address", ""),
        "subscription_tier": subscription_tier,
        "base_model": MODEL_BY_TIER.get(subscription_tier, "llama3.1:8b"),
        "onboarding_version": ONBOARDING_VERSION,
        "onboarded_at": datetime.now(timezone.utc).isoformat(),
        "steps_completed": steps_completed,
        "chroma_chunks": chroma_chunks,
        "output_dir": str(output_dir),
        "files_generated": [f.name for f in output_dir.iterdir() if f.is_file()],
        "rooms": [r["name"] for r in project.get("rooms", [])],
        "systems_installed": list(project.get("systems", {}).keys()),
        "scenes_count": len(project.get("systems", {}).get("control4", {}).get("scenes", [])),
        "subscription_status": "active",
        "knowledge_version": 1,
        "last_update": datetime.now(timezone.utc).isoformat(),
        "tailscale_ip": None,
        "appliance_ip": None,
        "tech_contact": project.get("tech_contact", {}),
        "installation_date": project.get("installation_date", ""),
        "notes": project.get("notes", ""),
    }

    record_path = output_dir / "onboarding_complete.json"
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info(f"Onboarding complete: {client_name} ({client_id})")

    return record


def print_client_list(registry: dict):
    """Print a formatted table of all onboarded clients."""
    clients = registry.get("clients", [])
    if not clients:
        print("No clients onboarded yet.")
        return
    print(f"\n{'='*80}")
    print(f"{'Client ID':<12} {'Name':<30} {'AI Name':<12} {'Tier':<12} {'Status':<10}")
    print(f"{'='*80}")
    for c in clients:
        print(
            f"{c.get('client_id', '?'):<12} "
            f"{c.get('client_name', '?')[:29]:<30} "
            f"{c.get('ai_name', '?'):<12} "
            f"{c.get('subscription_tier', '?'):<12} "
            f"{c.get('subscription_status', '?'):<10}"
        )
    print(f"{'='*80}")
    print(f"Total: {len(clients)} client(s)\n")


def main():
    parser = argparse.ArgumentParser(
        description="Symphony Concierge - Client Onboarding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", "-p", help="Path to D-Tools project JSON/XML")
    parser.add_argument("--client-id", help="Client ID (e.g. C0042)")
    parser.add_argument("--tier", choices=list(MODEL_BY_TIER.keys()), default="standard")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--no-chroma", action="store_true", help="Skip ChromaDB vector store ingestion")
    parser.add_argument("--chroma-path", help="Override ChromaDB data path")
    parser.add_argument("--update-registry", action="store_true", default=True)
    parser.add_argument("--list-clients", action="store_true", help="List all clients and exit")

    args = parser.parse_args()
    print(f"\nSymphony Concierge Onboarding v{ONBOARDING_VERSION}")

    registry = load_registry()

    if args.list_clients:
        print_client_list(registry)
        return

    if not args.project:
        parser.error("--project is required unless using --list-clients")
    if not args.client_id:
        parser.error("--client-id is required")

    p = Path(args.project)
    if not p.exists():
        print(f"Error: project file not found: {args.project}", file=sys.stderr)
        sys.exit(1)

    with open(p) as f:
        project = json.load(f)

    if "client_id" not in project:
        project["client_id"] = args.client_id

    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR / args.client_id

    record = run_onboarding(
        project=project,
        output_dir=output_dir,
        subscription_tier=args.tier,
        ingest_to_chroma=not args.no_chroma,
        chroma_path=args.chroma_path,
    )

    if args.update_registry:
        register_client(registry, record)
        save_registry(registry)

    print(f"\nOnboarding files written to: {output_dir}/")
    print("\nNext steps:")
    print(f"  1. Review generated files in {output_dir}/")
    print(f"  2. Install model: ollama create concierge-{args.client_id.lower()} -f {output_dir}/Modelfile")
    print(f"  3. Start the concierge server: python concierge_server.py")


if __name__ == "__main__":
    main()
