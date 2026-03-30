#!/usr/bin/env python3
"""
dropbox_integration.py — Dropbox API v2 integration for Symphony Smart Homes.

Manages project files in Dropbox using raw HTTP requests (no SDK dependency).
Uses OAuth2 refresh token flow matching the existing Zoho pattern.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN", "")

BASE_FOLDER = "/Symphony Projects"

# Token cache
_access_token: Optional[str] = None
_token_expires_at: float = 0


def _refresh_access_token() -> str:
    """Refresh the Dropbox access token using the stored refresh token."""
    global _access_token, _token_expires_at

    if _access_token and time.time() < _token_expires_at:
        return _access_token

    if not DROPBOX_APP_KEY or not DROPBOX_APP_SECRET or not DROPBOX_REFRESH_TOKEN:
        raise ValueError(
            "Dropbox credentials not configured. "
            "Set DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN in .env"
        )

    resp = requests.post(
        "https://api.dropboxapi.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": DROPBOX_REFRESH_TOKEN,
            "client_id": DROPBOX_APP_KEY,
            "client_secret": DROPBOX_APP_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    _access_token = data["access_token"]
    # Dropbox tokens expire in ~4 hours; refresh 5 min early
    _token_expires_at = time.time() + data.get("expires_in", 14400) - 300

    logger.info("Dropbox access token refreshed")
    return _access_token


def _api_headers() -> dict:
    """Build standard API headers with a fresh access token."""
    token = _refresh_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _project_path(project_name: str) -> str:
    """Build the full Dropbox path for a project folder."""
    return f"{BASE_FOLDER}/{project_name}"


def create_project_folder(project_name: str) -> dict:
    """
    Create /Symphony Projects/{project_name}/ in Dropbox.

    Returns the Dropbox metadata dict for the created folder.
    Silently succeeds if folder already exists.
    """
    path = _project_path(project_name)

    resp = requests.post(
        "https://api.dropboxapi.com/2/files/create_folder_v2",
        headers=_api_headers(),
        json={"path": path, "autorename": False},
        timeout=15,
    )

    if resp.status_code == 409:
        # Folder already exists — not an error
        logger.info("Dropbox folder already exists: %s", path)
        return {"path": path, "status": "already_exists"}

    resp.raise_for_status()
    data = resp.json()
    logger.info("Created Dropbox folder: %s", path)
    return data.get("metadata", data)


def upload_file(
    project_name: str,
    local_path: str,
    filename: Optional[str] = None,
) -> dict:
    """
    Upload a file to /Symphony Projects/{project_name}/{filename}.

    Args:
        project_name: Name of the project folder.
        local_path: Path to the local file to upload.
        filename: Optional target filename. Defaults to the local filename.

    Returns the Dropbox file metadata dict.
    """
    local = Path(local_path)
    if not local.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    target_name = filename or local.name
    dropbox_path = f"{_project_path(project_name)}/{target_name}"

    token = _refresh_access_token()

    with open(local, "rb") as f:
        resp = requests.post(
            "https://content.dropboxapi.com/2/files/upload",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": json.dumps({
                    "path": dropbox_path,
                    "mode": "overwrite",
                    "autorename": False,
                    "mute": False,
                }),
            },
            data=f,
            timeout=120,
        )

    resp.raise_for_status()
    data = resp.json()
    logger.info("Uploaded to Dropbox: %s (%d bytes)", dropbox_path, data.get("size", 0))
    return data


def create_share_link(project_name: str) -> str:
    """
    Create a shared link for the project folder.

    Returns the shared URL string.
    If a link already exists, returns the existing one.
    """
    path = _project_path(project_name)

    resp = requests.post(
        "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings",
        headers=_api_headers(),
        json={
            "path": path,
            "settings": {
                "requested_visibility": "public",
                "audience": "public",
                "access": "viewer",
            },
        },
        timeout=15,
    )

    if resp.status_code == 409:
        # Shared link already exists — fetch it
        error_data = resp.json()
        if "shared_link_already_exists" in str(error_data):
            existing = (
                error_data
                .get("error", {})
                .get("shared_link_already_exists", {})
                .get("metadata", {})
            )
            url = existing.get("url", "")
            if url:
                logger.info("Dropbox share link already exists: %s", url)
                return url

            # Fallback: list shared links to find it
            list_resp = requests.post(
                "https://api.dropboxapi.com/2/sharing/list_shared_links",
                headers=_api_headers(),
                json={"path": path, "direct_only": True},
                timeout=15,
            )
            list_resp.raise_for_status()
            links = list_resp.json().get("links", [])
            if links:
                return links[0].get("url", "")

    resp.raise_for_status()
    url = resp.json().get("url", "")
    logger.info("Created Dropbox share link: %s", url)
    return url


def list_project_files(project_name: str) -> list[dict]:
    """
    List files in /Symphony Projects/{project_name}/.

    Returns a list of dicts with name, path, size, and modified info.
    """
    path = _project_path(project_name)

    resp = requests.post(
        "https://api.dropboxapi.com/2/files/list_folder",
        headers=_api_headers(),
        json={"path": path, "recursive": False, "include_deleted": False},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    entries = []
    for entry in data.get("entries", []):
        entries.append({
            "name": entry.get("name"),
            "path": entry.get("path_display"),
            "type": entry.get(".tag", "unknown"),
            "size": entry.get("size", 0),
            "modified": entry.get("client_modified", ""),
        })

    # Handle pagination
    while data.get("has_more"):
        resp = requests.post(
            "https://api.dropboxapi.com/2/files/list_folder/continue",
            headers=_api_headers(),
            json={"cursor": data["cursor"]},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        for entry in data.get("entries", []):
            entries.append({
                "name": entry.get("name"),
                "path": entry.get("path_display"),
                "type": entry.get(".tag", "unknown"),
                "size": entry.get("size", 0),
                "modified": entry.get("client_modified", ""),
            })

    logger.info("Listed %d entries in Dropbox: %s", len(entries), path)
    return entries
