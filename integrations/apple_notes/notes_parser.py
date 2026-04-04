"""Read Apple Notes via JXA/osascript (macOS host only)."""

from __future__ import annotations

import json
import logging
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# JXA: export all notes as JSON (plaintext, folder, ids).
_JXA_EXPORT_ALL = r"""
function run() {
  try {
    var Notes = Application('Notes');
    var out = [];
    var notes = Notes.notes();
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      var folderName = '';
      try {
        folderName = String(n.container().name() || '');
      } catch (e0) {}
      var created = '';
      var modified = '';
      try {
        var cd = n.creationDate();
        created = cd ? String(cd) : '';
      } catch (e1) {}
      try {
        var md = n.modificationDate();
        modified = md ? String(md) : '';
      } catch (e2) {}
      var attCount = 0;
      try {
        var atts = n.attachments();
        attCount = atts ? atts.length : 0;
      } catch (e3) {}
      out.push({
        note_id: String(n.id()),
        title: String(n.name() || ''),
        body: String(n.plaintext() || ''),
        created_at: created,
        modified_at: modified,
        folder: folderName,
        attachment_count: attCount
      });
    }
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ "error": String(e) });
  }
}
"""

_JXA_FOLDERS = r"""
function run() {
  try {
    var Notes = Application('Notes');
    var out = [];
    var folders = Notes.folders();
    for (var i = 0; i < folders.length; i++) {
      var f = folders[i];
      var cnt = 0;
      try {
        var ns = f.notes();
        cnt = ns ? ns.length : 0;
      } catch (e) {}
      out.push({ name: String(f.name() || ''), note_count: cnt });
    }
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ "error": String(e) });
  }
}
"""

_JXA_NOTE_BY_ID = r"""
function run(argv) {
  if (!argv || argv.length < 1) return 'null';
  var want = argv[0];
  try {
    var Notes = Application('Notes');
    var notes = Notes.notes();
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      if (String(n.id()) !== String(want)) continue;
      var folderName = '';
      try { folderName = String(n.container().name() || ''); } catch (e0) {}
      var created = '', modified = '';
      try { var cd = n.creationDate(); created = cd ? String(cd) : ''; } catch (e1) {}
      try { var md = n.modificationDate(); modified = md ? String(md) : ''; } catch (e2) {}
      var attCount = 0;
      try { var atts = n.attachments(); attCount = atts ? atts.length : 0; } catch (e3) {}
      return JSON.stringify({
        note_id: String(n.id()),
        title: String(n.name() || ''),
        body: String(n.plaintext() || ''),
        created_at: created,
        modified_at: modified,
        folder: folderName,
        attachment_count: attCount
      });
    }
  } catch (e) { return 'null'; }
  return 'null';
}
"""

_JXA_ATTACHMENTS = r"""
function run(argv) {
  if (!argv || argv.length < 1) return '[]';
  var want = argv[0];
  try {
    var Notes = Application('Notes');
    var notes = Notes.notes();
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      if (String(n.id()) !== String(want)) continue;
      var out = [];
      try {
        var atts = n.attachments();
        for (var j = 0; j < atts.length; j++) {
          var a = atts[j];
          out.push({ name: String(a.name()||''), filename: String(a.filename()||'') });
        }
      } catch (e) {}
      return JSON.stringify(out);
    }
  } catch (e) {}
  return '[]';
}
"""


def run_jxa(source: str, timeout: float = 120.0) -> str:
    """Run a JavaScript-for-Automation snippet; return stdout."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", source],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"JXA failed (rc={result.returncode}): {result.stderr or result.stdout}"
        )
    return (result.stdout or "").strip()


def run_jxa_with_arg(source: str, arg: str, timeout: float = 90.0) -> str:
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", source, "--", arg],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"JXA failed (rc={result.returncode}): {result.stderr or result.stdout}"
        )
    return (result.stdout or "").strip()


def run_applescript(script: str, timeout: float = 60.0) -> str:
    """Execute AppleScript and return stdout (fallback / attachments)."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr}")
    return result.stdout.strip()


@dataclass
class NoteRecord:
    note_id: str
    title: str
    body: str
    created_at: str
    modified_at: str
    folder: str
    has_attachments: bool
    attachment_count: int = 0


@dataclass
class FolderInfo:
    name: str
    note_count: int


@dataclass
class AttachmentRecord:
    name: str
    filename: str


def _parse_note_dict(d: dict[str, Any]) -> NoteRecord:
    ac = int(d.get("attachment_count") or 0)
    return NoteRecord(
        note_id=str(d.get("note_id") or ""),
        title=str(d.get("title") or ""),
        body=str(d.get("body") or ""),
        created_at=str(d.get("created_at") or ""),
        modified_at=str(d.get("modified_at") or ""),
        folder=str(d.get("folder") or ""),
        has_attachments=ac > 0,
        attachment_count=ac,
    )


def get_all_notes() -> list[NoteRecord]:
    """Fetch all notes via JXA. Returns empty list on non-macOS or on failure."""
    if platform.system() != "Darwin":
        logger.warning("notes_parser: not macOS — skipping Notes export")
        return []
    try:
        raw = run_jxa(_JXA_EXPORT_ALL, timeout=180.0)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        if not isinstance(data, list):
            return []
        return [_parse_note_dict(x) for x in data if isinstance(x, dict)]
    except Exception as exc:
        logger.error("get_all_notes failed: %s", exc)
        return []


def get_folders() -> list[FolderInfo]:
    """List Notes folders with note counts."""
    if platform.system() != "Darwin":
        return []
    try:
        raw = run_jxa(_JXA_FOLDERS, timeout=60.0)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        if not isinstance(data, list):
            return []
        return [
            FolderInfo(name=str(x.get("name") or ""), note_count=int(x.get("note_count") or 0))
            for x in data
            if isinstance(x, dict)
        ]
    except Exception as exc:
        logger.error("get_folders failed: %s", exc)
        return []


def get_note_by_id(note_id: str) -> NoteRecord | None:
    """Fetch a single note by id (JXA)."""
    if platform.system() != "Darwin" or not note_id:
        return None
    try:
        raw = run_jxa_with_arg(_JXA_NOTE_BY_ID, note_id, timeout=90.0)
        if raw == "null" or not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return _parse_note_dict(data)
    except Exception as exc:
        logger.warning("get_note_by_id failed for %s: %s", note_id[:40], exc)
        return None


def get_attachments(note_id: str) -> list[AttachmentRecord]:
    """List attachment metadata for a note (read-only, JXA)."""
    if platform.system() != "Darwin" or not note_id:
        return []
    try:
        raw = run_jxa_with_arg(_JXA_ATTACHMENTS, note_id, timeout=90.0)
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return [
            AttachmentRecord(name=str(x.get("name") or ""), filename=str(x.get("filename") or ""))
            for x in data
            if isinstance(x, dict)
        ]
    except Exception as exc:
        logger.warning("get_attachments failed: %s", exc)
        return []
