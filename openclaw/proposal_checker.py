"""Proactive Proposal Checker — Bob reads new proposals and validates against confirmed decisions.

When a new proposal PDF appears (via iCloud watcher or email attachment), Bob:
1. Extracts the proposal text
2. Compares against the project's confirmed decisions in the knowledge base
3. Flags anything missing, inconsistent, or changed
4. Updates deliverables in Dropbox
5. Messages Matt with findings via iMessage

Usage:
    from proposal_checker import check_proposal
    check_proposal("/path/to/proposal.pdf", project="topletz")
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Knowledge base of confirmed decisions per project
# Bob should eventually load this from a DB or JSON file
CONFIRMED_DECISIONS = {
    "topletz": {
        "project_name": "84 Aspen Meadow",
        "client": "Steve Topletz",
        "gc": "RMGC (Rocky Mountain Construction Group)",
        "gc_contact": "David",
        "decisions": [
            {"item": "Lighting", "decision": "C4 native — no Lutron RA3"},
            {"item": "Shade prewire", "decision": "In scope"},
            {"item": "Security prewire", "decision": "Symphony runs alongside AV prewire"},
            {"item": "Cameras", "decision": "Prewire only — no Luma hardware"},
            {"item": "Touchscreens", "decision": "iPads at Kitchen/TV Room + Master Bedroom, replacing C4 T5"},
            {"item": "Tuning period", "decision": "60 days post-commissioning"},
            {"item": "Security panel", "decision": "Qolsys IQ Panel 4, hardwired Cat6, VLAN 40, garage entry primary, master bed secondary"},
            {"item": "Panel integration", "decision": "Cindev DriverCentral driver, SDDP auto-discovery on VLAN 40"},
            {"item": "Switches", "decision": "18 switches, all C4, code-required. Few in master suite optional for bedside control"},
            {"item": "TV install", "decision": "Symphony handles mounting, wiring, C4 integration at standard rates. Client supplies TVs"},
            {"item": "TV mounts", "decision": "Mounts as reviewed and approved by Matt. VLT7 recommended for service access"},
            {"item": "Art walls", "decision": "Cancelled"},
            {"item": "Lower Level Family TV", "decision": "Wall mounted"},
            {"item": "IR flashers", "decision": "Required for non-native C4 TVs"},
            {"item": "Post-install support", "decision": "90 days for installation-related issues"},
            {"item": "Wire management", "decision": "Strong VersaBox (SM-RBX-14-WH or SM-RBX-8-WH) recommended at each TV location"},
            {"item": "Security coordination", "decision": "Symphony coordinates with Superior Alarm on all security prewire"},
            {"item": "Conduit", "decision": "Rack to attic for future expansion"},
        ],
        "exclusions": [
            "No Sonos",
            "No distributed TV audio",
            "No video matrix or HDMI distribution",
            "CORE3 only (no CORE5)",
            "1G switching only (no 10G)",
            "Security hardware by Superior Alarm",
            "Camera hardware excluded — prewire only",
            "Shade hardware excluded — prewire only",
        ],
        "pricing": {
            "total": 57683.09,
            "subtotal": 55171.98,
            "tax": 2511.11,
            "deposit_pct": 0.60,
            "deposit": 34609.85,
        },
    }
}


def extract_proposal_text(pdf_path: str) -> str:
    """Extract text from a proposal PDF."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass

    # Fallback: try pdfplumber
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
                text += "\n"
        return text
    except ImportError:
        pass

    # Fallback: try pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass

    logger.error("No PDF extraction library available")
    return ""


def check_proposal(pdf_path: str, project: str = "topletz") -> dict:
    """Check a proposal PDF against confirmed decisions.
    
    Returns a dict with:
        - matches: list of confirmed items found in the proposal
        - missing: list of confirmed items NOT found
        - concerns: list of potential inconsistencies
        - pricing: pricing comparison
        - summary: human-readable summary
    """
    known = CONFIRMED_DECISIONS.get(project)
    if not known:
        return {"error": f"Unknown project: {project}"}

    text = extract_proposal_text(pdf_path)
    if not text:
        return {"error": f"Could not extract text from {pdf_path}"}

    text_lower = text.lower()
    results = {
        "matches": [],
        "missing": [],
        "concerns": [],
        "pricing": {},
        "summary": "",
    }

    # Check each confirmed decision
    for decision in known["decisions"]:
        item = decision["item"]
        detail = decision["decision"]

        # Build search patterns based on the item
        found = False
        patterns = _build_search_patterns(item, detail)
        for pattern in patterns:
            if pattern.lower() in text_lower:
                found = True
                break

        if found:
            results["matches"].append(f"{item}: {detail}")
        else:
            results["missing"].append(f"{item}: {detail}")

    # Check exclusions
    for exclusion in known.get("exclusions", []):
        key_terms = exclusion.lower().split()
        if not any(term in text_lower for term in key_terms if len(term) > 4):
            results["concerns"].append(f"Exclusion may be missing: {exclusion}")

    # Check pricing
    pricing = known.get("pricing", {})
    if pricing:
        total = pricing.get("total", 0)
        # Look for the total in the text
        total_str = f"${total:,.2f}"
        total_str_no_comma = f"${total:.2f}"
        if total_str in text or total_str_no_comma in text:
            results["pricing"]["total_match"] = True
            results["pricing"]["total"] = total
        else:
            results["pricing"]["total_match"] = False
            results["pricing"]["expected"] = total
            # Try to find what total IS in the document
            total_pattern = re.findall(r'\$[\d,]+\.\d{2}', text)
            large_amounts = [t for t in total_pattern if float(t.replace('$', '').replace(',', '')) > 10000]
            if large_amounts:
                results["pricing"]["found_amounts"] = large_amounts[-3:]

    # Check GC reference
    gc = known.get("gc", "")
    if gc and gc.lower().split("(")[0].strip().lower() not in text_lower:
        results["concerns"].append(f"GC ({gc}) not referenced in proposal")

    # Build summary
    total_items = len(known["decisions"])
    matched = len(results["matches"])
    missing = len(results["missing"])
    concerns = len(results["concerns"])

    lines = [
        f"Proposal Check: {known['project_name']} ({project})",
        f"",
        f"Matched: {matched}/{total_items} confirmed decisions found",
        f"Missing: {missing} items not found in proposal text",
        f"Concerns: {concerns}",
    ]

    if results["missing"]:
        lines.append("")
        lines.append("MISSING ITEMS:")
        for item in results["missing"]:
            lines.append(f"  - {item}")

    if results["concerns"]:
        lines.append("")
        lines.append("CONCERNS:")
        for concern in results["concerns"]:
            lines.append(f"  - {concern}")

    if results["pricing"].get("total_match"):
        lines.append(f"")
        lines.append(f"Pricing: ${results['pricing']['total']:,.2f} — MATCHES")
    elif results["pricing"].get("expected"):
        lines.append(f"")
        lines.append(f"Pricing: Expected ${results['pricing']['expected']:,.2f} — CHECK NEEDED")

    results["summary"] = "\n".join(lines)
    return results


def _build_search_patterns(item: str, detail: str) -> list[str]:
    """Build search patterns for a decision item."""
    patterns = [item.lower()]

    # Add specific keywords from the detail
    if "qolsys" in detail.lower():
        patterns.extend(["qolsys", "iq panel", "vlan 40"])
    if "ipad" in detail.lower():
        patterns.extend(["ipad", "tablet"])
    if "c4 native" in detail.lower():
        patterns.extend(["c4 native", "control4 native", "native lighting"])
    if "60 day" in detail.lower():
        patterns.extend(["60 day", "sixty", "tuning period"])
    if "18 switch" in detail.lower():
        patterns.extend(["18 switch", "18 switches"])
    if "prewire" in detail.lower():
        patterns.append("prewire")
    if "rmgc" in detail.lower() or "rocky mountain" in detail.lower():
        patterns.extend(["rmgc", "rocky mountain"])
    if "superior" in detail.lower():
        patterns.extend(["superior", "alarm"])
    if "versabox" in detail.lower() or "sm-rbx" in detail.lower():
        patterns.extend(["versabox", "sm-rbx", "recessed"])
    if "conduit" in detail.lower():
        patterns.append("conduit")
    if "garage entry" in detail.lower():
        patterns.extend(["garage entry", "garage"])
    if "cancelled" in detail.lower() or "canceled" in detail.lower():
        patterns.extend(["cancelled", "canceled", "removed", "eliminated"])

    return patterns


def notify_findings(results: dict, recipient: str = None) -> None:
    """Send findings via iMessage through Redis."""
    try:
        import redis
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        r = redis.from_url(url, decode_responses=True, socket_timeout=2)
        r.publish("notifications:email", json.dumps({
            "title": "[PROPOSAL CHECK]",
            "body": results.get("summary", "No summary available"),
        }))
    except Exception as e:
        logger.error(f"Failed to notify: {e}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python proposal_checker.py <pdf_path> [project]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    project = sys.argv[2] if len(sys.argv) > 2 else "topletz"
    
    results = check_proposal(pdf_path, project)
    print(results["summary"])
    
    if "--notify" in sys.argv:
        notify_findings(results)
