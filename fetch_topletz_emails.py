#!/usr/bin/env python3
"""
Run on Bob: cd ~/AI-Server && python3 fetch_topletz_emails.py
Fetches all recent emails mentioning Topletz/Steve via IMAP.
"""
import imaplib
import email
import email.header
import email.utils
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

SERVER = os.getenv("ZOHO_IMAP_SERVER", "imappro.zoho.com")
PORT = int(os.getenv("ZOHO_IMAP_PORT", "993"))
EMAIL_ADDR = os.getenv("SYMPHONY_EMAIL", "")
PASSWORD = os.getenv("SYMPHONY_EMAIL_PASSWORD", "")


def decode_hdr(value):
    if not value:
        return ""
    parts = email.header.decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def get_text_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    cs = part.get_content_charset() or "utf-8"
                    return payload.decode(cs, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            cs = msg.get_content_charset() or "utf-8"
            return payload.decode(cs, errors="replace")
    return ""


print(f"Connecting to {SERVER}:{PORT} as {EMAIL_ADDR}...")
mail = imaplib.IMAP4_SSL(SERVER, PORT)
mail.login(EMAIL_ADDR, PASSWORD)
mail.select("INBOX")

since = (datetime.now() - timedelta(days=10)).strftime("%d-%b-%Y")
print(f"Searching emails since {since}...\n")

seen = set()
search_terms = ["stopletz", "topletz", "aspen meadow", "TV", "shade", "television"]

for term in search_terms:
    try:
        criteria = f'(SINCE {since} TEXT "{term}")'
        _, nums = mail.search(None, criteria)
        if not nums[0]:
            continue
        for n in nums[0].split():
            if n in seen:
                continue
            seen.add(n)
            _, data = mail.fetch(n, "(RFC822)")
            if not data or not data[0]:
                continue
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            subj = decode_hdr(msg.get("Subject", ""))
            frm = decode_hdr(msg.get("From", ""))
            to = decode_hdr(msg.get("To", ""))
            date = msg.get("Date", "")

            body = get_text_body(msg)

            print("=" * 80)
            print(f"DATE:    {date}")
            print(f"FROM:    {frm}")
            print(f"TO:      {to}")
            print(f"SUBJECT: {subj}")
            print("-" * 80)
            print(body[:3000] if body else "(no text body)")
            print()
    except Exception as e:
        print(f"Search for '{term}' failed: {e}")
        continue

mail.logout()
print(f"Done. Found {len(seen)} unique emails.")
