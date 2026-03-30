#!/usr/bin/env python3
"""Fetch recent emails that aren't Topletz — find new project leads."""
import imaplib, email, email.header, email.utils, os
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

SERVER = os.getenv("ZOHO_IMAP_SERVER", "imappro.zoho.com")
PORT = int(os.getenv("ZOHO_IMAP_PORT", "993"))
EMAIL_ADDR = os.getenv("SYMPHONY_EMAIL", "")
PASSWORD = os.getenv("SYMPHONY_EMAIL_PASSWORD", "")

def decode_hdr(value):
    if not value: return ""
    parts = email.header.decode_header(value)
    return " ".join(p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p for p, c in parts)

def get_text_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload: return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload: return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""

print(f"Connecting to {SERVER}:{PORT} as {EMAIL_ADDR}...")
mail = imaplib.IMAP4_SSL(SERVER, PORT)
mail.login(EMAIL_ADDR, PASSWORD)
mail.select("INBOX")

since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
print(f"Fetching emails since {since} (excluding Topletz/stopletz)...\n")

criteria = f'(SINCE {since})'
_, nums = mail.search(None, criteria)
if not nums[0]:
    print("No emails found.")
else:
    skip_terms = ["stopletz", "topletz", "aspen meadow", "d-tools cloud", "mailer-daemon", "noreply", "no-reply"]
    count = 0
    for n in nums[0].split():
        _, data = mail.fetch(n, "(RFC822)")
        if not data or not data[0]: continue
        msg = email.message_from_bytes(data[0][1])
        frm = decode_hdr(msg.get("From", ""))
        subj = decode_hdr(msg.get("Subject", ""))
        date = msg.get("Date", "")
        
        combined = f"{frm} {subj}".lower()
        if any(s in combined for s in skip_terms): continue
        
        body = get_text_body(msg)
        
        # Skip obvious automated/marketing
        if any(x in combined for x in ["unsubscribe", "newsletter", "marketing", "promo"]): continue
        
        count += 1
        print("=" * 70)
        print(f"DATE:    {date}")
        print(f"FROM:    {frm}")
        print(f"SUBJECT: {subj}")
        print("-" * 70)
        print(body[:1500] if body else "(no text body)")
        print()
    
    print(f"\nDone. Found {count} non-Topletz emails from last 7 days.")

mail.logout()
