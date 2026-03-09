#!/usr/bin/env python3
"""
client.py — Email client for Symphony

Connects to info@symphonysh.com via IMAP to read and analyze emails.
Supports both App Password (simple) and OAuth2 (Google Workspace).
"""

import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import json

# Load env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")


@dataclass
class EmailMessage:
    """Parsed email message."""
    uid: str
    subject: str
    sender: str
    sender_name: str = ""
    to: str = ""
    date: str = ""
    body_text: str = ""
    body_html: str = ""
    attachments: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    is_read: bool = False
    
    @property
    def preview(self) -> str:
        """First 200 chars of body."""
        text = self.body_text or ""
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:200] + "..." if len(text) > 200 else text


class EmailClient:
    """IMAP email client for Symphony (supports Zoho, Gmail, or any IMAP)."""
    
    def __init__(self):
        self.email_address = os.getenv("SYMPHONY_EMAIL", "info@symphonysh.com")
        self.password = os.getenv("SYMPHONY_EMAIL_PASSWORD", "")
        
        # Auto-detect provider from email domain
        if "zoho" in self.email_address.lower() or os.getenv("ZOHO_IMAP_SERVER"):
            # Zoho Mail settings
            self.imap_server = os.getenv("ZOHO_IMAP_SERVER", "imappro.zoho.com")
            self.imap_port = int(os.getenv("ZOHO_IMAP_PORT", "993"))
        elif "gmail" in self.email_address.lower():
            # Gmail settings
            self.imap_server = os.getenv("SYMPHONY_IMAP_SERVER", "imap.gmail.com")
            self.imap_port = int(os.getenv("SYMPHONY_IMAP_PORT", "993"))
        else:
            # Custom / self-hosted - default to Zoho for Symphony
            self.imap_server = os.getenv("SYMPHONY_IMAP_SERVER", "imappro.zoho.com")
            self.imap_port = int(os.getenv("SYMPHONY_IMAP_PORT", "993"))
        
        self.conn: Optional[imaplib.IMAP4_SSL] = None
    
    def connect(self) -> bool:
        """Connect to IMAP server."""
        if not self.password:
            print("❌ SYMPHONY_EMAIL_PASSWORD not set in .env")
            print("   For Gmail: Create App Password at https://myaccount.google.com/apppasswords")
            return False
        
        try:
            self.conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.conn.login(self.email_address, self.password)
            return True
        except imaplib.IMAP4.error as e:
            print(f"❌ IMAP login failed: {e}")
            return False
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from server."""
        if self.conn:
            try:
                self.conn.logout()
            except:
                pass
            self.conn = None
    
    def _decode_header(self, header: str) -> str:
        """Decode email header."""
        if not header:
            return ""
        decoded = decode_header(header)
        parts = []
        for content, encoding in decoded:
            if isinstance(content, bytes):
                parts.append(content.decode(encoding or 'utf-8', errors='replace'))
            else:
                parts.append(str(content))
        return ' '.join(parts)
    
    def _parse_email(self, uid: str, raw_email: bytes) -> EmailMessage:
        """Parse raw email into EmailMessage."""
        msg = email.message_from_bytes(raw_email)
        
        # Headers
        subject = self._decode_header(msg.get("Subject", ""))
        sender = msg.get("From", "")
        to = msg.get("To", "")
        date = msg.get("Date", "")
        
        # Extract sender name and email
        sender_match = re.match(r'"?([^"<]+)"?\s*<?([^>]*)>?', sender)
        if sender_match:
            sender_name = sender_match.group(1).strip()
            sender_email = sender_match.group(2).strip() or sender
        else:
            sender_name = ""
            sender_email = sender
        
        # Body
        body_text = ""
        body_html = ""
        attachments = []
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                
                if "attachment" in disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append(self._decode_header(filename))
                elif content_type == "text/plain":
                    try:
                        body_text = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except:
                        pass
                elif content_type == "text/html":
                    try:
                        body_html = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except:
                        pass
        else:
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True).decode('utf-8', errors='replace')
                if content_type == "text/html":
                    body_html = payload
                else:
                    body_text = payload
            except:
                pass
        
        # If no text but have HTML, strip HTML for text
        if not body_text and body_html:
            body_text = re.sub(r'<[^>]+>', ' ', body_html)
            body_text = re.sub(r'\s+', ' ', body_text).strip()
        
        return EmailMessage(
            uid=uid,
            subject=subject,
            sender=sender_email,
            sender_name=sender_name,
            to=to,
            date=date,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments
        )
    
    def list_folders(self) -> List[str]:
        """List all mail folders."""
        if not self.conn:
            return []
        
        status, folders = self.conn.list()
        if status != "OK":
            return []
        
        result = []
        for folder in folders:
            if isinstance(folder, bytes):
                # Parse folder name from IMAP response
                match = re.search(rb'"([^"]+)"$|(\S+)$', folder)
                if match:
                    name = (match.group(1) or match.group(2)).decode('utf-8', errors='replace')
                    result.append(name)
        return result
    
    def search(
        self, 
        folder: str = "INBOX",
        criteria: str = "ALL",
        since_days: int = None,
        from_addr: str = None,
        subject_contains: str = None,
        unread_only: bool = False,
        limit: int = 50
    ) -> List[EmailMessage]:
        """Search emails with criteria."""
        if not self.conn:
            return []
        
        # Select folder (Zoho folder names can include spaces/special chars)
        try:
            status, _ = self.conn.select(folder, readonly=True)
        except Exception:
            status = "BAD"
        if status != "OK":
            safe_folder = folder.replace("\\", "\\\\").replace('"', r'\"')
            try:
                status, _ = self.conn.select(f'"{safe_folder}"', readonly=True)
            except Exception:
                status = "BAD"
        if status != "OK":
            print(f"❌ Could not select folder: {folder}")
            return []
        
        # Build search criteria
        search_parts = []
        
        if unread_only:
            search_parts.append("UNSEEN")
        
        if since_days:
            since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
            search_parts.append(f'SINCE {since_date}')
        
        if from_addr:
            search_parts.append(f'FROM "{from_addr}"')
        
        if subject_contains:
            search_parts.append(f'SUBJECT "{subject_contains}"')
        
        if not search_parts:
            search_parts.append("ALL")
        
        search_str = " ".join(search_parts)
        
        # Search
        status, data = self.conn.search(None, search_str)
        if status != "OK":
            return []
        
        uids = data[0].split()
        
        # Limit and reverse (newest first)
        uids = uids[-limit:][::-1]
        
        # Fetch emails
        emails = []
        for uid in uids:
            status, data = self.conn.fetch(uid, "(RFC822)")
            if status == "OK" and data[0]:
                raw = data[0][1]
                emails.append(self._parse_email(uid.decode(), raw))
        
        return emails
    
    def get_email(self, uid: str, folder: str = "INBOX") -> Optional[EmailMessage]:
        """Get single email by UID."""
        if not self.conn:
            return None
        
        self.conn.select(folder, readonly=True)
        status, data = self.conn.fetch(uid.encode(), "(RFC822)")
        
        if status == "OK" and data[0]:
            return self._parse_email(uid, data[0][1])
        return None
    
    def search_building_connected(self, since_days: int = 30, limit: int = 20) -> List[EmailMessage]:
        """Search for BuildingConnected bid invitations."""
        emails = []
        
        # Search by common BuildingConnected sender patterns
        bc_senders = [
            "buildingconnected.com",
            "team@buildingconnected.com",
            "notifications@buildingconnected.com",
            "noreply@buildingconnected.com"
        ]
        
        for sender in bc_senders:
            found = self.search(
                folder="INBOX",
                from_addr=sender,
                since_days=since_days,
                limit=limit
            )
            emails.extend(found)
        
        # Also search by subject
        subject_searches = ["bid invitation", "invited to bid", "BuildingConnected"]
        for subj in subject_searches:
            found = self.search(
                folder="INBOX",
                subject_contains=subj,
                since_days=since_days,
                limit=limit
            )
            for e in found:
                if e.uid not in [x.uid for x in emails]:
                    emails.append(e)
        
        # Sort by date (newest first)
        return sorted(emails, key=lambda x: x.date, reverse=True)[:limit]
    
    def get_unread_count(self, folder: str = "INBOX") -> int:
        """Get count of unread emails."""
        if not self.conn:
            return 0
        
        status, _ = self.conn.select(folder, readonly=True)
        if status != "OK":
            return 0
        
        status, data = self.conn.search(None, "UNSEEN")
        if status == "OK":
            return len(data[0].split())
        return 0
    
    def get_inbox_summary(self, limit: int = 10) -> Dict:
        """Get inbox summary for quick view."""
        if not self.connect():
            return {"error": "Could not connect"}
        
        try:
            unread = self.get_unread_count()
            recent = self.search(folder="INBOX", since_days=7, limit=limit)
            
            return {
                "email": self.email_address,
                "unread": unread,
                "recent_count": len(recent),
                "recent": [
                    {
                        "uid": e.uid,
                        "subject": e.subject[:60],
                        "from": e.sender_name or e.sender,
                        "date": e.date,
                        "preview": e.preview[:100]
                    }
                    for e in recent
                ]
            }
        finally:
            self.disconnect()


def main():
    """Test email client."""
    client = EmailClient()
    
    print(f"📧 Connecting to {client.email_address}...")
    
    if not client.connect():
        return 1
    
    try:
        # List folders
        folders = client.list_folders()
        print(f"\n📁 Folders: {len(folders)}")
        for f in folders[:10]:
            print(f"   - {f}")
        
        # Unread count
        unread = client.get_unread_count()
        print(f"\n📬 Unread: {unread}")
        
        # Recent emails
        print("\n📨 Recent Emails (last 7 days):")
        recent = client.search(since_days=7, limit=10)
        for e in recent:
            print(f"   [{e.date[:16]}] {e.sender_name or e.sender[:30]}")
            print(f"      {e.subject[:60]}")
        
        # BuildingConnected search
        print("\n🏗️ BuildingConnected Emails:")
        bc_emails = client.search_building_connected(since_days=30)
        if bc_emails:
            for e in bc_emails[:5]:
                print(f"   [{e.date[:16]}] {e.subject[:60]}")
        else:
            print("   (none found)")
        
    finally:
        client.disconnect()
    
    return 0


if __name__ == "__main__":
    exit(main())
