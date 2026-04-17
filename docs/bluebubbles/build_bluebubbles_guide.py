#!/usr/bin/env python3
"""
BlueBubbles -- Secure Local-First Setup Guide
Self-contained PDF builder using ReportLab Platypus.
Run: python build_bluebubbles_guide.py
"""

import os
import re
import sys
import logging
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent
PDF_OUT = WORKSPACE / "BlueBubbles_Secure_Setup_Guide.pdf"
FONT_DIR = Path("/tmp/fonts_bb")
FONT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Palette (Nexus light)
# ---------------------------------------------------------------------------
BG         = "#F7F6F2"
SURFACE    = "#F9F8F5"
SURFACE_ALT= "#FBFBF9"
BORDER     = "#D4D1CA"
TEXT       = "#28251D"
MUTED      = "#7A7974"
FAINT      = "#BAB9B4"
PRIMARY    = "#01696F"
WARNING    = "#964219"
ERROR      = "#A12C7B"
SUCCESS    = "#437A22"

# ---------------------------------------------------------------------------
# Font download
# ---------------------------------------------------------------------------
OLD_UA = "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; SV1)"

FONT_CSS_URLS = {
    "Inter-Regular":        "https://fonts.googleapis.com/css2?family=Inter:wght@400&display=swap",
    "DMSans-Bold":          "https://fonts.googleapis.com/css2?family=DM+Sans:wght@700&display=swap",
    "JetBrainsMono-Regular":"https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400&display=swap",
    "JetBrainsMono-Bold":   "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@700&display=swap",
}

FONTS_REGISTERED = set()


def _fetch_ttf_url(css_url):
    """Fetch Google Fonts CSS with old UA and extract TTF URL."""
    req = urllib.request.Request(css_url, headers={"User-Agent": OLD_UA})
    css = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="replace")
    m = re.search(r"url\(([^)]+\.ttf)\)", css)
    if m:
        return m.group(1).strip("'\"")
    return None


def _download_font(name, css_url):
    ttf_path = FONT_DIR / f"{name}.ttf"
    if ttf_path.exists():
        return ttf_path
    try:
        ttf_url = _fetch_ttf_url(css_url)
        if not ttf_url:
            log.warning("No TTF URL found for %s; will use Helvetica fallback.", name)
            return None
        log.info("Downloading %s ...", name)
        urllib.request.urlretrieve(ttf_url, str(ttf_path))
        return ttf_path
    except Exception as exc:
        log.warning("Font download failed for %s: %s; using Helvetica fallback.", name, exc)
        return None


def _setup_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for name, url in FONT_CSS_URLS.items():
        path = _download_font(name, url)
        if path:
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                FONTS_REGISTERED.add(name)
                log.info("Registered font %s", name)
            except Exception as exc:
                log.warning("Failed to register %s: %s", name, exc)
        if name not in FONTS_REGISTERED:
            log.warning("Font %s not available; using built-in fallback.", name)


def F(preferred, fallback="Helvetica"):
    return preferred if preferred in FONTS_REGISTERED else fallback


def F_bold(preferred, fallback="Helvetica-Bold"):
    return preferred if preferred in FONTS_REGISTERED else fallback


def F_mono(preferred, fallback="Courier"):
    return preferred if preferred in FONTS_REGISTERED else fallback


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _build_styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor

    body_font  = F("Inter-Regular")
    head_font  = F_bold("DMSans-Bold", "Helvetica-Bold")
    mono_font  = F_mono("JetBrainsMono-Regular", "Courier")

    S = {}

    S["body"] = ParagraphStyle(
        "body",
        fontName=body_font,
        fontSize=10,
        leading=14,
        textColor=HexColor(TEXT),
        spaceAfter=6,
    )
    S["body_small"] = ParagraphStyle(
        "body_small",
        parent=S["body"],
        fontSize=9,
        leading=13,
    )
    S["h1"] = ParagraphStyle(
        "h1",
        fontName=head_font,
        fontSize=20,
        leading=26,
        textColor=HexColor(TEXT),
        spaceBefore=18,
        spaceAfter=10,
    )
    S["h2"] = ParagraphStyle(
        "h2",
        fontName=head_font,
        fontSize=14,
        leading=20,
        textColor=HexColor(PRIMARY),
        spaceBefore=14,
        spaceAfter=6,
    )
    S["h3"] = ParagraphStyle(
        "h3",
        fontName=head_font,
        fontSize=11,
        leading=16,
        textColor=HexColor(TEXT),
        spaceBefore=10,
        spaceAfter=4,
    )
    S["code"] = ParagraphStyle(
        "code",
        fontName=mono_font,
        fontSize=8.5,
        leading=13,
        textColor=HexColor(TEXT),
        backColor=HexColor(SURFACE_ALT),
        leftIndent=8,
        rightIndent=8,
        spaceBefore=4,
        spaceAfter=4,
        borderPadding=(4, 6, 4, 6),
    )
    S["code_bold"] = ParagraphStyle(
        "code_bold",
        parent=S["code"],
        fontName=F_mono("JetBrainsMono-Bold", "Courier-Bold"),
    )
    S["bullet"] = ParagraphStyle(
        "bullet",
        parent=S["body"],
        leftIndent=16,
        bulletIndent=6,
        spaceBefore=2,
        spaceAfter=2,
    )
    S["check"] = ParagraphStyle(
        "check",
        parent=S["body"],
        leftIndent=20,
        spaceBefore=3,
        spaceAfter=3,
    )
    S["cover_title"] = ParagraphStyle(
        "cover_title",
        fontName=head_font,
        fontSize=26,
        leading=32,
        textColor=HexColor(PRIMARY),
        spaceAfter=8,
    )
    S["cover_sub"] = ParagraphStyle(
        "cover_sub",
        fontName=body_font,
        fontSize=12,
        leading=18,
        textColor=HexColor(MUTED),
        spaceAfter=20,
    )
    S["toc_entry"] = ParagraphStyle(
        "toc_entry",
        parent=S["body"],
        fontSize=10,
        leading=16,
        leftIndent=0,
    )
    S["caption"] = ParagraphStyle(
        "caption",
        fontName=body_font,
        fontSize=8,
        leading=12,
        textColor=HexColor(MUTED),
        spaceAfter=6,
    )
    S["footnote"] = ParagraphStyle(
        "footnote",
        fontName=body_font,
        fontSize=8,
        leading=12,
        textColor=HexColor(MUTED),
        leftIndent=12,
        spaceAfter=2,
    )
    return S


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------
def hr(width_frac=1.0):
    from reportlab.platypus import HRFlowable
    from reportlab.lib.colors import HexColor
    return HRFlowable(width=f"{int(width_frac*100)}%", thickness=0.5, color=HexColor(BORDER), spaceAfter=6, spaceBefore=6)


def sp(h=6):
    from reportlab.platypus import Spacer
    return Spacer(1, h)


def P(text, style):
    from reportlab.platypus import Paragraph
    return Paragraph(text, style)


def check_item(text, S):
    """Render a checklist item using [ ] in DMSans-Bold."""
    bold_name = F_bold("DMSans-Bold", "Helvetica-Bold")
    box = f'<font name="{bold_name}" color="{PRIMARY}">[ ]</font>'
    return P(f"{box}&nbsp;&nbsp;{text}", S["check"])


def code_block(lines, S):
    """Render a code block (list of strings) as Paragraphs."""
    from reportlab.platypus import KeepTogether
    items = []
    for line in lines:
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        items.append(P(safe, S["code"]))
    return KeepTogether(items)


def link(url, label=None):
    display = label or url
    return f'<a href="{url}" color="{PRIMARY}">{display}</a>'


def fn(n):
    """Footnote superscript marker."""
    return f"<super>{n}</super>"


def section_header(title, S):
    from reportlab.platypus import KeepTogether
    return KeepTogether([hr(), P(title, S["h2"]), sp(2)])


def build_table(headers, rows, col_widths, S):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib.colors import HexColor, white
    bold_name = F_bold("DMSans-Bold", "Helvetica-Bold")
    header_row = [P(f'<font name="{bold_name}">{h}</font>', S["body_small"]) for h in headers]
    data = [header_row] + [[P(str(cell), S["body_small"]) for cell in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  HexColor(PRIMARY)),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  white),
        ("FONTNAME",    (0, 0), (-1, 0),  bold_name),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor(SURFACE), HexColor(SURFACE_ALT)]),
        ("GRID",        (0, 0), (-1, -1), 0.4, HexColor(BORDER)),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
    ]))
    return t


# ---------------------------------------------------------------------------
# Content sections
# ---------------------------------------------------------------------------
def section_cover(S, inch):
    from reportlab.platypus import Table, TableStyle, PageBreak
    from reportlab.lib.colors import HexColor, white
    bold_name = F_bold("DMSans-Bold", "Helvetica-Bold")

    items = []
    items.append(sp(40))
    items.append(P("BlueBubbles", S["cover_title"]))
    items.append(P("Secure Local-First Setup Guide", S["h1"]))
    items.append(P(
        "Self-host your iMessage relay with Tailscale VPN -- "
        "no port-forwarding required", S["cover_sub"]
    ))
    items.append(hr())
    items.append(sp(12))

    # 3-column scope / audience / outcome card
    card_style = ParagraphStyleRef(S, bold_name)
    card_data = [[
        [P(f'<font name="{bold_name}" color="{PRIMARY}">Scope</font>', S["body"]),
         P("macOS BlueBubbles server with Tailscale VPN, Private API, "
           "Docker-OSX option, and mobile/desktop client hardening.", S["body_small"])],
        [P(f'<font name="{bold_name}" color="{PRIMARY}">Audience</font>', S["body"]),
         P("Self-hosters who want iMessage on Android/Windows without "
           "cloud relay services or router port-forwarding.", S["body_small"])],
        [P(f'<font name="{bold_name}" color="{PRIMARY}">Outcome</font>', S["body"]),
         P("A verified, TLS-secured BlueBubbles installation reachable "
           "only through your Tailscale network.", S["body_small"])],
    ]]
    ct = Table(card_data, colWidths=[2.1*inch, 2.1*inch, 2.1*inch])
    ct.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HexColor(SURFACE)),
        ("BOX",           (0, 0), (-1, -1), 0.5, HexColor(PRIMARY)),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, HexColor(BORDER)),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    items.append(ct)
    items.append(sp(20))

    # Contents list
    items.append(P(f'<font name="{bold_name}">Contents</font>', S["h3"]))
    toc = [
        "1.  Threat Model &amp; Design Goals",
        "2.  Prerequisites &amp; macOS Permissions",
        "3.  Install the BlueBubbles Server",
        "4.  Tailscale VPN Setup",
        "5.  Tailscale Funnel (Optional Public TLS)",
        "6.  Private API &amp; the SIP Trade-Off",
        "7.  Docker-OSX Self-Hosting Option",
        "8.  Android Client Checklist",
        "9.  Windows Client Checklist",
        "10. Operational Hygiene &amp; Hardening",
        "Appendix A -- Commands Reference",
        "Appendix B -- Troubleshooting Matrix",
        "Sources",
    ]
    for entry in toc:
        items.append(P(entry, S["toc_entry"]))

    items.append(PageBreak())
    return items


def ParagraphStyleRef(S, bold_name):
    """Dummy helper to satisfy reference in cover section."""
    return S


def section_threat_model(S, inch):
    from reportlab.platypus import PageBreak
    items = []
    items.append(section_header("1.  Threat Model &amp; Design Goals", S))
    items.append(P(
        "BlueBubbles relays iMessage traffic from a macOS host to any client device. "
        "The default cloud-relay mode routes messages through a Firebase server you do "
        "not control. This guide replaces that relay with a "
        "<b>local-first Tailscale tunnel</b>: your messages never leave hardware you own.",
        S["body"]
    ))
    items.append(sp(4))
    items.append(P(f'<font name="{F_bold("DMSans-Bold","Helvetica-Bold")}" color="{PRIMARY}">Threats addressed</font>', S["h3"]))

    rows = [
        ("Cloud relay interception", "Firebase-free mode: no third-party relay"),
        ("Router exploit via open port", "Tailscale WireGuard tunnel: zero open ports"),
        ("Plaintext LAN traffic", "tailscale serve provides automatic TLS"),
        ("Unauthorized device access", "Tailscale ACLs limit who can reach port 1234"),
        ("Credential leakage", "API passphrase + device-locked Tailscale keys"),
    ]
    t = build_table(["Threat", "Mitigation"], rows, [2.5*inch, 3.8*inch], S)
    items.append(t)
    items.append(sp(6))
    items.append(P(
        "<b>Design goals:</b> (1) zero open router ports, (2) TLS everywhere, "
        "(3) messages stay on-device, (4) Private API opt-in with informed consent.",
        S["body"]
    ))
    items.append(sp(6))
    items.append(P(
        "<b>Why not a VPS relay?</b> Cloud VPS relays introduce a third party that "
        "can read your metadata, are subject to subpoenas, and add latency. "
        "Tailscale's control plane only stores your public keys; the WireGuard tunnel "
        "is end-to-end encrypted between your own devices. Even Tailscale's staff "
        "cannot read your message traffic.",
        S["body"]
    ))
    items.append(P(
        "<b>Firebase-free push notifications:</b> Standard BlueBubbles uses Firebase "
        "Cloud Messaging (FCM) for push delivery. FCM is a Google server; if you want "
        "zero third-party servers, use the Tailscale LAN-only mode in Section 4 "
        "and accept that push delivery requires an active Tailscale connection.",
        S["body"]
    ))
    items.append(PageBreak())
    return items


def section_prerequisites(S, inch):
    items = []
    items.append(section_header("2.  Prerequisites &amp; macOS Permissions", S))
    items.append(P(
        f"Before installing BlueBubbles, grant the following macOS permissions. "
        f"Missing any of these causes silent failures -- the server will appear to run "
        f"but features will not work.{fn(2)}",
        S["body"]
    ))
    items.append(sp(4))

    rows = [
        ("Full Disk Access",
         "Required for reading iMessage databases (chat.db)",
         "System Settings > Privacy &amp; Security > Full Disk Access"),
        ("Contacts",
         "Required for contact name resolution",
         "System Settings > Privacy &amp; Security > Contacts"),
        ("Accessibility",
         "Required for sending messages via UI scripting",
         "System Settings > Privacy &amp; Security > Accessibility"),
        ("Notifications",
         "Optional: allows BlueBubbles to show system alerts",
         "System Settings > Notifications"),
        ("Screen Recording",
         "Optional: needed for link preview generation",
         "System Settings > Privacy &amp; Security > Screen Recording"),
    ]
    t = build_table(
        ["Permission", "Required For", "Where to Grant"],
        rows,
        [1.5*inch, 2.1*inch, 2.7*inch],
        S
    )
    items.append(t)
    items.append(sp(6))
    items.append(P(
        f"<b>Contacts fix</b>{fn(3)}: If BlueBubbles cannot read Contacts after granting "
        "access, remove the app from the list and re-add it, then restart the server.",
        S["body"]
    ))
    items.append(P(
        f"<b>Accessibility issue</b>{fn(4)}: On macOS 14+ granting Accessibility in "
        "a non-admin account requires entering an admin password in the prompt. "
        "If the toggle remains greyed-out, lock and unlock the preference pane with "
        "the padlock icon.",
        S["body"]
    ))
    items.append(sp(6))
    items.append(P(
        "<b>System versions:</b> This guide covers macOS 12 Monterey through macOS 15 "
        "Sequoia. On macOS 14 Sonoma and later, the Privacy &amp; Security pane was "
        "redesigned. Permission entries that appear missing are often found by scrolling "
        "down in the right-hand panel of that pane.",
        S["body"]
    ))
    return items


def section_install_server(S, inch):
    from reportlab.platypus import PageBreak
    items = []
    items.append(section_header("3.  Install the BlueBubbles Server", S))
    items.append(P(
        f"Download the latest release from "
        f"{link('https://bluebubbles.app/install/', 'bluebubbles.app/install')}{fn(5)}. "
        "Drag BlueBubbles.app to /Applications, launch it, and follow the setup wizard.",
        S["body"]
    ))
    items.append(sp(4))
    items.append(P("<b>Manual Setup steps</b>", S["h3"]))
    steps = [
        f"1.  Open BlueBubbles Server and choose <b>Manual Setup</b>.{fn(2)}",
        "2.  When prompted for server URL, enter your Tailscale IP (e.g. 100.x.x.x:1234) "
            "or leave blank -- you will configure it in Section 4.",
        "3.  Set a strong <b>API passphrase</b>. This is the only secret protecting remote access.",
        "4.  Under <b>Connection > Socket &amp; REST API</b>, set port to <b>1234</b>.",
        "5.  Enable <b>Keep app running in background</b> and <b>Start on Login</b>.",
        "6.  Grant all required permissions listed in Section 2 before clicking Finish.",
    ]
    for step in steps:
        items.append(P(step, S["bullet"]))
    items.append(sp(6))
    items.append(P("<b>Firebase (optional)</b>", S["h3"]))
    items.append(P(
        "Firebase push notifications are optional when using Tailscale. "
        "Skip Firebase setup entirely if you do not need push delivery while your "
        "device is off the Tailscale network. "
        f"See the simplified setup blog{fn(11)} for the Firebase-free workflow.",
        S["body"]
    ))
    items.append(sp(6))
    items.append(P("<b>Verifying the server is running</b>", S["h3"]))
    items.append(P(
        "After setup, confirm BlueBubbles is listening on the expected port:",
        S["body"]
    ))
    items.append(code_block([
        "# Check that BlueBubbles is listening on port 1234",
        "lsof -nP -iTCP:1234 -sTCP:LISTEN",
        "",
        "# Quick local ping via REST API",
        "curl -s http://localhost:1234/api/v1/ping",
        "# Expected response: {\"status\":\"OK\",\"message\":\"pong\"}",
    ], S))
    items.append(PageBreak())
    return items


def section_tailscale(S, inch):
    items = []
    items.append(section_header("4.  Tailscale VPN Setup", S))
    items.append(P(
        f"Tailscale creates an encrypted WireGuard mesh between your devices with no "
        f"open router ports. Install Tailscale on the Mac running BlueBubbles and on "
        f"every client device.{fn(6)} Both options below assume BlueBubbles listens on "
        f"port <b>1234</b>.",
        S["body"]
    ))
    items.append(sp(6))

    # Option A
    items.append(P("<b>Option A -- LAN-only HTTP (simplest)</b>", S["h3"]))
    items.append(P(
        "Use the Tailscale IPv4 address directly. No certificate required. "
        "Your client URL will be: <b>http://100.x.x.x:1234</b>",
        S["body"]
    ))
    items.append(code_block([
        "# Verify your Tailscale IP on the Mac",
        "tailscale ip -4",
        "",
        "# In BlueBubbles Server > Connection, set:",
        "#   Local Address: 0.0.0.0",
        "#   Port: 1234",
        "#   Server URL: http://<your-tailscale-ip>:1234",
    ], S))
    items.append(sp(8))

    # Option B
    items.append(P("<b>Option B -- tailscale serve (TLS, recommended)</b>", S["h3"]))
    items.append(P(
        "tailscale serve terminates TLS using a Let's Encrypt certificate issued "
        "for your <b>.ts.net</b> hostname, so your client sees a valid HTTPS URL "
        "with no certificate warnings.",
        S["body"]
    ))
    items.append(code_block([
        "# Enable HTTPS termination on port 443 -> local port 1234",
        "tailscale serve --bg --https=443 1234",
        "",
        "# Verify the serve config",
        "tailscale serve status",
        "",
        "# Your BlueBubbles Server URL becomes:",
        "#   https://<hostname>.ts.net",
        "#   (shown in tailscale serve status output)",
    ], S))
    items.append(P(
        f"Set the <b>Server URL</b> in BlueBubbles to the https://<hostname>.ts.net address "
        f"shown by <code>tailscale serve status</code>. See the Tailscale blog{fn(1)} for "
        f"a step-by-step walkthrough with screenshots.",
        S["body"]
    ))
    return items


def section_funnel(S, inch):
    from reportlab.platypus import PageBreak
    items = []
    items.append(section_header("5.  Tailscale Funnel (Optional Public TLS)", S))
    items.append(P(
        "Tailscale Funnel exposes your BlueBubbles server to the public internet over "
        "HTTPS, still without opening any router ports. Use this only if you need "
        "push notifications from a carrier network where Tailscale is unavailable "
        "(e.g., some corporate Wi-Fi or cellular restrictions).",
        S["body"]
    ))
    items.append(code_block([
        "# Enable public HTTPS Funnel on port 443 -> local port 1234",
        "tailscale funnel --bg --https=443 1234",
        "",
        "# Check status",
        "tailscale funnel status",
        "",
        "# To disable Funnel later:",
        "tailscale funnel off",
    ], S))
    items.append(P(
        "<b>Security note:</b> Funnel makes your server reachable from anywhere on the "
        "internet. Ensure your BlueBubbles API passphrase is strong (16+ random characters) "
        "before enabling Funnel. Prefer Option B in Section 4 unless Funnel is necessary.",
        S["body"]
    ))
    items.append(PageBreak())
    return items


def section_private_api(S, inch):
    items = []
    items.append(section_header("6.  Private API &amp; the SIP Trade-Off", S))
    items.append(P(
        f"The BlueBubbles Private API{fn(7)} unlocks features Apple does not expose to "
        "third-party apps: typing indicators, tapbacks/reactions, read receipts, "
        "and message editing. Enabling it requires disabling System Integrity Protection (SIP) "
        "on the server Mac -- a significant security decision.",
        S["body"]
    ))
    items.append(sp(4))

    # Risks, Benefits, Mitigations
    rows = [
        ("Risks",
         "SIP removal reduces kernel-level attack surface. A malicious process can more "
         "easily modify system files. Warranty/support implications on some hardware."),
        ("Benefits",
         "Typing indicators, reactions, read receipts, message unsend/edit, "
         "high-quality media forwarding."),
        ("Mitigations",
         "Dedicated server Mac (not primary workstation). Disable SIP only on the server. "
         "Keep macOS and BlueBubbles updated. Restrict physical access."),
    ]
    t = build_table(["Factor", "Detail"], rows, [1.3*inch, 5.0*inch], S)
    items.append(t)
    items.append(sp(8))

    items.append(P("<b>Decision Rule</b>", S["h3"]))
    items.append(P(
        "<b>Enable the Private API if:</b> you frequently exchange reactions, rely on "
        "read receipts, or need typing indicators, AND the server Mac is dedicated to "
        "this role (not your daily driver).",
        S["body"]
    ))
    items.append(P(
        "<b>Skip the Private API if:</b> the Mac is your primary computer, you need "
        "enterprise MDM compliance, or basic send/receive without reactions is sufficient.",
        S["body"]
    ))
    items.append(sp(6))

    items.append(P("<b>Intel Mac -- Disabling SIP</b>", S["h3"]))
    items.append(P(
        "Restart into Recovery Mode by holding Cmd+R at boot. "
        "Open Terminal from the Utilities menu.",
        S["body"]
    ))
    items.append(code_block([
        "# In Recovery Mode Terminal:",
        "csrutil disable",
        "",
        "# Reboot normally",
        "reboot",
        "",
        "# Verify SIP status after reboot",
        "csrutil status",
        "# Expected output: System Integrity Protection status: disabled.",
    ], S))

    items.append(P("<b>Apple Silicon -- Disabling SIP</b>", S["h3"]))
    items.append(P(
        "Apple Silicon Macs use a different recovery flow. "
        f"See the SIP on Unofficial Macs guide{fn(9)} if using a Hackintosh or OpenCore.",
        S["body"]
    ))
    items.append(code_block([
        "# Shut down completely, then hold Power button until 'Loading startup options'",
        "# Click Options > Continue > open Terminal",
        "csrutil disable",
        "# Enter your admin password when prompted",
        "reboot",
    ], S))

    items.append(P(
        "After reboot, follow the Private API installation guide to install "
        f"the required system plugins.{fn(7)}",
        S["body"]
    ))
    return items


def section_docker_osx(S, inch):
    from reportlab.platypus import PageBreak
    items = []
    items.append(section_header("7.  Docker-OSX Self-Hosting Option", S))
    items.append(P(
        f"Docker-OSX{fn(8)} runs macOS in a KVM virtual machine inside Docker, allowing "
        "you to host BlueBubbles on Linux hardware without a physical Mac. "
        "This is useful for a homelab server or a cloud VPS with KVM support.",
        S["body"]
    ))
    items.append(sp(4))
    items.append(P("<b>Prerequisites</b>", S["h3"]))
    prereqs = [
        "Linux host with KVM enabled: <code>egrep -c '(vmx|svm)' /proc/cpuinfo</code> returns &gt; 0",
        "Docker Engine 20.10+ with <code>--privileged</code> support",
        "At least 50 GB free disk, 8 GB RAM",
        "Docker-OSX image: <code>docker pull sickcodes/docker-osx:latest</code>",
    ]
    for p in prereqs:
        items.append(P(f"- {p}", S["bullet"]))
    items.append(sp(6))

    items.append(P("<b>Basic Docker-OSX launch</b>", S["h3"]))
    items.append(code_block([
        "docker run -it \\",
        "  --device /dev/kvm \\",
        "  -p 50922:10022 \\",
        "  -v /tmp/.X11-unix:/tmp/.X11-unix \\",
        "  -e DISPLAY=\"${DISPLAY:-:0.0}\" \\",
        "  -e GENERATE_UNIQUE=true \\",
        "  sickcodes/docker-osx:latest",
    ], S))
    items.append(P(
        "Once macOS boots inside the container, install BlueBubbles.app normally. "
        "Configure Tailscale inside the VM for secure external access. "
        "Use <code>docker compose</code> to run Docker-OSX as a persistent service "
        f"that survives reboots.{fn(8)}",
        S["body"]
    ))
    items.append(P(
        "<b>Limitation:</b> Private API features (Section 6) require SIP disabled "
        "inside the Docker-OSX VM. Follow the Intel Mac steps in Section 6 inside "
        "the VM's recovery console.",
        S["body"]
    ))
    items.append(sp(6))
    items.append(P("<b>docker-compose.yml for persistent Docker-OSX</b>", S["h3"]))
    items.append(P(
        "Use the following Compose file to run Docker-OSX as a system service "
        f"that restarts automatically on host reboot:{fn(8)}",
        S["body"]
    ))
    items.append(code_block([
        "version: '3.8'",
        "services:",
        "  macos-bb:",
        "    image: sickcodes/docker-osx:latest",
        "    restart: unless-stopped",
        "    privileged: true",
        "    devices:",
        "      - /dev/kvm",
        "    environment:",
        "      - GENERATE_UNIQUE=true",
        "      - DISPLAY=${DISPLAY:-:0}",
        "    volumes:",
        "      - /tmp/.X11-unix:/tmp/.X11-unix",
        "      - bb_data:/var/lib/bluebubbles",
        "volumes:",
        "  bb_data:",
    ], S))
    items.append(code_block([
        "# Start the service",
        "docker compose up -d",
        "",
        "# Tail logs",
        "docker compose logs -f macos-bb",
    ], S))
    items.append(PageBreak())
    return items


def section_android(S, inch):
    items = []
    items.append(section_header("8.  Android Client Checklist", S))
    items.append(P(
        "Install the BlueBubbles Android app from the Play Store or F-Droid. "
        "Complete each item below before connecting.",
        S["body"]
    ))
    items.append(sp(4))

    checks = [
        "Install Tailscale on Android and sign in to the same Tailscale account.",
        "Open Tailscale and confirm your Mac appears in the peer list.",
        "In BlueBubbles Android: Settings > Server URL -- enter your Tailscale URL.",
        "Enter your BlueBubbles API passphrase.",
        "Tap <b>Connect</b> -- status should show <b>Connected</b> within 5 seconds.",
        "Send a test iMessage to yourself to confirm delivery.",
        "Enable <b>Background Connection</b> in Android app settings to keep socket alive.",
        "Disable battery optimization for BlueBubbles in Android settings.",
        "Set notification permission to <b>Allow</b> for message alerts.",
        "Test sending an attachment (photo) to confirm media pipeline works.",
    ]
    for c in checks:
        items.append(check_item(c, S))

    items.append(sp(8))
    items.append(P("<b>TLS Verification &amp; Certificate Troubleshooting</b>", S["h3"]))
    items.append(P(
        "When using Option B (tailscale serve TLS) or Funnel, the app may show "
        "a certificate error on first connection. Check the Android logcat for:",
        S["body"]
    ))
    items.append(code_block([
        "# Filter BlueBubbles certificate errors in logcat",
        "adb logcat | grep -E 'HandshakeException|CERTIFICATE_VERIFY_FAILED'",
        "",
        "# Common causes:",
        "#  HandshakeException: No subjectAltName entries -- wrong hostname",
        "#  CERTIFICATE_VERIFY_FAILED: system CA store missing .ts.net cert",
    ], S))
    items.append(P(
        f"If you see <b>CERTIFICATE_VERIFY_FAILED</b>, the Android system CA store does "
        f"not include Let's Encrypt. On older Android (&lt;7.1) this is common.{fn(10)} "
        "Workaround: add the Let's Encrypt ISRG Root X1 certificate to the Android "
        "user certificate store via Settings > Security > Install Certificate.",
        S["body"]
    ))
    items.append(P(
        "If you see <b>HandshakeException</b>, verify the BlueBubbles Server URL "
        "matches the <code>tailscale serve status</code> hostname exactly, "
        "including no trailing slash.",
        S["body"]
    ))
    return items


def section_windows(S, inch):
    from reportlab.platypus import PageBreak
    items = []
    items.append(section_header("9.  Windows Client Checklist", S))
    items.append(P(
        "Download the BlueBubbles Desktop client from bluebubbles.app and install Tailscale "
        "for Windows. Complete each item below.",
        S["body"]
    ))
    items.append(sp(4))

    checks = [
        "Install Tailscale for Windows and sign in.",
        "Confirm the Mac peer appears in the Tailscale tray menu.",
        "Open BlueBubbles Desktop > Settings > Server URL -- enter Tailscale URL.",
        "Enter the API passphrase and click <b>Connect</b>.",
        "Test send and receive a message before enabling any advanced features.",
        "Enable <b>Launch at startup</b> in BlueBubbles Desktop settings.",
        "Allow BlueBubbles through Windows Defender Firewall when prompted.",
    ]
    for c in checks:
        items.append(check_item(c, S))

    items.append(sp(8))
    items.append(P("<b>TLS Verification via PowerShell</b>", S["h3"]))
    items.append(P(
        "Verify TLS connectivity and inspect the certificate thumbprint "
        "before trusting the connection:",
        S["body"]
    ))
    items.append(code_block([
        "# Quick connectivity check (replace with your .ts.net hostname)",
        "Invoke-WebRequest -Uri https://<hostname>.ts.net -UseBasicParsing",
        "",
        "# Inspect certificate thumbprint",
        "$req = [Net.HttpWebRequest]::Create('https://<hostname>.ts.net')",
        "$req.GetResponse() | Out-Null",
        "$cert = $req.ServicePoint.Certificate",
        "Write-Host 'Thumbprint:' $cert.GetCertHashString()",
        "Write-Host 'Issuer:' $cert.Issuer",
        "Write-Host 'Expiry:' $cert.GetExpirationDateString()",
    ], S))
    items.append(P(
        "The issuer should be <b>Let's Encrypt</b> and expiry should be within 90 days "
        "of issuance. Tailscale renews the certificate automatically; if it shows expired, "
        "run <code>tailscale serve --https=443 1234</code> again to force renewal.",
        S["body"]
    ))
    items.append(PageBreak())
    return items


def section_hygiene(S, inch):
    items = []
    items.append(section_header("10. Operational Hygiene &amp; Hardening", S))

    bullets = [
        "<b>Keep macOS updated.</b> Security patches frequently address privilege-escalation "
        "vulnerabilities that are amplified when SIP is disabled.",
        "<b>Update BlueBubbles regularly.</b> Enable auto-update or check "
        + link("https://github.com/BlueBubblesApp/bluebubbles-server/releases", "GitHub releases")
        + " weekly.",
        "<b>Rotate the API passphrase</b> every 90 days. Update all connected clients after rotation.",
        "<b>Review Tailscale ACLs.</b> Restrict which Tailscale nodes can reach port 1234. "
        "Use a tag-based ACL policy so only your personal devices connect.",
        "<b>Enable Tailscale key expiry.</b> Set device key expiry to 90 days so lost devices "
        "are automatically de-authorized.",
        "<b>Log retention.</b> BlueBubbles writes logs to ~/Library/Logs/BlueBubbles/. "
        "Rotate or delete logs older than 30 days to prevent disk exhaustion.",
        "<b>Backup chat.db.</b> The iMessage database lives at "
        "~/Library/Messages/chat.db. Back it up before any macOS upgrade.",
        "<b>Monitor Tailscale connectivity.</b> Add a cron job or launchd plist that "
        "pings your Tailscale IP and sends an alert if unreachable for &gt;5 minutes.",
    ]
    for b in bullets:
        items.append(P(f"- {b}", S["bullet"]))
    return items


def section_appendix_a(S, inch):
    items = []
    items.append(section_header("Appendix A -- Commands Reference", S))
    items.append(P("<b>Tailscale</b>", S["h3"]))
    items.append(code_block([
        "tailscale ip -4                        # show Tailscale IPv4",
        "tailscale serve --bg --https=443 1234  # serve TLS (Sec. 4, Option B)",
        "tailscale funnel --bg --https=443 1234 # public funnel (Sec. 5)",
        "tailscale serve status                 # list active serve configs",
        "tailscale funnel off                   # disable funnel",
        "tailscale status                       # peer list",
    ], S))
    items.append(sp(4))
    items.append(P("<b>SIP / Private API</b>", S["h3"]))
    items.append(code_block([
        "csrutil status                         # check SIP status",
        "csrutil disable                        # disable SIP (Recovery Mode only)",
        "csrutil enable                         # re-enable SIP (Recovery Mode)",
    ], S))
    items.append(sp(4))
    items.append(P("<b>Verification</b>", S["h3"]))
    items.append(code_block([
        "# Test BlueBubbles REST API",
        "curl -s https://<hostname>.ts.net/api/v1/ping",
        "",
        "# Check TLS certificate",
        "curl -vI https://<hostname>.ts.net 2>&1 | grep -E 'subject|issuer|expire'",
        "",
        "# Android certificate check (requires adb)",
        "adb logcat | grep -E 'HandshakeException|CERTIFICATE_VERIFY_FAILED'",
    ], S))
    return items


def section_appendix_b(S, inch):
    items = []
    items.append(section_header("Appendix B -- Troubleshooting Matrix", S))

    rows = [
        ("Server shows offline in app",
         "Check BlueBubbles is running on Mac; verify Tailscale is connected on both devices",
         "tailscale status"),
        ("CERTIFICATE_VERIFY_FAILED on Android",
         "Android CA store missing Let's Encrypt root; add ISRG Root X1 cert",
         "Settings > Security > Install Certificate"),
        ("HandshakeException on Android",
         "Server URL hostname mismatch; check trailing slashes",
         "tailscale serve status"),
        ("Full Disk Access prompt missing",
         "App not in FDA list; drag BlueBubbles.app manually into System Settings > FDA",
         "System Settings > Privacy > Full Disk Access"),
        ("Contacts not resolving",
         "Contacts permission not granted or needs reset",
         "Remove and re-add in System Settings > Contacts"),
        ("Private API features missing",
         "SIP still enabled or plugins not installed",
         "csrutil status"),
        ("Messages delayed / not arriving",
         "Background app refresh killed; disable battery optimization",
         "Android battery settings for BlueBubbles"),
        ("Docker-OSX VM kernel panic",
         "KVM not enabled on host; check /proc/cpuinfo for vmx/svm",
         "egrep -c '(vmx|svm)' /proc/cpuinfo"),
        ("Tailscale serve cert expired",
         "Re-run tailscale serve to force certificate renewal",
         "tailscale serve --https=443 1234"),
    ]
    t = build_table(
        ["Symptom", "Cause / Fix", "Verify with"],
        rows,
        [1.8*inch, 2.9*inch, 1.6*inch],
        S
    )
    items.append(t)
    return items


def section_sources(S, inch):
    from reportlab.platypus import Paragraph
    items = []
    items.append(section_header("Sources", S))

    sources = [
        ("1", "Tailscale blog -- BlueBubbles with Tailscale",
         "https://tailscale.com/blog/bluebubbles-tailscale-imessage-android-pc-no-port-forwarding"),
        ("2", "BlueBubbles Docs -- Manual Setup",
         "https://docs.bluebubbles.app/server/installation-guides/manual-setup"),
        ("3", "GitHub -- Contacts fix",
         "https://github.com/BlueBubblesApp/bluebubbles-docs/blob/master/server/troubleshooting-guides/bluebubbles-server-cannot-access-macos-contacts.md"),
        ("4", "GitHub Issue #792 -- Accessibility",
         "https://github.com/BlueBubblesApp/bluebubbles-server/issues/792"),
        ("5", "BlueBubbles -- Standard Install",
         "https://bluebubbles.app/install/"),
        ("6", "BlueBubbles Docs -- Tailscale VPN Setup",
         "https://docs.bluebubbles.app/server/advanced/byo-proxy-service-guides/tailscale-vpn-setup"),
        ("7", "BlueBubbles Docs -- Private API Installation",
         "https://docs.bluebubbles.app/private-api/installation"),
        ("8", "BlueBubbles Docs -- Docker-OSX as a Service",
         "https://docs.bluebubbles.app/server/advanced/macos-virtualization/running-bluebubbles-in-docker-osx/configuring-bluebubbles-as-a-service"),
        ("9", "BlueBubbles Docs -- SIP on Unofficial Macs",
         "https://docs.bluebubbles.app/server/advanced/disabling-sip-on-unofficial-macs-for-the-private-api"),
        ("10", "GitHub Issue #2688 -- Android CA issue",
         "https://github.com/BlueBubblesApp/bluebubbles-app/issues/2688"),
        ("11", "BlueBubbles Blog -- Simplified Setup",
         "https://docs.bluebubbles.app/blog/simplified-setup"),
    ]
    for num, label, url in sources:
        items.append(P(
            f"{num}. {label} -- {link(url)}",
            S["footnote"]
        ))
        items.append(sp(2))
    return items


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def build():
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Paragraph, Spacer, PageBreak

    _setup_fonts()
    S = _build_styles()

    doc = SimpleDocTemplate(
        str(PDF_OUT),
        pagesize=letter,
        title="BlueBubbles \u2014 Secure Local-First Setup Guide",
        author="Perplexity Computer",
        subject="Self-hosting iMessage relay with Tailscale VPN",
        creator="build_bluebubbles_guide.py",
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
    )

    story = []
    story += section_cover(S, inch)
    story += section_threat_model(S, inch)
    story += section_prerequisites(S, inch)
    story += section_install_server(S, inch)
    story += section_tailscale(S, inch)
    story += section_funnel(S, inch)
    story += section_private_api(S, inch)
    story += section_docker_osx(S, inch)
    story += section_android(S, inch)
    story += section_windows(S, inch)
    story += section_hygiene(S, inch)
    story += section_appendix_a(S, inch)
    story += section_appendix_b(S, inch)
    story += section_sources(S, inch)

    doc.build(story)
    log.info("PDF written to %s", PDF_OUT)
    return PDF_OUT


if __name__ == "__main__":
    out = build()
    print(f"SUCCESS: {out}")
