#!/usr/bin/env python3
"""
invoice_generator.py — Symphony Smart Homes branded PDF invoice generator.

Generates professional invoices using ReportLab with Symphony's brand:
  - Dark navy #0D1B2A header with logo
  - Work Sans Bold headings, Inter body text
  - Stripe payment link + ACH transfer instructions
  - Letter-size portrait layout

Fonts are bundled in ./fonts/ alongside this module.

Usage:
    from invoice_generator import generate_invoice, generate_milestone_invoice
    path = generate_invoice(output_path="/tmp/inv001.pdf", ...)
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Font paths (relative to this module)
# ---------------------------------------------------------------------------
_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_WS_BOLD = str(_FONTS_DIR / "WorkSans-Bold.ttf")
_FONT_WS_REG = str(_FONTS_DIR / "WorkSans-Regular.ttf")
_FONT_INTER = str(_FONTS_DIR / "Inter-Regular.ttf")

# ---------------------------------------------------------------------------
# Brand colours
# ---------------------------------------------------------------------------
_NAVY = (0x0D / 255, 0x1B / 255, 0x2A / 255)        # #0D1B2A
_WHITE = (1.0, 1.0, 1.0)
_GRAY = (0x6B / 255, 0x72 / 255, 0x80 / 255)         # #6B7280
_BORDER = (0xE5 / 255, 0xE7 / 255, 0xEB / 255)       # #E5E7EB
_BLUE = (0x1D / 255, 0x4E / 255, 0xD8 / 255)         # link blue
_LIGHT_NAVY_BG = (0xF0 / 255, 0xF4 / 255, 0xF8 / 255)  # row alt bg

# ---------------------------------------------------------------------------
# Company info
# ---------------------------------------------------------------------------
COMPANY_NAME = "Symphony Smart Homes"
COMPANY_ADDRESS = "45 Aspen Glen Ct, Edwards, CO 81632"
COMPANY_PHONE = "(970) 519-3013"
COMPANY_EMAIL = "info@symphonysh.com"
COMPANY_WEB = "symphonysh.com"
ACH_ROUTING = "102000076"   # placeholder — user should update
ACH_ACCOUNT = "XXXXXXXXXX"  # placeholder — user should update


# ---------------------------------------------------------------------------
# ReportLab helpers
# ---------------------------------------------------------------------------

def _register_fonts() -> tuple[str, str, str]:
    """Register custom fonts and return (heading, body_bold, body) names."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.registerFont(TTFont("WorkSans-Bold", _FONT_WS_BOLD))
        pdfmetrics.registerFont(TTFont("WorkSans-Regular", _FONT_WS_REG))
        pdfmetrics.registerFont(TTFont("Inter-Regular", _FONT_INTER))
        return "WorkSans-Bold", "WorkSans-Bold", "Inter-Regular"
    except Exception:
        # Fall back to built-in Helvetica if fonts are missing
        return "Helvetica-Bold", "Helvetica-Bold", "Helvetica"


def _rgb(triple: tuple) -> object:
    from reportlab.lib.colors import Color
    return Color(*triple)


def _pt(inches: float) -> float:
    """Convert inches to points."""
    return inches * 72.0


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_header(canvas, page_width: float, page_height: float, font_heading: str) -> None:
    """Draw dark-navy header bar with Symphony logo and company name."""
    from reportlab.lib.colors import Color

    header_h = 72  # 1 inch
    header_y = page_height - header_h

    # Navy background
    canvas.setFillColor(Color(*_NAVY))
    canvas.rect(0, header_y, page_width, header_h, fill=1, stroke=0)

    # Logo — navy square with white "S"
    logo_x = _pt(0.4)
    logo_y = header_y + 12
    logo_size = 48

    # Slightly lighter navy square
    canvas.setFillColor(Color(0.15, 0.28, 0.4))
    canvas.roundRect(logo_x, logo_y, logo_size, logo_size, 4, fill=1, stroke=0)

    # "S" letter
    canvas.setFillColor(Color(*_WHITE))
    canvas.setFont(font_heading, 28)
    canvas.drawCentredString(logo_x + logo_size / 2, logo_y + 11, "S")

    # Company name + tagline
    text_x = logo_x + logo_size + 12
    canvas.setFillColor(Color(*_WHITE))
    canvas.setFont(font_heading, 18)
    canvas.drawString(text_x, header_y + 40, COMPANY_NAME.upper())

    canvas.setFont(font_heading, 8)
    canvas.setFillColor(Color(0.7, 0.78, 0.87))
    canvas.drawString(text_x, header_y + 26, "SMART HOME INTEGRATION  ·  EDWARDS, COLORADO")


def _draw_footer(canvas, page_width: float, page_num: int, total_pages: int, font_body: str) -> None:
    """Draw footer with contact info and page number."""
    from reportlab.lib.colors import Color

    y = 28
    canvas.setStrokeColor(Color(*_BORDER))
    canvas.setLineWidth(0.5)
    canvas.line(_pt(0.5), y + 12, page_width - _pt(0.5), y + 12)

    canvas.setFont(font_body, 8)
    canvas.setFillColor(Color(*_GRAY))
    footer_text = (
        f"{COMPANY_NAME}  ·  {COMPANY_ADDRESS}  ·  "
        f"{COMPANY_PHONE}  ·  {COMPANY_EMAIL}  ·  {COMPANY_WEB}"
    )
    canvas.drawCentredString(page_width / 2, y, footer_text)

    canvas.drawRightString(page_width - _pt(0.5), y, f"Page {page_num} of {total_pages}")


def _draw_horizontal_rule(canvas, x: float, y: float, width: float) -> None:
    from reportlab.lib.colors import Color
    canvas.setStrokeColor(Color(*_BORDER))
    canvas.setLineWidth(0.5)
    canvas.line(x, y, x + width, y)


def _section_label(canvas, x: float, y: float, text: str, font_heading: str) -> None:
    """Draw a small section label in navy."""
    from reportlab.lib.colors import Color
    canvas.setFont(font_heading, 9)
    canvas.setFillColor(Color(*_NAVY))
    canvas.drawString(x, y, text.upper())


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_invoice(
    output_path: str,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    client_name: str,
    client_email: str,
    client_address: str,
    project_name: str,
    quote_ref: str,
    line_items: list[dict],
    subtotal: float,
    tax: float,
    total: float,
    payment_link: str,
    payment_methods: str = "ACH Bank Transfer (preferred) | Credit Card",
    notes: str = "",
) -> str:
    """
    Generate a Symphony-branded PDF invoice.

    Args:
        output_path:     Destination .pdf file path
        invoice_number:  e.g. "INV-2026-001"
        invoice_date:    e.g. "April 8, 2026"
        due_date:        e.g. "April 22, 2026"
        client_name:     Full name of bill-to contact
        client_email:    Client email
        client_address:  Multi-line address string (use \\n for line breaks)
        project_name:    e.g. "Topletz Residence — 84 Aspen Meadow Dr"
        quote_ref:       e.g. "Q-212 V3"
        line_items:      List of dicts with keys: description, quantity, unit_price, amount
        subtotal:        Pre-tax subtotal (float, dollars)
        tax:             Tax amount (float, dollars)
        total:           Grand total (float, dollars)
        payment_link:    Stripe payment link URL
        payment_methods: Human-readable accepted payment methods string
        notes:           Optional footer notes

    Returns:
        output_path
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.colors import Color

    font_heading, font_bold, font_body = _register_fonts()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    PAGE_W, PAGE_H = letter  # 612 x 792 pts
    MARGIN_L = _pt(0.55)
    MARGIN_R = PAGE_W - _pt(0.55)
    CONTENT_W = MARGIN_R - MARGIN_L

    c = rl_canvas.Canvas(output_path, pagesize=letter)
    c.setTitle(f"{invoice_number} — {COMPANY_NAME}")
    c.setAuthor(COMPANY_NAME)
    c.setSubject(f"Invoice for {client_name}")

    # ---- Header -------------------------------------------------------
    _draw_header(c, PAGE_W, PAGE_H, font_heading)

    # ---- "INVOICE" title + meta table ---------------------------------
    y = PAGE_H - 72 - 24  # below header

    c.setFont(font_heading, 28)
    c.setFillColor(Color(*_NAVY))
    c.drawString(MARGIN_L, y, "INVOICE")

    # Invoice details on the right
    meta_x = PAGE_W - _pt(2.8)
    meta_rows = [
        ("Invoice #:", invoice_number),
        ("Date:", invoice_date),
        ("Due Date:", due_date),
        ("Project:", project_name),
        ("Quote Ref:", quote_ref),
    ]
    meta_y = y + 6
    row_h = 16

    for i, (label, value) in enumerate(meta_rows):
        row_y = meta_y - i * row_h
        c.setFont(font_bold, 8.5)
        c.setFillColor(Color(*_GRAY))
        c.drawRightString(meta_x + 78, row_y, label)
        c.setFont(font_body, 8.5)
        c.setFillColor(Color(*_NAVY))
        c.drawString(meta_x + 82, row_y, value)

    y -= 14
    _draw_horizontal_rule(c, MARGIN_L, y, CONTENT_W)

    # ---- Bill To section -----------------------------------------------
    y -= 20
    _section_label(c, MARGIN_L, y, "Bill To", font_heading)

    y -= 16
    c.setFont(font_bold, 11)
    c.setFillColor(Color(*_NAVY))
    c.drawString(MARGIN_L, y, client_name)

    y -= 14
    c.setFont(font_body, 9)
    c.setFillColor(Color(*_GRAY))
    for line in client_address.split("\n"):
        c.drawString(MARGIN_L, y, line.strip())
        y -= 12
    c.drawString(MARGIN_L, y, client_email)
    y -= 18

    _draw_horizontal_rule(c, MARGIN_L, y, CONTENT_W)
    y -= 16

    # ---- Line items table header ----------------------------------------
    COL_DESC_X = MARGIN_L
    COL_QTY_X = MARGIN_L + CONTENT_W * 0.58
    COL_UNIT_X = MARGIN_L + CONTENT_W * 0.72
    COL_AMT_X = MARGIN_R

    # Table header background
    c.setFillColor(Color(*_NAVY))
    c.rect(MARGIN_L, y - 4, CONTENT_W, 20, fill=1, stroke=0)

    c.setFont(font_heading, 8.5)
    c.setFillColor(Color(*_WHITE))
    c.drawString(COL_DESC_X + 4, y + 2, "DESCRIPTION")
    c.drawCentredString(COL_QTY_X + 20, y + 2, "QTY")
    c.drawCentredString(COL_UNIT_X + 20, y + 2, "UNIT PRICE")
    c.drawRightString(COL_AMT_X - 4, y + 2, "AMOUNT")

    y -= 4

    # ---- Line items -------------------------------------------------------
    for i, item in enumerate(line_items):
        row_y = y - (i + 1) * 22

        # Alternate row background
        if i % 2 == 1:
            c.setFillColor(Color(*_LIGHT_NAVY_BG))
            c.rect(MARGIN_L, row_y - 4, CONTENT_W, 22, fill=1, stroke=0)

        desc = str(item.get("description", ""))
        qty = item.get("quantity", 1)
        unit_price = item.get("unit_price", 0.0)
        amount = item.get("amount", 0.0)

        c.setFont(font_body, 9)
        c.setFillColor(Color(*_NAVY))

        # Truncate description if too long
        max_desc_chars = 62
        if len(desc) > max_desc_chars:
            desc = desc[:max_desc_chars - 1] + "…"

        c.drawString(COL_DESC_X + 4, row_y + 4, desc)
        c.drawCentredString(COL_QTY_X + 20, row_y + 4, str(qty))
        c.drawCentredString(COL_UNIT_X + 20, row_y + 4, f"${unit_price:,.2f}")
        c.drawRightString(COL_AMT_X - 4, row_y + 4, f"${amount:,.2f}")

    y -= (len(line_items) + 1) * 22
    _draw_horizontal_rule(c, MARGIN_L, y, CONTENT_W)

    # ---- Totals section --------------------------------------------------
    y -= 10
    totals_x = COL_UNIT_X - 20
    totals_label_x = totals_x + 2
    totals_val_x = COL_AMT_X - 4

    def _total_row(label: str, value: str, bold: bool = False, large: bool = False):
        nonlocal y
        size = 11 if large else 9
        if bold or large:
            c.setFont(font_bold, size)
        else:
            c.setFont(font_body, size)
        c.setFillColor(Color(*_GRAY) if not (bold or large) else Color(*_NAVY))
        c.drawString(totals_label_x, y, label)
        c.drawRightString(totals_val_x, y, value)
        y -= (16 if large else 13)

    _total_row("Subtotal:", f"${subtotal:,.2f}")
    _total_row("Tax:", f"${tax:,.2f}")

    # Total highlight box
    y -= 4
    total_box_h = 24
    c.setFillColor(Color(*_NAVY))
    c.rect(totals_x - 4, y - 6, COL_AMT_X - totals_x + 8, total_box_h, fill=1, stroke=0)
    c.setFont(font_heading, 12)
    c.setFillColor(Color(*_WHITE))
    c.drawString(totals_label_x, y + 2, "TOTAL DUE:")
    c.drawRightString(totals_val_x, y + 2, f"${total:,.2f}")
    y -= total_box_h

    y -= 20
    _draw_horizontal_rule(c, MARGIN_L, y, CONTENT_W)

    # ---- Payment section -------------------------------------------------
    y -= 16
    _section_label(c, MARGIN_L, y, "Payment", font_heading)
    y -= 16

    # Payment link button-style box
    c.setFillColor(Color(*_BLUE))
    c.roundRect(MARGIN_L, y - 6, 220, 26, 4, fill=1, stroke=0)
    c.setFont(font_heading, 10)
    c.setFillColor(Color(*_WHITE))
    c.drawCentredString(MARGIN_L + 110, y + 4, "Pay Online (Stripe)")

    c.setFont(font_body, 8)
    c.setFillColor(Color(*_BLUE))
    c.drawString(MARGIN_L, y - 18, payment_link)

    # Accepted methods
    c.setFont(font_body, 8.5)
    c.setFillColor(Color(*_GRAY))
    c.drawString(MARGIN_L + 230, y + 4, f"Accepted: {payment_methods}")

    y -= 36
    _section_label(c, MARGIN_L, y, "ACH Bank Transfer Instructions", font_heading)
    y -= 14

    ach_lines = [
        f"Bank:             Wells Fargo Bank",
        f"Account Name:     {COMPANY_NAME}",
        f"Routing Number:   {ACH_ROUTING}",
        f"Account Number:   {ACH_ACCOUNT}",
        f"Reference:        {invoice_number}",
    ]
    c.setFont(font_body, 9)
    c.setFillColor(Color(*_NAVY))
    for line in ach_lines:
        c.drawString(MARGIN_L + 8, y, line)
        y -= 13

    # Notes
    if notes:
        y -= 10
        _draw_horizontal_rule(c, MARGIN_L, y, CONTENT_W)
        y -= 16
        _section_label(c, MARGIN_L, y, "Notes", font_heading)
        y -= 14
        c.setFont(font_body, 9)
        c.setFillColor(Color(*_GRAY))
        for note_line in notes.split("\n"):
            c.drawString(MARGIN_L, y, note_line.strip())
            y -= 13

    # ---- Footer ----------------------------------------------------------
    _draw_footer(c, PAGE_W, 1, 1, font_body)

    c.save()
    return output_path


# ---------------------------------------------------------------------------
# Milestone invoice convenience wrapper
# ---------------------------------------------------------------------------

def generate_milestone_invoice(
    output_path: str,
    client_name: str,
    client_email: str,
    project_name: str,
    quote_ref: str,
    milestone_name: str,
    milestone_amount: float,
    payment_link: str,
    client_address: str = "",
    invoice_number: Optional[str] = None,
    invoice_date: Optional[str] = None,
    due_date: Optional[str] = None,
    notes: str = "",
) -> str:
    """
    Convenience wrapper that generates a single-line-item milestone invoice.

    Args:
        output_path:       Destination .pdf path
        client_name:       Client full name
        client_email:      Client email
        project_name:      e.g. "Topletz Residence — 84 Aspen Meadow Dr"
        quote_ref:         e.g. "Q-212 V3"
        milestone_name:    e.g. "Deposit (60%)"
        milestone_amount:  Dollar amount (float)
        payment_link:      Stripe payment link URL
        client_address:    Client mailing address (optional)
        invoice_number:    Auto-generated if omitted
        invoice_date:      Defaults to today
        due_date:          Defaults to today + 14 days
        notes:             Optional notes

    Returns:
        output_path
    """
    today = date.today()

    if invoice_number is None:
        invoice_number = f"INV-{today.strftime('%Y-%m%d')}-001"
    if invoice_date is None:
        invoice_date = today.strftime("%B %-d, %Y")
    if due_date is None:
        due_date = (today + timedelta(days=14)).strftime("%B %-d, %Y")

    line_items = [
        {
            "description": f"{project_name} — {milestone_name}",
            "quantity": 1,
            "unit_price": milestone_amount,
            "amount": milestone_amount,
        }
    ]

    return generate_invoice(
        output_path=output_path,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        client_name=client_name,
        client_email=client_email,
        client_address=client_address or client_name,
        project_name=project_name,
        quote_ref=quote_ref,
        line_items=line_items,
        subtotal=milestone_amount,
        tax=0.0,
        total=milestone_amount,
        payment_link=payment_link,
        payment_methods="ACH Bank Transfer (preferred) | Credit Card",
        notes=notes,
    )


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    out = tempfile.mktemp(suffix=".pdf")
    generate_invoice(
        output_path=out,
        invoice_number="INV-2026-001",
        invoice_date="April 8, 2026",
        due_date="April 22, 2026",
        client_name="Topletz Family",
        client_email="topletz@example.com",
        client_address="84 Aspen Meadow Dr\nEdwards, CO 81632",
        project_name="Topletz Residence — 84 Aspen Meadow Dr",
        quote_ref="Q-212 V3",
        line_items=[
            {
                "description": "Smart Home Control System — Labor & Materials",
                "quantity": 1,
                "unit_price": 32124.97,
                "amount": 32124.97,
            },
            {
                "description": "Lutron Lighting Control Package",
                "quantity": 1,
                "unit_price": 6424.59,
                "amount": 6424.59,
            },
        ],
        subtotal=38549.56,
        tax=0.00,
        total=38549.56,
        payment_link="https://buy.stripe.com/test_abc123",
        payment_methods="ACH Bank Transfer (preferred) | Credit Card",
        notes="Questions? Call us at (970) 519-3013 or email info@symphonysh.com",
    )
    print(f"Test invoice written to: {out}")
