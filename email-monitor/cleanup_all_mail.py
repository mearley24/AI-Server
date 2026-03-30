#!/usr/bin/env python3
"""
One-time cleanup: scan ALL Zoho Mail folders and route emails
to the correct folders based on routing rules.

Run on Bob: cd ~/AI-Server && python3 email-monitor/cleanup_all_mail.py
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from router import route_all_folders

server = os.getenv("ZOHO_IMAP_SERVER", "imappro.zoho.com")
port = int(os.getenv("ZOHO_IMAP_PORT", "993"))
email = os.getenv("SYMPHONY_EMAIL", "")
password = os.getenv("SYMPHONY_EMAIL_PASSWORD", "")

if not email or not password:
    print("ERROR: SYMPHONY_EMAIL and SYMPHONY_EMAIL_PASSWORD must be set in .env")
    sys.exit(1)

print(f"Starting full mailbox cleanup for {email}...")
print("This will scan ALL folders and route emails to the new structure.")
print("Folders already in the new structure (Projects/, Bids/, Vendor/, etc.) will be skipped.\n")

moved = route_all_folders(server, port, email, password)
print(f"\nDone. Moved {moved} emails total.")
