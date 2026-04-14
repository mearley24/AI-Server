#!/usr/bin/env python3
"""
Symphony Markup App Server

Serves the iPad markup tool and handles export/import.

Usage:
    python3 server.py                              # Start on localhost:8088
    python3 server.py --host 127.0.0.1 --port 8088  # Custom bind/port

For HTTPS (Share → Save to Files on iPad): tailscale serve 8088, set MARKUP_HTTPS_URL in .env
"""

import argparse
import base64
import csv
import io
import json
import os
import secrets
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import socket
import mimetypes
from urllib.parse import parse_qs, urlsplit

# Load .env from AI-Server root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

BASE = Path(__file__).parent
WEB_DIR = BASE / "web"

# Save to iCloud so iPad can access, and also local for Bob
ICLOUD_EXPORTS = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Symphony SH" / "Markup_Exports"
LOCAL_EXPORTS = Path.home() / "AI-Server" / "knowledge" / "markup_exports"
ICLOUD_EXPORTS.mkdir(parents=True, exist_ok=True)
LOCAL_EXPORTS.mkdir(parents=True, exist_ok=True)
LOCAL_ACCESS_CONTROL_FILE = LOCAL_EXPORTS / ".access_control.json"
ICLOUD_ACCESS_CONTROL_FILE = ICLOUD_EXPORTS / ".access_control.json"
LOCAL_SESSION_FILE = LOCAL_EXPORTS / ".session_tracking.json"
ICLOUD_SESSION_FILE = ICLOUD_EXPORTS / ".session_tracking.json"
LOCAL_ORG_SYMBOLS_FILE = LOCAL_EXPORTS / ".org_symbols.json"
ICLOUD_ORG_SYMBOLS_FILE = ICLOUD_EXPORTS / ".org_symbols.json"


class MarkupHandler(BaseHTTPRequestHandler):
    """Custom handler for markup app."""

    ROLE_ORDER = {
        "viewer": 1,
        "editor": 2,
        "owner": 3,
    }

    @staticmethod
    def _truthy(value=None, default: bool = False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _is_local_client(self) -> bool:
        host = (self.client_address[0] if self.client_address else "") or ""
        if host in {"127.0.0.1", "::1"} or host.startswith("192.168.") or host.startswith("10."):
            return True
        if host.startswith("172."):
            try:
                second = int(host.split(".")[1])
                return 16 <= second <= 31
            except Exception:
                return False
        return False

    def _auth_config(self) -> dict:
        return {
            "required": self._truthy(os.environ.get("MARKUP_REQUIRE_AUTH"), default=False),
            "allow_local": self._truthy(os.environ.get("MARKUP_ALLOW_LOCAL"), default=True),
            "token": (os.environ.get("MARKUP_API_TOKEN") or "").strip(),
        }

    def _trusted_identity(self) -> str:
        return (
            self.headers.get("CF-Access-Authenticated-User-Email")
            or self.headers.get("X-Auth-Request-Email")
            or self.headers.get("X-Forwarded-Email")
            or ""
        ).strip()

    def _extract_bearer_token(self) -> str:
        auth = (self.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return ""

    def _is_authorized(self) -> bool:
        cfg = self._auth_config()
        if not cfg["required"]:
            return True
        if cfg["allow_local"] and self._is_local_client():
            return True
        if self._trusted_identity():
            return True
        expected = cfg["token"]
        if not expected:
            return False
        supplied = (self.headers.get("X-Markup-Token") or "").strip() or self._extract_bearer_token()
        return supplied == expected

    def _current_user(self) -> str:
        trusted = self._trusted_identity()
        if trusted:
            return trusted
        if self._is_local_client():
            return "local-user"
        host = (self.client_address[0] if self.client_address else "") or "remote"
        return f"trade-{host.replace(':', '_')}"

    def _send_json(self, status: int, payload: dict):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _deny_unauthorized(self):
        self._send_json(401, {"success": False, "error": "Unauthorized"})

    def _load_access_control(self) -> dict:
        for path in (LOCAL_ACCESS_CONTROL_FILE, ICLOUD_ACCESS_CONTROL_FILE):
            try:
                if path.exists():
                    data = json.loads(path.read_text())
                    if isinstance(data, dict):
                        data.setdefault("projects", {})
                        data.setdefault("invites", {})
                        return data
            except Exception:
                continue
        return {"projects": {}, "invites": {}}

    def _save_access_control(self, data: dict):
        payload = json.dumps(data, indent=2)
        LOCAL_ACCESS_CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_ACCESS_CONTROL_FILE.write_text(payload)
        try:
            ICLOUD_ACCESS_CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
            ICLOUD_ACCESS_CONTROL_FILE.write_text(payload)
        except Exception:
            pass

    def _get_project_acl(self, access: dict, project: str) -> dict:
        projects = access.setdefault("projects", {})
        acl = projects.setdefault(project, {"owner": "", "members": {}})
        acl.setdefault("owner", "")
        acl.setdefault("members", {})
        return acl

    def _role_for_user(self, access: dict, project: str, user: str) -> str:
        acl = access.get("projects", {}).get(project) or {}
        if not user:
            return ""
        if acl.get("owner") == user:
            return "owner"
        member = (acl.get("members") or {}).get(user) or {}
        role = str(member.get("role") or "").strip().lower()
        return role if role in self.ROLE_ORDER else ""

    def _can_access_project(self, access: dict, project: str, user: str, write: bool = False) -> bool:
        if not project:
            return False
        cfg = self._auth_config()
        if cfg["allow_local"] and self._is_local_client():
            return True
        role = self._role_for_user(access, project, user)
        if role == "owner":
            return True
        if role == "editor":
            return True
        if role == "viewer":
            return not write
        return False

    def _ensure_project_owner(self, access: dict, project: str, user: str):
        acl = self._get_project_acl(access, project)
        if not acl.get("owner") and user:
            acl["owner"] = user

    def _project_user_list(self, access: dict, user: str) -> list[dict]:
        rows = []
        for project, acl in (access.get("projects") or {}).items():
            role = self._role_for_user(access, project, user)
            if role:
                rows.append({"project": project, "role": role})
        rows.sort(key=lambda r: r["project"].lower())
        return rows

    def _rename_project_dirs(self, src: str, dst: str):
        for root in (LOCAL_EXPORTS, ICLOUD_EXPORTS):
            old_dir = root / src
            new_dir = root / dst
            if not old_dir.exists() or not old_dir.is_dir():
                continue
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            if new_dir.exists():
                # Merge files into destination when it already exists.
                for entry in old_dir.iterdir():
                    target = new_dir / entry.name
                    if target.exists():
                        # Preserve destination if conflict exists.
                        continue
                    entry.rename(target)
                try:
                    old_dir.rmdir()
                except Exception:
                    pass
            else:
                old_dir.rename(new_dir)

    def _resolve_base_url(self) -> str:
        configured = (os.environ.get("MARKUP_HTTPS_URL") or "").strip()
        if configured:
            return configured.rstrip("/")
        host = self.headers.get("Host") or "localhost:8091"
        scheme = "https" if (self.headers.get("X-Forwarded-Proto") == "https") else "http"
        return f"{scheme}://{host}".rstrip("/")

    def _create_invite(self, access: dict, project: str, role: str, created_by: str, expires_hours: int) -> dict:
        token = secrets.token_urlsafe(24)
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=max(1, min(expires_hours, 24 * 30)))
        invite = {
            "token": token,
            "project": project,
            "role": role,
            "createdBy": created_by,
            "createdAt": now.isoformat() + "Z",
            "expiresAt": expires_at.isoformat() + "Z",
            "revoked": False,
        }
        access.setdefault("invites", {})[token] = invite
        return invite

    @staticmethod
    def _invite_is_active(invite: dict) -> bool:
        if not invite or invite.get("revoked"):
            return False
        try:
            expires = str(invite.get("expiresAt", "")).replace("Z", "")
            return datetime.utcnow() <= datetime.fromisoformat(expires)
        except Exception:
            return False

    def _summarize_payload(self, data: dict) -> dict:
        pages = data.get("pages") or {}
        if not isinstance(pages, dict):
            return {}
        symbol_count = 0
        note_count = 0
        room_count = 0
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            symbol_count += len(page.get("placed") or [])
            note_count += len(page.get("markupNotes") or [])
            room_count += len(page.get("rooms") or [])
        return {
            "pages": len(pages),
            "symbols": symbol_count,
            "rooms": room_count,
            "notes": note_count,
        }

    def _append_audit(self, project: str, event: dict):
        line = json.dumps(event, separators=(",", ":")) + "\n"
        local_path = LOCAL_EXPORTS / project / ".audit.jsonl"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "a") as f:
            f.write(line)
        try:
            icloud_path = ICLOUD_EXPORTS / project / ".audit.jsonl"
            icloud_path.parent.mkdir(parents=True, exist_ok=True)
            with open(icloud_path, "a") as f:
                f.write(line)
        except Exception:
            pass

    def _read_audit(self, project: str, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit or 100), 1000))
        for root in (LOCAL_EXPORTS, ICLOUD_EXPORTS):
            path = root / project / ".audit.jsonl"
            if not path.exists():
                continue
            try:
                lines = path.read_text().splitlines()
                events = []
                for line in lines[-limit:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.append(event)
                    except Exception:
                        continue
                return list(reversed(events))
            except Exception:
                continue
        return []

    def _session_idle_seconds(self) -> int:
        try:
            value = int(os.environ.get("MARKUP_SESSION_IDLE_SECONDS", "900"))
            return max(60, min(value, 24 * 3600))
        except Exception:
            return 900

    def _load_session_db(self) -> dict:
        for path in (LOCAL_SESSION_FILE, ICLOUD_SESSION_FILE):
            try:
                if path.exists():
                    data = json.loads(path.read_text())
                    if isinstance(data, dict):
                        data.setdefault("users", {})
                        return data
            except Exception:
                continue
        return {"users": {}}

    def _save_session_db(self, db: dict):
        payload = json.dumps(db, indent=2)
        LOCAL_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_SESSION_FILE.write_text(payload)
        try:
            ICLOUD_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            ICLOUD_SESSION_FILE.write_text(payload)
        except Exception:
            pass

    def _track_session_ping(self, user: str, project: str = "") -> dict:
        db = self._load_session_db()
        users = db.setdefault("users", {})
        now = datetime.utcnow()
        now_iso = now.isoformat() + "Z"
        idle_seconds = self._session_idle_seconds()
        row = users.setdefault(user, {
            "totalSeconds": 0.0,
            "projectSeconds": {},
            "current": {},
            "sessions": [],
            "lastSeenAt": "",
        })
        row.setdefault("totalSeconds", 0.0)
        row.setdefault("projectSeconds", {})
        row.setdefault("current", {})
        row.setdefault("sessions", [])
        row.setdefault("lastSeenAt", "")

        current = row.get("current") or {}
        last_seen_iso = str(current.get("lastSeenAt") or "")
        prev_project = str(current.get("project") or "")

        # Parse last seen
        last_seen_dt = None
        if last_seen_iso:
            try:
                last_seen_dt = datetime.fromisoformat(last_seen_iso.replace("Z", ""))
            except Exception:
                last_seen_dt = None

        started_new = False
        if not current.get("startedAt") or not last_seen_dt:
            current = {"startedAt": now_iso, "lastSeenAt": now_iso, "project": project or prev_project}
            started_new = True
        else:
            gap = (now - last_seen_dt).total_seconds()
            if gap > idle_seconds:
                # Close stale session
                started_at = str(current.get("startedAt") or last_seen_iso)
                duration = max(0.0, (last_seen_dt - datetime.fromisoformat(started_at.replace("Z", ""))).total_seconds())
                row["sessions"].append({
                    "startedAt": started_at,
                    "endedAt": last_seen_iso,
                    "durationSeconds": round(duration, 2),
                    "project": prev_project,
                })
                current = {"startedAt": now_iso, "lastSeenAt": now_iso, "project": project or prev_project}
                started_new = True
            else:
                delta = max(0.0, min(gap, idle_seconds))
                row["totalSeconds"] = float(row.get("totalSeconds", 0.0)) + delta
                bill_project = prev_project or project
                if bill_project:
                    proj = row["projectSeconds"]
                    proj[bill_project] = float(proj.get(bill_project, 0.0)) + delta
                if project:
                    current["project"] = project
                current["lastSeenAt"] = now_iso

        row["current"] = current
        row["lastSeenAt"] = now_iso
        users[user] = row
        self._save_session_db(db)

        current_started = str(current.get("startedAt") or now_iso)
        try:
            current_seconds = max(0.0, (now - datetime.fromisoformat(current_started.replace("Z", ""))).total_seconds())
        except Exception:
            current_seconds = 0.0
        return {
            "startedNewSession": started_new,
            "user": user,
            "project": str(current.get("project") or ""),
            "totalSeconds": round(float(row.get("totalSeconds", 0.0)), 2),
            "currentSessionSeconds": round(current_seconds, 2),
        }

    def _project_time_summary(self, project: str) -> dict:
        return {row["user"]: row["seconds"] for row in self._project_time_rows(project)}

    def _project_time_rows(self, project: str) -> list[dict]:
        db = self._load_session_db()
        rows = []
        now = datetime.utcnow()
        idle_seconds = self._session_idle_seconds()
        for user, row in (db.get("users") or {}).items():
            seconds = float((row.get("projectSeconds") or {}).get(project, 0.0))
            first_seen = ""
            last_seen = ""
            for session in (row.get("sessions") or []):
                if str((session or {}).get("project") or "") != project:
                    continue
                started = str((session or {}).get("startedAt") or "")
                ended = str((session or {}).get("endedAt") or "")
                if started and (not first_seen or started < first_seen):
                    first_seen = started
                if ended and (not last_seen or ended > last_seen):
                    last_seen = ended
            current = row.get("current") or {}
            if str(current.get("project") or "") == project:
                cur_started = str(current.get("startedAt") or "")
                cur_last = str(current.get("lastSeenAt") or "")
                if cur_started and (not first_seen or cur_started < first_seen):
                    first_seen = cur_started
                if cur_last and (not last_seen or cur_last > last_seen):
                    last_seen = cur_last
                if cur_last and cur_started:
                    try:
                        last_dt = datetime.fromisoformat(cur_last.replace("Z", ""))
                        start_dt = datetime.fromisoformat(cur_started.replace("Z", ""))
                        gap = (now - last_dt).total_seconds()
                        if gap <= idle_seconds:
                            seconds += max(0.0, (now - max(last_dt, start_dt)).total_seconds())
                    except Exception:
                        pass
            if seconds > 0:
                rows.append({
                    "user": user,
                    "seconds": round(seconds, 2),
                    "firstSeenAt": first_seen or str(row.get("lastSeenAt") or ""),
                    "lastSeenAt": last_seen or str(row.get("lastSeenAt") or ""),
                })
        rows.sort(key=lambda r: (-float(r.get("seconds", 0.0)), str(r.get("user", "")).lower()))
        return rows

    @staticmethod
    def _sanitize_symbol_definitions(raw: dict) -> dict:
        if not isinstance(raw, dict):
            return {}
        safe = {}
        for key, value in raw.items():
            symbol_id = str(key or "").strip().lower().replace(" ", "-")
            if not symbol_id or not isinstance(value, dict):
                continue
            safe[symbol_id] = {
                "label": str(value.get("label") or ""),
                "category": str(value.get("category") or "custom"),
                "shape": str(value.get("shape") or "roundrect"),
                "color": str(value.get("color") or "#3B82F6"),
                "sku": str(value.get("sku") or ""),
            }
        return safe

    def _symbols_storage_targets(self, project: str = "") -> dict:
        project = self._slugify_name(project or "") if project else ""
        if project:
            local_current = LOCAL_EXPORTS / project / ".symbols.json"
            icloud_current = ICLOUD_EXPORTS / project / ".symbols.json"
            local_history = LOCAL_EXPORTS / project / "symbols_history"
            icloud_history = ICLOUD_EXPORTS / project / "symbols_history"
            scope = "project"
        else:
            local_current = LOCAL_ORG_SYMBOLS_FILE
            icloud_current = ICLOUD_ORG_SYMBOLS_FILE
            local_history = LOCAL_EXPORTS / "symbols_history"
            icloud_history = ICLOUD_EXPORTS / "symbols_history"
            scope = "organization"
        return {
            "project": project,
            "scope": scope,
            "local_current": local_current,
            "icloud_current": icloud_current,
            "local_history": local_history,
            "icloud_history": icloud_history,
        }

    def _load_symbols_bundle(self, project: str = "") -> dict:
        targets = self._symbols_storage_targets(project)
        for path in (targets["local_current"], targets["icloud_current"]):
            try:
                if not path.exists():
                    continue
                payload = json.loads(path.read_text())
                if isinstance(payload, dict):
                    symbols = self._sanitize_symbol_definitions(payload.get("symbols") or {})
                    return {
                        "project": targets["project"],
                        "scope": targets["scope"],
                        "symbols": symbols,
                        "updatedAt": str(payload.get("updatedAt") or ""),
                        "updatedBy": str(payload.get("updatedBy") or ""),
                        "source": str(payload.get("source") or ""),
                    }
            except Exception:
                continue
        return {
            "project": targets["project"],
            "scope": targets["scope"],
            "symbols": {},
            "updatedAt": "",
            "updatedBy": "",
            "source": "",
        }

    def _list_symbol_backups(self, project: str = "", limit: int = 50) -> list[dict]:
        targets = self._symbols_storage_targets(project)
        rows = {}
        max_rows = max(1, min(int(limit or 50), 500))
        for source, folder in (("local", targets["local_history"]), ("icloud", targets["icloud_history"])):
            if not folder.exists() or not folder.is_dir():
                continue
            try:
                for entry in folder.iterdir():
                    if not entry.is_file() or entry.suffix.lower() != ".json":
                        continue
                    key = entry.name
                    row = rows.get(key) or {"filename": entry.name, "createdAt": "", "sources": []}
                    try:
                        st = entry.stat()
                        created = datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z"
                        if not row["createdAt"] or created > row["createdAt"]:
                            row["createdAt"] = created
                    except Exception:
                        pass
                    if source not in row["sources"]:
                        row["sources"].append(source)
                    rows[key] = row
            except Exception:
                continue
        out = sorted(rows.values(), key=lambda r: (r.get("createdAt") or "", r.get("filename") or ""), reverse=True)
        return out[:max_rows]

    def _save_symbols_bundle(self, project: str, symbols: dict, user: str, source: str = "manual", create_backup: bool = True) -> dict:
        targets = self._symbols_storage_targets(project)
        now_iso = datetime.utcnow().isoformat() + "Z"
        safe_symbols = self._sanitize_symbol_definitions(symbols)
        payload = {
            "version": 1,
            "scope": targets["scope"],
            "project": targets["project"],
            "updatedAt": now_iso,
            "updatedBy": user,
            "source": source,
            "symbols": safe_symbols,
        }
        serialized = json.dumps(payload, indent=2)
        targets["local_current"].parent.mkdir(parents=True, exist_ok=True)
        targets["local_current"].write_text(serialized)
        try:
            targets["icloud_current"].parent.mkdir(parents=True, exist_ok=True)
            targets["icloud_current"].write_text(serialized)
        except Exception:
            pass
        backup_name = ""
        if create_backup:
            backup_name = f"symbols_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            for history_dir in (targets["local_history"], targets["icloud_history"]):
                try:
                    history_dir.mkdir(parents=True, exist_ok=True)
                    (history_dir / backup_name).write_text(serialized)
                except Exception:
                    continue
        payload["backupFilename"] = backup_name
        return payload

    def _restore_latest_symbols(self, project: str, user: str) -> dict | None:
        targets = self._symbols_storage_targets(project)
        candidates: list[tuple[datetime, Path]] = []
        for folder in (targets["local_history"], targets["icloud_history"]):
            if not folder.exists() or not folder.is_dir():
                continue
            try:
                for entry in folder.iterdir():
                    if not entry.is_file() or entry.suffix.lower() != ".json":
                        continue
                    try:
                        mtime = datetime.utcfromtimestamp(entry.stat().st_mtime)
                    except Exception:
                        mtime = datetime.utcnow()
                    candidates.append((mtime, entry))
            except Exception:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        for _, path in candidates:
            try:
                payload = json.loads(path.read_text())
                symbols = self._sanitize_symbol_definitions(payload.get("symbols") or {})
                if not symbols:
                    continue
                restored = self._save_symbols_bundle(project, symbols, user=user, source="restore_latest", create_backup=False)
                restored["restoredFrom"] = path.name
                return restored
            except Exception:
                continue
        return None

    @staticmethod
    def _slugify_name(value: str) -> str:
        """Normalize project/file names for safe filesystem paths."""
        cleaned = (value or "untitled").strip().replace(" ", "_").replace("/", "-")
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in ("-", "_", "."))
        return cleaned or "untitled"

    def _resolve_save_target(self, data: dict) -> tuple[str, str]:
        """
        Resolve (project_folder, filename) for save operations.

        Supports:
        - savePath: "Project/file.symphony" for overwriting canonical project file
        - default behavior: timestamped snapshot in project folder
        """
        project = self._slugify_name(data.get('project') or data.get('projectName') or 'untitled')
        save_path = str(data.get('savePath') or '').strip()
        if save_path:
            raw = Path(save_path.replace("\\", "/"))
            parts = [self._slugify_name(p) for p in raw.parts if p not in ("", ".", "..")]
            if parts:
                if len(parts) == 1:
                    filename = parts[0]
                    if "." not in filename:
                        filename = f"{filename}.symphony"
                    return project, filename
                folder = parts[0] or project
                filename = parts[-1]
                if "." not in filename:
                    filename = f"{filename}.symphony"
                return folder, filename

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{project}_{timestamp}.symphony"
        return project, filename

    @staticmethod
    def _has_embedded_source_pdf(data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        source_obj = data.get("sourcePdf")
        if isinstance(source_obj, dict) and (source_obj.get("bytes_b64") or source_obj.get("bytes_arr")):
            return True
        for key in ("source_pdf_b64", "sourcePdfB64", "sourcePdfBytesB64", "pdf_b64", "pdfBase64"):
            if data.get(key):
                return True
        return False

    def _preserve_existing_source_pdf(self, data: dict, existing_paths: list[Path]) -> dict:
        if self._has_embedded_source_pdf(data):
            return data
        for path in existing_paths:
            try:
                if not path.exists() or not path.is_file():
                    continue
                existing = json.loads(path.read_text())
                if not isinstance(existing, dict):
                    continue
                if self._has_embedded_source_pdf(existing):
                    # Preserve embedded source PDF from existing project file during lightweight autosaves.
                    if isinstance(existing.get("sourcePdf"), dict):
                        data["sourcePdf"] = existing["sourcePdf"]
                    for key in ("source_pdf_b64", "sourcePdfB64", "sourcePdfBytesB64", "pdf_b64", "pdfBase64"):
                        if existing.get(key) and not data.get(key):
                            data[key] = existing[key]
                    return data
            except Exception:
                continue
        return data

    def _list_project_folders(self, query: str = "", limit: int = 200) -> list[str]:
        """List known project folders from iCloud/local export roots."""
        folders = set()
        user = self._current_user()
        access = self._load_access_control()
        for root in (ICLOUD_EXPORTS, LOCAL_EXPORTS):
            if not root.exists():
                continue
            try:
                for entry in root.iterdir():
                    if entry.is_dir() and not entry.name.startswith("."):
                        folders.add(entry.name)
            except PermissionError:
                # Some iCloud roots may be unavailable to this process; ignore them.
                continue
            except OSError:
                continue

        names = sorted(folders, key=lambda s: s.lower())
        q = (query or "").strip().lower()
        if q:
            tokens = [t for t in q.replace("_", " ").replace("-", " ").split() if t]
            filtered: list[str] = []
            for name in names:
                lower = name.lower()
                if q in lower or all(t in lower for t in tokens):
                    filtered.append(name)
            names = filtered
        visible = []
        for name in names:
            if self._can_access_project(access, name, user, write=False):
                visible.append(name)
        return visible[: max(1, min(limit, 1000))]

    def _list_project_files(self, project: str, limit: int = 200) -> list[dict]:
        """List .symphony files for a project (prefer local metadata, mirror path included)."""
        safe_project = self._slugify_name(project or "")
        if not safe_project:
            return []
        user = self._current_user()
        access = self._load_access_control()
        if not self._can_access_project(access, safe_project, user, write=False):
            return []

        files = {}
        roots = [
            ("local", LOCAL_EXPORTS / safe_project),
            ("icloud", ICLOUD_EXPORTS / safe_project),
        ]
        for source, folder in roots:
            if not folder.exists() or not folder.is_dir():
                continue
            try:
                for entry in folder.iterdir():
                    if not entry.is_file():
                        continue
                    if entry.name.startswith("."):
                        continue
                    if entry.suffix.lower() not in {".symphony", ".json"}:
                        continue
                    key = entry.name.lower()
                    row = files.get(key) or {
                        "filename": entry.name,
                        "savePath": f"{safe_project}/{entry.name}",
                        "sizeBytes": 0,
                        "modifiedAt": "",
                        "sources": [],
                    }
                    try:
                        st = entry.stat()
                        row["sizeBytes"] = max(int(row.get("sizeBytes") or 0), int(st.st_size))
                        modified = datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z"
                        if not row["modifiedAt"] or modified > row["modifiedAt"]:
                            row["modifiedAt"] = modified
                    except Exception:
                        pass
                    if source not in row["sources"]:
                        row["sources"].append(source)
                    files[key] = row
            except PermissionError:
                continue
            except Exception:
                continue

        rows = sorted(files.values(), key=lambda r: (r.get("modifiedAt") or "", r.get("filename") or ""), reverse=True)
        return rows[: max(1, min(int(limit or 200), 1000))]
    
    def do_GET(self):
        """Serve static files and /api/config."""
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)

        if path == '/api/config':
            https_url = os.environ.get("MARKUP_HTTPS_URL", "").strip()
            auth = self._auth_config()
            self._send_json(200, {
                "httpsUrl": https_url or None,
                "authRequired": auth["required"],
                "allowLocal": auth["allow_local"],
            })
            return

        if path == '/api/whoami':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            self._send_json(200, {
                "success": True,
                "user": self._current_user(),
                "local": self._is_local_client(),
            })
            return

        if path == '/api/projects':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            user = self._current_user()
            access = self._load_access_control()
            self._send_json(200, {
                "success": True,
                "user": user,
                "projects": self._project_user_list(access, user),
            })
            return

        if path == '/api/projects/access':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            project = self._slugify_name((query.get("project", [""])[0] or "").strip())
            if not project:
                self._send_json(400, {"success": False, "error": "Project required"})
                return
            user = self._current_user()
            access = self._load_access_control()
            if not self._can_access_project(access, project, user, write=False):
                self._send_json(403, {"success": False, "error": "No access to project"})
                return
            acl = self._get_project_acl(access, project)
            invites = []
            for token, invite in (access.get("invites") or {}).items():
                if (invite or {}).get("project") != project:
                    continue
                invites.append({
                    "token": token,
                    "role": invite.get("role"),
                    "createdBy": invite.get("createdBy"),
                    "createdAt": invite.get("createdAt"),
                    "expiresAt": invite.get("expiresAt"),
                    "active": self._invite_is_active(invite),
                    "revoked": bool(invite.get("revoked")),
                })
            invites.sort(key=lambda i: i.get("createdAt", ""), reverse=True)
            self._send_json(200, {
                "success": True,
                "project": project,
                "owner": acl.get("owner"),
                "members": acl.get("members") or {},
                "timeByUserSeconds": self._project_time_summary(project),
                "invites": invites[:100],
            })
            return

        if path == '/api/projects/time':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            project = self._slugify_name((query.get("project", [""])[0] or "").strip())
            if not project:
                self._send_json(400, {"success": False, "error": "Project required"})
                return
            user = self._current_user()
            access = self._load_access_control()
            if not self._can_access_project(access, project, user, write=False):
                self._send_json(403, {"success": False, "error": "No access to project"})
                return
            self._send_json(200, {
                "success": True,
                "project": project,
                "timeByUserSeconds": self._project_time_summary(project),
            })
            return

        if path == '/api/projects/time/export':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            project = self._slugify_name((query.get("project", [""])[0] or "").strip())
            if not project:
                self._send_json(400, {"success": False, "error": "Project required"})
                return
            user = self._current_user()
            access = self._load_access_control()
            if not self._can_access_project(access, project, user, write=False):
                self._send_json(403, {"success": False, "error": "No access to project"})
                return
            rows = self._project_time_rows(project)
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["project", "user", "seconds", "hours", "first_seen_at", "last_seen_at"])
            for row in rows:
                seconds = float(row.get("seconds") or 0.0)
                writer.writerow([
                    project,
                    row.get("user") or "",
                    f"{seconds:.2f}",
                    f"{seconds / 3600.0:.4f}",
                    row.get("firstSeenAt") or "",
                    row.get("lastSeenAt") or "",
                ])
            content = buffer.getvalue().encode("utf-8")
            filename = f"{project}_time_report.csv"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
            return

        if path == '/api/symbols':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            project = self._slugify_name((query.get("project", [""])[0] or "").strip()) if (query.get("project", [""])[0] or "").strip() else ""
            user = self._current_user()
            access = self._load_access_control()
            if project and not self._can_access_project(access, project, user, write=False):
                self._send_json(403, {"success": False, "error": "No access to project"})
                return
            try:
                limit = int((query.get("backupLimit", ["25"])[0] or "25").strip())
            except Exception:
                limit = 25
            bundle = self._load_symbols_bundle(project)
            backups = self._list_symbol_backups(project, limit=limit)
            self._send_json(200, {
                "success": True,
                "project": project,
                "scope": bundle.get("scope"),
                "symbols": bundle.get("symbols") or {},
                "updatedAt": bundle.get("updatedAt") or "",
                "updatedBy": bundle.get("updatedBy") or "",
                "source": bundle.get("source") or "",
                "backupCount": len(backups),
                "backups": backups,
            })
            return

        if path == '/api/projects/audit':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            project = self._slugify_name((query.get("project", [""])[0] or "").strip())
            if not project:
                self._send_json(400, {"success": False, "error": "Project required"})
                return
            user = self._current_user()
            access = self._load_access_control()
            if not self._can_access_project(access, project, user, write=False):
                self._send_json(403, {"success": False, "error": "No access to project"})
                return
            try:
                limit = int((query.get("limit", ["100"])[0] or "100").strip())
            except Exception:
                limit = 100
            events = self._read_audit(project, limit=limit)
            self._send_json(200, {
                "success": True,
                "project": project,
                "count": len(events),
                "events": events,
            })
            return

        if path.startswith('/api/invites/'):
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            token = path.split('/api/invites/', 1)[1].strip()
            access = self._load_access_control()
            invite = (access.get("invites") or {}).get(token)
            if not self._invite_is_active(invite):
                self._send_json(404, {"success": False, "error": "Invite not found or expired"})
                return
            self._send_json(200, {
                "success": True,
                "invite": {
                    "project": invite.get("project"),
                    "role": invite.get("role"),
                    "expiresAt": invite.get("expiresAt"),
                }
            })
            return

        if path == '/api/folders':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            q = (query.get("query", [""])[0] or "").strip()
            try:
                limit = int(query.get("limit", ["200"])[0])
            except (TypeError, ValueError):
                limit = 200
            folders = self._list_project_folders(query=q, limit=limit)
            self._send_json(200, {
                "success": True,
                "query": q,
                "count": len(folders),
                "folders": folders,
            })
            return

        if path == '/api/project-files':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            project = self._slugify_name((query.get("project", [""])[0] or "").strip())
            if not project:
                self._send_json(400, {"success": False, "error": "Project required"})
                return
            try:
                limit = int(query.get("limit", ["200"])[0])
            except (TypeError, ValueError):
                limit = 200
            files = self._list_project_files(project=project, limit=limit)
            self._send_json(200, {
                "success": True,
                "project": project,
                "count": len(files),
                "files": files,
            })
            return

        if path == '/' or path == '':
            path = '/index.html'

        filepath = WEB_DIR / path.lstrip('/')
        
        if filepath.exists() and filepath.is_file():
            content_type, _ = mimetypes.guess_type(str(filepath))
            if content_type is None:
                content_type = 'application/octet-stream'
            
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            # Avoid stale PWA UI after deploys (especially index + service worker).
            rel = filepath.relative_to(WEB_DIR).as_posix()
            if rel in {"index.html", "sw.js"}:
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
            self.end_headers()
            
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>404 Not Found</h1>')
    
    def do_POST(self):
        """Handle POST requests for saving markups."""
        path = urlsplit(self.path).path
        if path == '/api/save':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data)
                project, filename = self._resolve_save_target(data)
                user = self._current_user()
                access = self._load_access_control()
                # Bootstrap owner only for local user or first authenticated user writing.
                self._ensure_project_owner(access, project, user)
                if not self._can_access_project(access, project, user, write=True):
                    self._send_json(403, {"success": False, "error": "No write access to project"})
                    return
                self._save_access_control(access)
                
                # Save to project subfolder (so files are organized by project)
                icloud_dir = ICLOUD_EXPORTS / project
                local_dir = LOCAL_EXPORTS / project
                icloud_dir.mkdir(parents=True, exist_ok=True)
                local_dir.mkdir(parents=True, exist_ok=True)
                icloud_path = icloud_dir / filename
                local_path = local_dir / filename
                data = self._preserve_existing_source_pdf(data, [local_path, icloud_path])
                
                with open(icloud_path, 'w') as f:
                    json.dump(data, f, indent=2)
                with open(local_path, 'w') as f:
                    json.dump(data, f, indent=2)
                
                rel_path = f"{project}/{filename}"
                self._send_json(200, {
                    'success': True,
                    'filename': rel_path,
                    'savePath': rel_path,
                    'icloud': str(icloud_path),
                    'local': str(local_path),
                    'user': user,
                })
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "save",
                    "project": project,
                    "path": rel_path,
                    "user": user,
                    "summary": self._summarize_payload(data),
                })
                
            except Exception as e:
                self._send_json(500, {'error': str(e)})
        elif path == '/api/projects/invite':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                raw_project = str(payload.get("project") or "").strip()
                if not raw_project:
                    self._send_json(400, {"success": False, "error": "Project required"})
                    return
                project = self._slugify_name(raw_project)
                role = str(payload.get("role") or "editor").strip().lower()
                if role not in {"viewer", "editor"}:
                    role = "editor"
                expires_hours = int(payload.get("expiresHours") or 24 * 7)
                user = self._current_user()
                access = self._load_access_control()
                self._ensure_project_owner(access, project, user)
                requester_role = self._role_for_user(access, project, user)
                if requester_role != "owner" and not (self._auth_config()["allow_local"] and self._is_local_client()):
                    self._send_json(403, {"success": False, "error": "Only project owner can create invites"})
                    return
                invite = self._create_invite(access, project, role, user, expires_hours)
                self._save_access_control(access)
                base_url = self._resolve_base_url()
                invite_url = f"{base_url}/?invite={invite['token']}"
                self._send_json(200, {
                    "success": True,
                    "invite": invite,
                    "inviteUrl": invite_url,
                })
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "invite_created",
                    "project": project,
                    "user": user,
                    "role": role,
                    "inviteToken": invite["token"],
                    "expiresAt": invite["expiresAt"],
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/projects/create':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                raw_project = str(payload.get("project") or "").strip()
                if not raw_project:
                    self._send_json(400, {"success": False, "error": "Project required"})
                    return
                project = self._slugify_name(raw_project)
                access = self._load_access_control()
                user = self._current_user()
                acl = self._get_project_acl(access, project)
                self._ensure_project_owner(access, project, user)
                # If project already has an owner, require owner role (unless local override).
                if acl.get("owner") and acl.get("owner") != user and not (self._auth_config()["allow_local"] and self._is_local_client()):
                    self._send_json(403, {"success": False, "error": "Only owner can manage this project"})
                    return
                # Ensure directories exist.
                (LOCAL_EXPORTS / project).mkdir(parents=True, exist_ok=True)
                try:
                    (ICLOUD_EXPORTS / project).mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                self._save_access_control(access)
                self._send_json(200, {
                    "success": True,
                    "project": project,
                    "owner": self._get_project_acl(access, project).get("owner"),
                })
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "project_created",
                    "project": project,
                    "user": user,
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/projects/rename':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                src = self._slugify_name(str(payload.get("fromProject") or "").strip())
                dst = self._slugify_name(str(payload.get("toProject") or "").strip())
                if not src or not dst:
                    self._send_json(400, {"success": False, "error": "fromProject and toProject required"})
                    return
                if src == dst:
                    self._send_json(200, {"success": True, "project": dst, "renamed": False})
                    return
                access = self._load_access_control()
                user = self._current_user()
                actor_role = self._role_for_user(access, src, user)
                if actor_role != "owner" and not (self._auth_config()["allow_local"] and self._is_local_client()):
                    self._send_json(403, {"success": False, "error": "Only owner can rename project"})
                    return
                src_acl = (access.get("projects") or {}).get(src)
                if not src_acl:
                    self._send_json(404, {"success": False, "error": "Source project not found"})
                    return
                projects = access.setdefault("projects", {})
                if dst in projects and dst != src:
                    self._send_json(409, {"success": False, "error": "Destination project already exists"})
                    return
                projects[dst] = src_acl
                projects.pop(src, None)
                # Move invites bound to source project.
                for invite in (access.get("invites") or {}).values():
                    if (invite or {}).get("project") == src:
                        invite["project"] = dst
                self._save_access_control(access)
                self._rename_project_dirs(src, dst)
                self._send_json(200, {"success": True, "fromProject": src, "project": dst, "renamed": True})
                self._append_audit(dst, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "project_renamed",
                    "project": dst,
                    "fromProject": src,
                    "user": user,
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/invites/accept':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                token = str(payload.get("token") or "").strip()
                if not token:
                    self._send_json(400, {"success": False, "error": "Invite token required"})
                    return
                access = self._load_access_control()
                invite = (access.get("invites") or {}).get(token)
                if not self._invite_is_active(invite):
                    self._send_json(404, {"success": False, "error": "Invite not found or expired"})
                    return
                project = self._slugify_name(invite.get("project") or "")
                role = str(invite.get("role") or "viewer").strip().lower()
                if role not in {"viewer", "editor"}:
                    role = "viewer"
                user = self._current_user()
                acl = self._get_project_acl(access, project)
                if acl.get("owner") != user:
                    acl["members"][user] = {
                        "role": role,
                        "addedAt": datetime.utcnow().isoformat() + "Z",
                        "addedByInvite": token,
                    }
                self._save_access_control(access)
                self._send_json(200, {
                    "success": True,
                    "project": project,
                    "role": role,
                    "user": user,
                })
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "invite_accepted",
                    "project": project,
                    "user": user,
                    "role": role,
                    "inviteToken": token,
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/projects/member':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                project = self._slugify_name(str(payload.get("project") or "").strip())
                member = str(payload.get("member") or "").strip().lower()
                role = str(payload.get("role") or "").strip().lower()
                if not project or not member:
                    self._send_json(400, {"success": False, "error": "Project and member required"})
                    return
                if role not in {"viewer", "editor"}:
                    self._send_json(400, {"success": False, "error": "Role must be viewer or editor"})
                    return
                access = self._load_access_control()
                actor = self._current_user()
                acl = self._get_project_acl(access, project)
                actor_role = self._role_for_user(access, project, actor)
                if actor_role != "owner" and not (self._auth_config()["allow_local"] and self._is_local_client()):
                    self._send_json(403, {"success": False, "error": "Only owner can update members"})
                    return
                if acl.get("owner") == member:
                    self._send_json(400, {"success": False, "error": "Cannot change owner role"})
                    return
                acl["members"][member] = {
                    "role": role,
                    "addedAt": datetime.utcnow().isoformat() + "Z",
                    "addedBy": actor,
                }
                self._save_access_control(access)
                self._send_json(200, {"success": True, "project": project, "member": member, "role": role})
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "member_role_updated",
                    "project": project,
                    "user": actor,
                    "member": member,
                    "role": role,
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/projects/member/remove':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                project = self._slugify_name(str(payload.get("project") or "").strip())
                member = str(payload.get("member") or "").strip().lower()
                if not project or not member:
                    self._send_json(400, {"success": False, "error": "Project and member required"})
                    return
                access = self._load_access_control()
                actor = self._current_user()
                acl = self._get_project_acl(access, project)
                actor_role = self._role_for_user(access, project, actor)
                if actor_role != "owner" and not (self._auth_config()["allow_local"] and self._is_local_client()):
                    self._send_json(403, {"success": False, "error": "Only owner can remove members"})
                    return
                if acl.get("owner") == member:
                    self._send_json(400, {"success": False, "error": "Cannot remove owner"})
                    return
                acl.get("members", {}).pop(member, None)
                self._save_access_control(access)
                self._send_json(200, {"success": True, "project": project, "member": member, "removed": True})
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "member_removed",
                    "project": project,
                    "user": actor,
                    "member": member,
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/projects/invite/revoke':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                token = str(payload.get("token") or "").strip()
                if not token:
                    self._send_json(400, {"success": False, "error": "Invite token required"})
                    return
                access = self._load_access_control()
                invite = (access.get("invites") or {}).get(token)
                if not invite:
                    self._send_json(404, {"success": False, "error": "Invite not found"})
                    return
                project = self._slugify_name(str(invite.get("project") or "").strip())
                actor = self._current_user()
                actor_role = self._role_for_user(access, project, actor)
                if actor_role != "owner" and not (self._auth_config()["allow_local"] and self._is_local_client()):
                    self._send_json(403, {"success": False, "error": "Only owner can revoke invites"})
                    return
                invite["revoked"] = True
                access.setdefault("invites", {})[token] = invite
                self._save_access_control(access)
                self._send_json(200, {"success": True, "token": token, "revoked": True, "project": project})
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "invite_revoked",
                    "project": project,
                    "user": actor,
                    "inviteToken": token,
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/session/ping':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                project_raw = str(payload.get("project") or "").strip()
                project = self._slugify_name(project_raw) if project_raw else ""
                user = self._current_user()
                access = self._load_access_control()
                if project and not self._can_access_project(access, project, user, write=False):
                    # Ignore unauthorized project context but still track global session.
                    project = ""
                result = self._track_session_ping(user=user, project=project)
                self._send_json(200, {"success": True, **result})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/symbols/save':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                raw_project = str(payload.get("project") or "").strip()
                project = self._slugify_name(raw_project) if raw_project else ""
                user = self._current_user()
                access = self._load_access_control()
                if project:
                    self._ensure_project_owner(access, project, user)
                    if not self._can_access_project(access, project, user, write=True):
                        self._send_json(403, {"success": False, "error": "No write access to project"})
                        return
                    self._save_access_control(access)
                safe_symbols = self._sanitize_symbol_definitions(payload.get("symbols") or {})
                source = str(payload.get("source") or "manual")
                saved = self._save_symbols_bundle(project, safe_symbols, user=user, source=source, create_backup=True)
                self._send_json(200, {
                    "success": True,
                    "project": project,
                    "scope": saved.get("scope"),
                    "symbolCount": len(saved.get("symbols") or {}),
                    "updatedAt": saved.get("updatedAt"),
                    "backupFilename": saved.get("backupFilename"),
                })
                if project:
                    self._append_audit(project, {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "action": "symbols_saved",
                        "project": project,
                        "user": user,
                        "count": len(saved.get("symbols") or {}),
                        "source": source,
                        "backupFilename": saved.get("backupFilename"),
                    })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/symbols/restore-latest':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                raw_project = str(payload.get("project") or "").strip()
                project = self._slugify_name(raw_project) if raw_project else ""
                user = self._current_user()
                access = self._load_access_control()
                if project and not self._can_access_project(access, project, user, write=True):
                    self._send_json(403, {"success": False, "error": "No write access to project"})
                    return
                restored = self._restore_latest_symbols(project, user=user)
                if not restored:
                    self._send_json(404, {"success": False, "error": "No symbol backups found"})
                    return
                self._send_json(200, {
                    "success": True,
                    "project": project,
                    "scope": restored.get("scope"),
                    "symbols": restored.get("symbols") or {},
                    "updatedAt": restored.get("updatedAt"),
                    "restoredFrom": restored.get("restoredFrom"),
                })
                if project:
                    self._append_audit(project, {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "action": "symbols_restored_latest",
                        "project": project,
                        "user": user,
                        "count": len(restored.get("symbols") or {}),
                        "restoredFrom": restored.get("restoredFrom"),
                    })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        elif path == '/api/save-binary':
            if not self._is_authorized():
                self._deny_unauthorized()
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data or b"{}")
                raw_project = str(payload.get("project") or payload.get("projectName") or "").strip()
                if not raw_project:
                    self._send_json(400, {"success": False, "error": "Project required"})
                    return
                project = self._slugify_name(raw_project)
                filename = self._slugify_name(str(payload.get("filename") or "").strip())
                if not filename:
                    self._send_json(400, {"success": False, "error": "Filename required"})
                    return
                if "." not in filename:
                    filename = f"{filename}.zip"
                b64 = str(payload.get("bytesB64") or "").strip()
                if not b64:
                    self._send_json(400, {"success": False, "error": "bytesB64 required"})
                    return
                try:
                    content = base64.b64decode(b64, validate=True)
                except Exception:
                    self._send_json(400, {"success": False, "error": "Invalid base64 payload"})
                    return
                user = self._current_user()
                access = self._load_access_control()
                self._ensure_project_owner(access, project, user)
                if not self._can_access_project(access, project, user, write=True):
                    self._send_json(403, {"success": False, "error": "No write access to project"})
                    return
                self._save_access_control(access)

                icloud_dir = ICLOUD_EXPORTS / project
                local_dir = LOCAL_EXPORTS / project
                icloud_dir.mkdir(parents=True, exist_ok=True)
                local_dir.mkdir(parents=True, exist_ok=True)
                icloud_path = icloud_dir / filename
                local_path = local_dir / filename
                with open(icloud_path, "wb") as f:
                    f.write(content)
                with open(local_path, "wb") as f:
                    f.write(content)
                rel_path = f"{project}/{filename}"
                self._send_json(200, {
                    "success": True,
                    "project": project,
                    "filename": rel_path,
                    "savePath": rel_path,
                    "icloud": str(icloud_path),
                    "local": str(local_path),
                    "bytes": len(content),
                })
                self._append_audit(project, {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "action": "binary_saved",
                    "project": project,
                    "path": rel_path,
                    "user": user,
                    "bytes": len(content),
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Markup-Token')
        self.end_headers()
    
    def log_message(self, format, *args):
        """Quieter logging."""
        pass


def get_local_ip():
    """Get local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


def main():
    parser = argparse.ArgumentParser(description="Symphony Markup App Server")
    parser.add_argument('--port', type=int, default=8088, help='Port number')
    parser.add_argument('--host', default='127.0.0.1', help='Host/IP to bind (default: localhost)')
    args = parser.parse_args()
    
    local_ip = get_local_ip()
    
    remote_hint = f"║  LAN:    http://{local_ip}:{args.port}                        ║" if args.host == "0.0.0.0" else "║  LAN:    disabled (localhost bind)                      ║"

    print(f"""
╔════════════════════════════════════════════════════════════╗
║             Symphony Markup App Server                     ║
╠════════════════════════════════════════════════════════════╣
║  Bind:   {args.host:<43}║
║  Local:  http://localhost:{args.port:<25}║
{remote_hint}
╠════════════════════════════════════════════════════════════╣
║  Exports saved to:                                         ║
║    iCloud: ~/Library/.../Symphony SH/Markup_Exports/       ║
║    Local:  ~/AI-Server/knowledge/markup_exports/           ║
╚════════════════════════════════════════════════════════════╝
Press Ctrl+C to stop
    """)
    
    server = HTTPServer((args.host, args.port), MarkupHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
