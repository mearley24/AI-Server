#!/usr/bin/env python3
"""
TV & Mount Recommendations PDF Generator — Symphony Smart Homes
Config-driven template. Pass a JSON config file as the first argument:
    python generate.py config.json
Or import and call programmatically:
    from generate import build_pdf
    build_pdf(config_dict, output_path)
"""

import json
import os
import sys
import urllib.request

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ─────────────────────────────────────────────────────────────────────────────
# FONTS
# ─────────────────────────────────────────────────────────────────────────────

FONT_DIR = "/tmp/fonts"
FONT_URLS = {
    "Inter.ttf": "https://fonts.gstatic.com/s/inter/v13/UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiA.woff2",
    "DMSans.ttf": "https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriCZOIHQ.woff2",
}

# Fallback direct TTF download URLs (woff2 may not register; use TTF sources)
FONT_URLS_TTF = {
    "Inter.ttf": (
        "https://github.com/rsms/inter/releases/download/v3.19/Inter-3.19.zip",
        None,  # zip — handled specially below
    ),
    "DMSans.ttf": (
        "https://fonts.google.com/download?family=DM+Sans",
        None,
    ),
}

# Direct TTF file URLs that work reliably
FONT_DIRECT_URLS = {
    "Inter.ttf": "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "DMSans.ttf": "https://github.com/google/fonts/raw/main/ofl/dmsans/DMSans%5Bopsz%2Cwght%5D.ttf",
}


def _ensure_fonts():
    """Download Inter and DMSans TTF fonts to /tmp/fonts/ if not already present."""
    os.makedirs(FONT_DIR, exist_ok=True)
    for fname, url in FONT_DIRECT_URLS.items():
        dest = os.path.join(FONT_DIR, fname)
        if not os.path.exists(dest):
            print(f"Downloading {fname}...", end=" ", flush=True)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                with open(dest, "wb") as f:
                    f.write(data)
                print("done")
            except Exception as e:
                print(f"FAILED ({e})")
                # Try alternate: use a bundled known-good URL
                _download_font_fallback(fname, dest)


def _download_font_fallback(fname, dest):
    """Attempt alternate download sources for fonts."""
    alternates = {
        "Inter.ttf": [
            "https://github.com/google/fonts/raw/refs/heads/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
            "https://cdn.jsdelivr.net/npm/@fontsource/inter/files/inter-latin-400-normal.woff2",
        ],
        "DMSans.ttf": [
            "https://github.com/google/fonts/raw/refs/heads/main/ofl/dmsans/DMSans%5Bopsz%2Cwght%5D.ttf",
            "https://cdn.jsdelivr.net/npm/@fontsource/dm-sans/files/dm-sans-latin-400-normal.woff2",
        ],
    }
    for url in alternates.get(fname, []):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with open(dest, "wb") as f:
                f.write(data)
            print(f"  → fallback succeeded for {fname}")
            return
        except Exception:
            continue
    print(f"  → all fallbacks failed for {fname}; will use Helvetica")


_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    _ensure_fonts()
    inter_path = os.path.join(FONT_DIR, "Inter.ttf")
    dmsans_path = os.path.join(FONT_DIR, "DMSans.ttf")
    try:
        if os.path.exists(inter_path) and os.path.getsize(inter_path) > 10000:
            pdfmetrics.registerFont(TTFont("Inter", inter_path))
        else:
            pdfmetrics.registerFont(TTFont("Inter", "Helvetica"))
    except Exception:
        pass  # Helvetica is built-in, no registration needed
    try:
        if os.path.exists(dmsans_path) and os.path.getsize(dmsans_path) > 10000:
            pdfmetrics.registerFont(TTFont("DMSans", dmsans_path))
        else:
            pdfmetrics.registerFont(TTFont("DMSans", "Helvetica-Bold"))
    except Exception:
        pass
    _FONTS_REGISTERED = True


# ─────────────────────────────────────────────────────────────────────────────
# COLORS  (matches build_tv_pdf_v2.py exactly)
# ─────────────────────────────────────────────────────────────────────────────

TEAL         = HexColor("#01696F")
DARK_TEAL    = HexColor("#0C4E54")
LIGHT_BG     = HexColor("#F7F6F2")
TEXT         = HexColor("#28251D")
TEXT_MUTED   = HexColor("#5A5856")
BORDER       = HexColor("#D4D1CA")
WARN_BG      = HexColor("#FFF7ED")
WARN_BORDER  = HexColor("#964219")
SUCCESS_BG   = HexColor("#F0F7EC")
SUCCESS_BG_C = HexColor("#437A22")  # success border/callout
TABLE_HEADER = HexColor("#1C2A2B")
TABLE_ALT    = HexColor("#F4F7F7")
RED_ACCENT   = HexColor("#A13544")
BLUE_BG      = HexColor("#EFF6FB")
BLUE_BORDER  = HexColor("#006494")


# ─────────────────────────────────────────────────────────────────────────────
# STYLES  (built lazily after fonts are registered)
# ─────────────────────────────────────────────────────────────────────────────

def _make_styles():
    base = getSampleStyleSheet()
    title_style          = ParagraphStyle("DocTitle",     parent=base["Title"],    fontName="DMSans",  fontSize=26, leading=32, textColor=DARK_TEAL, spaceAfter=4,  alignment=TA_LEFT)
    subtitle_style       = ParagraphStyle("Subtitle",     parent=base["Normal"],   fontName="Inter",   fontSize=11, leading=15, textColor=TEXT_MUTED, spaceAfter=20)
    h1_style             = ParagraphStyle("H1",           parent=base["Heading1"], fontName="DMSans",  fontSize=17, leading=22, textColor=DARK_TEAL, spaceBefore=20, spaceAfter=8)
    h2_style             = ParagraphStyle("H2",           parent=base["Heading2"], fontName="DMSans",  fontSize=13, leading=17, textColor=TEXT,      spaceBefore=14, spaceAfter=6)
    body_style           = ParagraphStyle("Body",         parent=base["Normal"],   fontName="Inter",   fontSize=10, leading=15, textColor=TEXT,       spaceAfter=8)
    body_bold            = ParagraphStyle("BodyBold",     parent=body_style,       fontName="DMSans",  fontSize=10, leading=15)
    small_style          = ParagraphStyle("Small",        parent=body_style,       fontSize=8.5, leading=12, textColor=TEXT_MUTED)
    callout_style        = ParagraphStyle("Callout",      parent=body_style,       fontSize=10, leading=14, leftIndent=12, rightIndent=12, spaceBefore=4, spaceAfter=4)
    table_header_style   = ParagraphStyle("TH",           parent=body_style,       fontName="DMSans",  fontSize=9, leading=12, textColor=white)
    table_cell_style     = ParagraphStyle("TC",           parent=body_style,       fontSize=9, leading=12, spaceAfter=0)
    table_cell_bold      = ParagraphStyle("TCB",          parent=table_cell_style, fontName="DMSans")
    table_cell_warn      = ParagraphStyle("TCW",          parent=table_cell_style, textColor=RED_ACCENT)
    table_cell_center    = ParagraphStyle("TCC",          parent=table_cell_style, alignment=TA_CENTER)
    table_cell_ctr_bold  = ParagraphStyle("TCCB",         parent=table_cell_bold,  alignment=TA_CENTER)
    footnote_style       = ParagraphStyle("Footnote",     parent=base["Normal"],   fontName="Inter",   fontSize=7.5, leading=10, textColor=TEXT_MUTED, spaceAfter=2)
    source_hdr_style     = ParagraphStyle("SH",           parent=body_bold,        fontSize=9, textColor=TEXT_MUTED)
    return {
        "title": title_style, "subtitle": subtitle_style,
        "h1": h1_style, "h2": h2_style,
        "body": body_style, "body_bold": body_bold,
        "small": small_style, "callout": callout_style,
        "th": table_header_style, "tc": table_cell_style,
        "tcb": table_cell_bold, "tcw": table_cell_warn,
        "tcc": table_cell_center, "tccb": table_cell_ctr_bold,
        "footnote": footnote_style, "source_hdr": source_hdr_style,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _make_table(headers, rows, col_widths, S):
    header_cells = [Paragraph(h, S["th"]) for h in headers]
    data = [header_cells] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND",   (0, 0), (-1, 0),  TABLE_HEADER),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  white),
        ("FONTNAME",     (0, 0), (-1, 0),  "DMSans"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("ALIGN",        (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("GRID",         (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",   (0, 0), (-1, 0),  8),
        ("BOTTOMPADDING",(0, 0), (-1, 0),  8),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT))
    t.setStyle(TableStyle(cmds))
    return t


def _callout_box(text, border_color, bg_color, S):
    inner = Paragraph(text, S["callout"])
    t = Table([[inner]], colWidths=[460])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg_color),
        ("BOX",           (0, 0), (-1, -1), 0.5, border_color),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def TC(text, S):    return Paragraph(text, S["tc"])
def TCB(text, S):   return Paragraph(text, S["tcb"])
def TCW(text, S):   return Paragraph(text, S["tcw"])
def TCC(text, S):   return Paragraph(text, S["tcc"])
def TCCB(text, S):  return Paragraph(text, S["tccb"])


# ─────────────────────────────────────────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_intro(cfg, story, S):
    """Page 1: title, intro paragraph, key takeaway."""
    project_name = cfg["project_name"]
    client_name  = cfg["client_name"]
    date         = cfg["date"]
    first_name   = cfg.get("client_first_name", client_name.split()[0])

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("TV &amp; Mount Recommendations", S["title"]))
    story.append(Paragraph(
        f"{project_name}  \u2022  Prepared for {client_name}  \u2022  {date}",
        S["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=16))

    intro = cfg.get(
        "intro_paragraph",
        f"{first_name} \u2014 these recommendations are not meant to replace your selections. "
        "This document highlights considerations specific to an integrated Control4 smart home \u2014 "
        "native IP control, dealer warranty support, mount serviceability, and long-term firmware commitment \u2014 "
        "that aren\u2019t always visible on a spec sheet. We will support whatever you choose."
    )
    story.append(Paragraph(intro, S["body"]))
    story.append(Spacer(1, 6))

    key_takeaway = cfg.get(
        "key_takeaway",
        "<b>Key Takeaway:</b> We can deliver a package with native Control4 integration "
        "across every TV, dealer warranty support, and pricing in the same range as your current selections."
    )
    story.append(_callout_box(key_takeaway, TEAL, LIGHT_BG, S))


def _build_price_volatility(cfg, story, S):
    """Price volatility section with the client TV schedule table."""
    story.append(Spacer(1, 10))
    story.append(Paragraph("A Note on Pricing", S["h1"]))
    story.append(Paragraph(
        "Retail pricing on consumer TV brands fluctuates significantly based on sales cycles, "
        "retailer, and inventory. The prices in your TV schedule may not hold when it\u2019s "
        "time to purchase:<super>1</super>", S["body"]))

    vol_headers = ["TV", "Low Price Observed", "High Price Observed", "Swing"]
    vol_rows = []
    seen = {}  # deduplicate rows by model
    for tv in cfg["client_tv_schedule"]:
        model = tv["model"]
        if model in seen:
            continue
        seen[model] = True
        swing = tv.get("price_swing", "")
        # If no swing provided, just leave blank rather than compute
        vol_rows.append([
            TCB(model, S),
            TC(tv["price_low"], S),
            TC(tv["price_high"], S),
            TCW(swing, S) if swing else TC("", S),
        ])
    story.append(_make_table(vol_headers, vol_rows, [105, 130, 130, 105], S))

    story.append(Spacer(1, 8))
    story.append(_callout_box(
        "<b>Price certainty:</b> When supplied through Symphony, TV pricing is locked at time of agreement. "
        "To secure current pricing, Symphony can purchase and store all units ahead of the installation schedule. "
        "No hunting for flash sales, no hoping prices hold.",
        BLUE_BORDER, BLUE_BG, S))


def _build_c4_integration(cfg, story, S):
    """C4 integration methods table + warning callout."""
    story.append(Spacer(1, 8))
    story.append(Paragraph("Control4 Integration", S["h1"]))
    story.append(Paragraph(
        "This is the most important consideration. In a Control4 home, every device should be controllable "
        "from your iPads and the C4 app. TVs that lack native integration create ongoing issues:<super>2</super>",
        S["body"]))

    int_headers = ["Method", "How It Works", "Your Experience"]
    int_rows = [
        [TCB("Native SDDP (IP)", S),
         TC("TV auto-discovers on your network. Two-way communication \u2014 C4 sees power state, "
            "input, volume in real time. No extra hardware.", S),
         TC("Tap \u201cWatch TV\u201d on your iPad \u2014 it just works. Every time.", S)],

        [TCB("3rd-Party IP Driver", S),
         TC("Requires separate purchased driver from Chowmain or DriverCentral. "
            "Must be maintained when TV firmware updates.", S),
         TC("Usually works, but can break after TV updates. Symphony cannot guarantee "
            "third-party driver compatibility long-term.", S)],

        [TCB("IR (Infrared)", S),
         TC("Physical IR emitter aimed at TV sensor. One-way \u2014 C4 sends commands blind "
            "with no confirmation they were received.", S),
         TC("Commands sometimes miss. \u201cTV didn\u2019t turn on\u201d or \u201cwrong input\u201d issues. "
            "Extra hardware at every location.", S)],

        [TCB("No Driver", S),
         TC("No Control4 driver exists for this TV model.", S),
         TCW("TV cannot be controlled from C4 at all. Must use separate remote.", S)],
    ]
    story.append(_make_table(int_headers, int_rows, [90, 195, 185], S))

    story.append(Spacer(1, 8))
    warn_text = cfg.get(
        "c4_warning_text",
        "<b>Your current selections</b> include TVs that lack native Control4 integration. "
        "Third-party drivers and IR control create support issues that compromise the integrated "
        "experience this system is designed to deliver. We strongly recommend native integration "
        "for every TV in the home."
    )
    story.append(_callout_box(warn_text, WARN_BORDER, WARN_BG, S))


def _build_packages(cfg, story, S):
    """Page 2: three package options + comparison table."""
    story.append(PageBreak())
    story.append(Paragraph("Three Package Options", S["h1"]))

    pkg_intro = cfg.get(
        "packages_intro",
        "All three packages use TVs with native Control4 SDDP integration, available through our "
        "dealer network. Installation, mounting, Control4 programming, streaming setup, and menu "
        "optimization billed at standard service rates per the agreement.<super>3</super>"
    )
    # Ensure footnote 3 marker present
    if "<super>3</super>" not in pkg_intro:
        pkg_intro += "<super>3</super>"
    story.append(Paragraph(pkg_intro, S["body"]))

    pkg_headers = ["Location", "Model", "Type", "Price"]
    for pkg in cfg["packages"]:
        story.append(Spacer(1, 6 if pkg == cfg["packages"][0] else 12))
        story.append(Paragraph(pkg["name"], S["h2"]))
        story.append(Paragraph(pkg["description"], S["small"]))

        rows = []
        for loc in pkg["locations"]:
            rows.append([
                TCB(loc["location"], S),
                TC(loc["model"], S),
                TC(loc["type"], S),
                TCC(loc["price"], S),
            ])
        rows.append([TCB("", S), TC("", S), TCB("Total", S), TCCB(pkg["total"], S)])
        story.append(_make_table(pkg_headers, rows, [90, 140, 120, 80], S))

    # Comparison table
    story.append(Spacer(1, 12))
    comp = cfg["comparison_rows"]
    comp_headers = ["", cfg["packages"][0]["name"].split("\u2014")[0].strip(),
                    cfg["packages"][1]["name"].split("\u2014")[0].strip(),
                    cfg["packages"][2]["name"].split("\u2014")[0].strip()]
    comp_rows = [
        [TCB("TV Total", S)]          + [TCC(v, S) for v in comp["tv_totals"]],
        [TCB("C4 Integration", S)]    + [TCC(v, S) for v in comp["c4_integration"]],
        [TCB("IR Flashers Needed", S)]+ [TCC(v, S) for v in comp["ir_flashers"]],
        [TCB("3rd-Party Drivers", S)] + [TCC(v, S) for v in comp["third_party_drivers"]],
        [TCB("Install + Programming", S)] + [TCC(v, S) for v in comp["install_programming"]],
        [TCB("Dealer Warranty", S)]   + [TCC(v, S) for v in comp["dealer_warranty"]],
        [TCB("Firmware Support", S)]  + [TCC(v, S) for v in comp["firmware_support"]],
    ]
    story.append(_make_table(comp_headers, comp_rows, [110, 110, 110, 110], S))

    story.append(Spacer(1, 8))
    payment  = cfg.get("payment_terms", "full payment for TV equipment is required at time of package selection")
    svc_lang = cfg.get("service_rates_language", "billed at standard service rates per the agreement")
    footnote = cfg.get(
        "packages_footnote",
        f"TV pricing is based on current availability and is subject to change. To lock in these prices, "
        f"{payment}. Symphony will purchase, receive, and store all units until the installation date. "
        f"Installation, C4 programming, streaming setup, and menu optimization {svc_lang}."
    )
    story.append(Paragraph(f"<i>{footnote}</i>", S["small"]))


def _build_consumer_brands(cfg, story, S):
    """Page 3: consumer brand comparison table + warning."""
    story.append(PageBreak())
    recommended_brand = cfg.get("recommended_brand", "Samsung")
    brands = cfg.get("consumer_brands_compared", ["TCL", "Hisense"])
    b1, b2 = brands[0], brands[1]

    story.append(Paragraph(f"Why {recommended_brand} Over Consumer Brands", S["h1"]))
    story.append(Paragraph("Warranty &amp; Service", S["h2"]))

    cbr = cfg.get("consumer_brand_rows", {})
    war_headers = ["", b1, b2, recommended_brand]

    def _row(label, key, warn_cols=(0, 1)):
        vals = cbr.get(key, ["", "", ""])
        cells = [TCB(label, S)]
        for i, v in enumerate(vals[:3]):
            if i in warn_cols:
                cells.append(TCW(v, S))
            else:
                cells.append(TC(v, S))
        return cells

    war_rows = [
        _row("Warranty",           "warranty",           warn_cols=()),
        _row("Service Channel",    "service_channel",    warn_cols=()),
        _row("Wall-Mount Service", "wall_mount_service", warn_cols=(0, 1)),
        _row("Integrator Parts",   "integrator_parts",   warn_cols=(0, 1)),
        _row("5-Year Failure Rate","five_year_failure",  warn_cols=(0, 1)),
        _row("Firmware Updates",   "firmware_updates",   warn_cols=(0, 1)),
    ]
    story.append(_make_table(war_headers, war_rows, [110, 110, 110, 130], S))

    story.append(Spacer(1, 8))
    brand_warn = cfg.get(
        "consumer_brand_warning",
        f"<b>What this means for you:</b> Every TV in this house will be wall-mounted. "
        f"If a consumer-brand panel fails, getting service may require removing the TV and shipping it \u2014 "
        f"or the service partner may decline entirely. With {recommended_brand}, Symphony handles warranty "
        "claims through our dealer network, on-site."
    )
    story.append(_callout_box(brand_warn, WARN_BORDER, WARN_BG, S))


def _build_mounts(cfg, story, S):
    """Mount recommendations section: clearance problem table + success callout."""
    story.append(Spacer(1, 8))
    story.append(Paragraph("Mount Recommendations", S["h1"]))
    story.append(Paragraph("The Clearance Problem", S["h2"]))

    rb = cfg["recessed_box"]
    story.append(Paragraph(
        f"Your {rb['model']} recessed TV boxes are a great choice for cable management. "
        f"However, once devices are installed (duplex outlet, HDMI connections, low-voltage jacks), "
        f"plugs protrude approximately {rb['plug_protrusion_inches']} forward of the wall surface. "
        f"Your specified fixed mounts sit 0.5\u20130.7\u201d from the wall \u2014 they physically "
        f"cannot clear the plugs.<super>4</super>", S["body"]))

    mr = cfg["mount_recommendation"]
    cl_headers = ["Mount", "Wall Profile", "Plug Clearance", "Tilt", "Service Access"]

    # Build rows from client_mounts + the recommended mount
    cl_rows = []
    for cm in cfg.get("client_mounts", []):
        cl_rows.append([
            TCB(cm["name"], S),
            TC(cm.get("wall_profile", ""), S),
            TCW(cm.get("plug_clearance", "Plugs contact TV"), S),
            TCW(cm.get("tilt", "None"), S),
            TCW(cm.get("service_access", "Remove TV"), S),
        ])
    # Recommended mount row
    cl_rows.append([
        TCB(f"{mr['model']} (included)", S),
        TC(mr["collapsed_depth"], S),
        TC("Clears all plugs", S),
        TC(f"{mr['tilt']}, {mr['swivel']} swivel", S),
        TC(f"{mr['extension']} extension \u2014 full access", S),
    ])
    story.append(_make_table(cl_headers, cl_rows, [110, 68, 90, 100, 100], S))

    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Beyond clearance, fixed mounts offer zero tilt. For TVs mounted above eye level, "
        "this means permanent glare and a suboptimal viewing angle with no correction available.",
        S["body"]))

    ceiling_note = cfg.get("ceiling_mount_note", "")
    success_text = (
        f"<b>All packages include {mr['model']} mounts</b> for every wall-mount location. "
        f"{mr['collapsed_depth']} collapsed (clears recessed box plugs), "
        f"{mr['extension']} extension for service access, "
        f"{mr['tilt']} tilt for glare correction, {mr['swivel']} swivel, "
        f"{mr['weight_capacity']} capacity, {mr['warranty']} warranty.<super>5</super>"
    )
    if ceiling_note:
        success_text += f" {ceiling_note}"
    story.append(Spacer(1, 4))
    story.append(_callout_box(success_text, SUCCESS_BG_C, SUCCESS_BG, S))


def _build_summary(cfg, story, S):
    """Page 4: summary table + next steps."""
    story.append(PageBreak())
    story.append(Paragraph("Summary", S["h1"]))

    pkgs = cfg["packages"]
    story.append(Paragraph(
        "All three options deliver native Control4 integration across every TV, dealer warranty support, "
        "mounts that clear your recessed boxes, and firmware update commitment. "
        "Installation and programming billed at standard service rates. "
        "The difference is picture technology:", S["body"]))

    sum_data = []
    for pkg in pkgs:
        sum_data.append([
            Paragraph(f"<b>{pkg['name']}</b> \u2014 {pkg['total']}", S["tcb"]),
            TC(pkg["description"], S),
        ])
    sum_t = Table(sum_data, colWidths=[160, 310])
    sum_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    story.append(sum_t)

    story.append(Spacer(1, 12))
    summary_callout = cfg.get(
        "summary_callout",
        "<b>These are recommendations, not requirements.</b> We will fully support whichever TVs and mounts "
        "you choose. However, based on our experience with third-party drivers and IR control in integrated homes, "
        "we strongly recommend native C4 integration for every TV to ensure the system performs as designed."
    )
    story.append(_callout_box(summary_callout, TEAL, LIGHT_BG, S))

    story.append(Spacer(1, 14))
    story.append(Paragraph("Next Steps", S["h2"]))

    default_next_steps = [
        "Review this document and let us know your preference or questions.",
        "Select a package \u2014 or let us know if you\u2019d like to adjust.",
        "To lock current pricing, full payment for TV equipment is required at time of selection.",
        "Symphony will purchase, receive, and store all units until the installation date.",
    ]
    next_steps = cfg.get("next_steps", default_next_steps)
    for i, step in enumerate(next_steps, 1):
        story.append(Paragraph(f"{i}. {step}", S["body"]))


def _build_sources(cfg, story, S):
    """Sources section at the bottom of the last page."""
    sources = cfg.get("sources", [])
    if not sources:
        return

    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))
    story.append(Paragraph("Sources", S["source_hdr"]))
    for i, src in enumerate(sources, 1):
        url  = src.get("url", "")
        name = src.get("name", url)
        story.append(Paragraph(
            f'{i}. {name}, <a href="{url}" color="blue">{url}</a>',
            S["footnote"]))


# ─────────────────────────────────────────────────────────────────────────────
# HEADER / FOOTER
# ─────────────────────────────────────────────────────────────────────────────

def _make_header_footer(project_name):
    def header_footer(c, doc):
        c.saveState()
        w, h = letter
        c.setFont("Inter", 8)
        c.setFillColor(TEXT_MUTED)
        c.drawString(0.75 * inch, 0.45 * inch,
                     f"Symphony Smart Homes  \u2022  {project_name}  \u2022  Confidential")
        c.drawRightString(w - 0.75 * inch, 0.45 * inch, f"Page {doc.page}")
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(0.75 * inch, 0.55 * inch, w - 0.75 * inch, 0.55 * inch)
        c.restoreState()
    return header_footer


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def build_pdf(cfg: dict, output_path: str = None) -> str:
    """
    Build the TV & Mount Recommendations PDF from a config dict.

    Parameters
    ----------
    cfg : dict
        Configuration matching config_schema.json.
    output_path : str, optional
        Full output file path. If omitted, the filename is derived from
        cfg["project_address"] and cfg["version"].

    Returns
    -------
    str
        Absolute path to the generated PDF.
    """
    _register_fonts()
    S = _make_styles()

    # Derive output path if not provided
    if output_path is None:
        address = cfg.get("project_address", "Project").replace(" ", "_")
        version = cfg.get("version", 1)
        filename = f"{address}_TV_Mount_Recommendations_V{version}.pdf"
        output_path = os.path.join(os.getcwd(), filename)

    project_name = cfg["project_name"]
    client_name  = cfg["client_name"]
    date         = cfg["date"]

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        title=f"TV & Mount Recommendations \u2014 {project_name}",
        author="Perplexity Computer",
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    story = []

    _build_intro(cfg, story, S)
    _build_price_volatility(cfg, story, S)
    _build_c4_integration(cfg, story, S)
    _build_packages(cfg, story, S)
    _build_consumer_brands(cfg, story, S)
    _build_mounts(cfg, story, S)
    _build_summary(cfg, story, S)
    _build_sources(cfg, story, S)

    hf = _make_header_footer(project_name)
    doc.build(story, onFirstPage=hf, onLaterPages=hf)

    print(f"PDF created: {output_path}")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python generate.py <config.json> [output_path.pdf]", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else None

    if not os.path.exists(config_path):
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # If output_path not provided on CLI, derive from config
    if output_path is None:
        address = cfg.get("project_address", "Project").replace(" ", "_")
        version = cfg.get("version", 1)
        filename = f"{address}_TV_Mount_Recommendations_V{version}.pdf"
        # Place output next to the config file
        config_dir = os.path.dirname(os.path.abspath(config_path))
        output_path = os.path.join(config_dir, filename)

    build_pdf(cfg, output_path)


if __name__ == "__main__":
    main()
