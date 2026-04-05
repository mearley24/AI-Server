"""Unified Symphony client lifecycle coordinator."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import redis
import requests

try:
    from client_tracker import ClientTracker
    from dropbox_integration import create_project_folders
    from follow_up_tracker import FollowUpTracker
    from payment_tracker import PaymentTracker
    from project_template import create_project
except ImportError:
    from openclaw.client_tracker import ClientTracker
    from openclaw.dropbox_integration import create_project_folders
    from openclaw.follow_up_tracker import FollowUpTracker
    from openclaw.payment_tracker import PaymentTracker
    from openclaw.project_template import create_project

logger = logging.getLogger("openclaw.lifecycle")

PHASES = [
    "lead",
    "proposal_sent",
    "follow_up_active",
    "deposit_pending",
    "project_setup",
    "commissioning",
    "handoff",
    "complete",
]


@dataclass
class LifecycleRecord:
    project_id: str
    client_name: str
    phase: str
    phase_start_date: str
    next_action: str
    metadata: dict[str, Any]


class LifecycleCoordinator:
    """
    Manages full client lifecycle and calls tracker interfaces at phase transitions.
    """

    def __init__(
        self,
        client_tracker: ClientTracker,
        follow_up_tracker: FollowUpTracker,
        payment_tracker: PaymentTracker,
        redis_url: str | None = None,
    ):
        self.client_tracker = client_tracker
        self.follow_up_tracker = follow_up_tracker
        self.payment_tracker = payment_tracker
        self.redis = redis.from_url(redis_url or os.getenv("REDIS_URL", "redis://:d1fff1065992d132b000c01d6012fa52@redis:6379"), decode_responses=True, socket_timeout=2)
        self.payment_tracker.set_on_confirm(self._on_payment_confirm)

    @staticmethod
    def _key(project_id: str) -> str:
        return f"lifecycle:project:{project_id}"

    def _phase_idx(self, phase: str) -> int:
        return PHASES.index(phase)

    def _load(self, project_id: str) -> dict[str, Any]:
        raw = self.redis.get(self._key(project_id))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save(self, project_id: str, row: dict[str, Any]) -> None:
        self.redis.set(self._key(project_id), json.dumps(row))

    def _notify(self, title: str, body: str) -> None:
        payload = {"title": title, "body": body}
        try:
            self.redis.publish("notifications:trading", json.dumps(payload))
        except Exception:
            pass

    def _emit_event(self, event_type: str, payload: dict[str, Any], priority: str = "normal") -> None:
        event = {
            "service": "lifecycle-coordinator",
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "priority": priority,
        }
        self.redis.publish("agents:messages", json.dumps(event))

    def _create_lead_linear_ticket(self, project_id: str, client_name: str, source: str) -> None:
        api_key = os.getenv("LINEAR_API_KEY", "")
        team_id = os.getenv("LINEAR_TEAM_ID", "b1ba685a-0eff-43fe-bec9-023e3c455672")
        if not api_key:
            logger.info("[lifecycle] LINEAR_API_KEY missing, skipping lead ticket")
            return
        query = """
        mutation CreateIssue($input: IssueCreateInput!) {
          issueCreate(input: $input) { success issue { id identifier title } }
        }
        """
        title = f"Lead: {client_name} ({project_id})"
        desc = f"Lifecycle lead created.\n\nSource: {source}\nProject: {project_id}"
        resp = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            json={"query": query, "variables": {"input": {"teamId": team_id, "title": title, "description": desc, "priority": 2}}},
            timeout=15,
        )
        if resp.status_code >= 300:
            logger.warning("[lifecycle] lead ticket create failed status=%s", resp.status_code)
            return
        logger.info("[lifecycle] lead ticket created project=%s", project_id)

    def _legal_transition(self, old_phase: str, new_phase: str) -> bool:
        if old_phase == new_phase:
            return True
        # Strict forward-only progression: cannot skip and cannot move backward.
        return self._phase_idx(new_phase) == self._phase_idx(old_phase) + 1

    def _archive_linear_project(self, row: dict[str, Any]) -> None:
        """Best-effort archive of Linear project when lifecycle completes."""
        api_key = os.getenv("LINEAR_API_KEY", "")
        project_id = str((row.get("metadata") or {}).get("linear_project_id") or "").strip()
        if not api_key or not project_id:
            logger.info("[lifecycle] linear archive skipped (missing api key or project id)")
            return
        query = """
        mutation ArchiveProject($id: String!) {
          projectArchive(id: $id) { success }
        }
        """
        try:
            resp = requests.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": api_key, "Content-Type": "application/json"},
                json={"query": query, "variables": {"id": project_id}},
                timeout=15,
            )
            if resp.status_code >= 300:
                logger.warning("[lifecycle] linear archive failed status=%s", resp.status_code)
                return
            logger.info("[lifecycle] linear project archived id=%s", project_id)
        except Exception as exc:
            logger.warning("[lifecycle] linear archive exception %s", exc)

    def _archive_dropbox_project(self, row: dict[str, Any]) -> None:
        """Best-effort move of project root into shared Dropbox Archive folder."""
        try:
            from dropbox_integration import _api_headers, _project_path
        except ImportError:
            from openclaw.dropbox_integration import _api_headers, _project_path

        metadata = row.get("metadata") or {}
        client_name = str(row.get("client_name") or "").strip()
        address = str(metadata.get("address") or "").strip()
        if not client_name:
            return
        project_name = f"{client_name} — {address}".strip(" —")
        from_path = _project_path(project_name)
        to_path = f"/Symphony Projects/Archive/{project_name}"

        try:
            # Ensure shared archive parent exists.
            requests.post(
                "https://api.dropboxapi.com/2/files/create_folder_v2",
                headers=_api_headers(),
                json={"path": "/Symphony Projects/Archive", "autorename": False},
                timeout=15,
            )
            resp = requests.post(
                "https://api.dropboxapi.com/2/files/move_v2",
                headers=_api_headers(),
                json={"from_path": from_path, "to_path": to_path, "allow_shared_folder": True, "autorename": True},
                timeout=20,
            )
            if resp.status_code not in (200, 409):
                resp.raise_for_status()
            logger.info("[lifecycle] dropbox project archived from=%s to=%s", from_path, to_path)
        except Exception as exc:
            logger.warning("[lifecycle] dropbox archive failed %s", exc)

    def transition(self, project_id: str, new_phase: str, metadata: dict | None = None):
        metadata = metadata or {}
        now = datetime.now(timezone.utc).isoformat()
        if new_phase not in PHASES:
            raise ValueError(f"Unknown lifecycle phase: {new_phase}")
        row = self._load(project_id)
        old_phase = row.get("phase")
        if old_phase and not self._legal_transition(old_phase, new_phase):
            raise ValueError(f"Illegal transition {old_phase} -> {new_phase}")

        client_name = metadata.get("client_name") or row.get("client_name") or project_id
        row.update(
            {
                "project_id": project_id,
                "client_name": client_name,
                "phase": new_phase,
                "phase_start_date": now,
                "metadata": {**(row.get("metadata") or {}), **metadata},
            }
        )

        # Phase actions
        if new_phase == "lead":
            self.client_tracker.create(project_id, metadata)
            self._create_lead_linear_ticket(project_id, client_name, metadata.get("lead_source", "unknown"))
            row["next_action"] = "Send proposal"
            self.client_tracker.set_lifecycle_status(project_id, "lead", metadata)

        elif new_phase == "proposal_sent":
            client_email = metadata.get("client_email", "")
            sent_date = metadata.get("proposal_sent_date")
            if isinstance(sent_date, date):
                proposal_date = sent_date
            elif isinstance(sent_date, str) and sent_date:
                proposal_date = date.fromisoformat(sent_date)
            else:
                proposal_date = date.today()
            self.follow_up_tracker.schedule_follow_ups(
                project_id=project_id,
                client_email=client_email,
                proposal_sent_date=proposal_date,
                client_name=client_name,
                project_value=float(metadata.get("project_value", 0) or 0),
                project_detail=str(metadata.get("project_detail") or metadata.get("address") or "").strip(),
            )
            link = ""
            try:
                link = create_project_folders(
                    project_id=project_id,
                    client_name=client_name,
                    address=metadata.get("address", ""),
                )
            except Exception as exc:
                logger.warning("[lifecycle] dropbox folder creation failed %s", exc)
            if link:
                row["metadata"]["dropbox_client_link"] = link
            if metadata.get("address"):
                row["metadata"]["address"] = metadata.get("address")
            self.client_tracker.set_lifecycle_status(project_id, "proposal_sent", {"dropbox_client_link": link})
            row["next_action"] = "Monitor follow-ups and deposit"
            # auto-progression to follow_up_active
            row["phase"] = "follow_up_active"
            self.client_tracker.set_lifecycle_status(project_id, "follow_up_active", {"dropbox_client_link": link})

        elif new_phase == "deposit_pending":
            expected = float(metadata.get("expected_amount", 0) or 0)
            if expected <= 0:
                expected = float(self.payment_tracker.get_expected_deposit(project_id) or 0)
            self.payment_tracker.watch_deposit(project_id, client_name, expected)
            row["next_action"] = "Await deposit confirmation"
            self.client_tracker.set_lifecycle_status(project_id, "deposit_pending", metadata)

        elif new_phase == "project_setup":
            self.follow_up_tracker.cancel_remaining(project_id)
            try:
                result = create_project(project_id, {"client_name": client_name, **metadata})
                row["metadata"]["linear_project_created"] = True
                if isinstance(result, dict):
                    linear_project_id = (
                        result.get("project", {}).get("id")
                        or result.get("project_id")
                    )
                    if linear_project_id:
                        row["metadata"]["linear_project_id"] = linear_project_id
            except Exception as exc:
                row["metadata"]["linear_project_created"] = False
                row["metadata"]["linear_error"] = str(exc)[:180]
                logger.warning("[lifecycle] project template create failed: %s", exc)
            self._notify("Lifecycle", f"{client_name} deposit confirmed — project setup complete")
            row["next_action"] = "Kickoff + procurement"
            self.client_tracker.set_lifecycle_status(project_id, "project_setup", metadata)
            self._emit_event("project_setup_complete", {"project_id": project_id, "client_name": client_name}, priority="high")

        elif new_phase == "commissioning":
            row["next_action"] = "Track system shell device completion"
            self.client_tracker.set_lifecycle_status(project_id, "commissioning", metadata)

        elif new_phase == "handoff":
            remaining = float(metadata.get("remaining_balance", 0) or 0)
            if remaining > 0:
                self.payment_tracker.watch_final_payment(project_id, remaining)
            row["next_action"] = "Collect final payment + 30-day check-in"
            row["metadata"]["checkin_30d_due"] = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
            self.client_tracker.set_lifecycle_status(project_id, "handoff", metadata)

        elif new_phase == "complete":
            row["next_action"] = "Archive project records"
            self.client_tracker.set_lifecycle_status(project_id, "complete", metadata)
            self._archive_linear_project(row)
            self._archive_dropbox_project(row)
            self._emit_event("project_completed", {"project_id": project_id, "client_name": client_name})

        self._save(project_id, row)
        logger.info("[lifecycle] transition %s -> %s", project_id, row.get("phase"))
        return row

    def _on_payment_confirm(self, project_id: str, target_phase: str) -> None:
        # payment tracker callback: deposit -> project_setup, final -> complete
        try:
            self.transition(project_id, target_phase)
        except Exception as exc:
            logger.warning("[lifecycle] payment transition failed %s", exc)

    def get_all_active(self) -> list[dict]:
        out: list[dict] = []
        for key in self.redis.scan_iter(match="lifecycle:project:*"):
            raw = self.redis.get(key)
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if row.get("phase") == "complete":
                continue
            out.append(
                {
                    "project_id": row.get("project_id"),
                    "client_name": row.get("client_name", ""),
                    "phase": row.get("phase", ""),
                    "phase_start_date": row.get("phase_start_date", ""),
                    "next_action": row.get("next_action", ""),
                }
            )
        out.sort(key=lambda r: r.get("phase_start_date", ""), reverse=True)
        return out

    def simulate_topletz(self) -> dict[str, Any]:
        """
        API-13 test flow:
        - ensure topetz client exists
        - ensure proposal follow-ups scheduled
        - simulate deposit receipt
        - verify project_setup and follow-ups cancelled
        """
        project_id = "topletz"
        client = self.client_tracker.get_by_project_id(project_id)
        if not client:
            self.transition(
                project_id,
                "lead",
                {
                    "client_name": "Topletz",
                    "email": "stopletz1@gmail.com",
                    "address": "84 Aspen Meadow Drive, Edwards, CO",
                    "lead_source": "existing_project",
                    "project_value": 34609.0,
                },
            )
            client = self.client_tracker.get_by_project_id(project_id)
        self.transition(
            project_id,
            "proposal_sent",
            {
                "client_name": client.get("name", "Topletz"),
                "client_email": client.get("email", "stopletz1@gmail.com"),
                "address": client.get("address", "84 Aspen Meadow Drive, Edwards, CO"),
                "proposal_sent_date": (date.today()).isoformat(),
                "project_value": float(self.payment_tracker.get_expected_deposit(project_id) or 0.0),
            },
        )
        expected = float(self.payment_tracker.get_expected_deposit(project_id) or 0.0)
        self.transition(project_id, "deposit_pending", {"client_name": "Topletz", "expected_amount": expected})
        self.payment_tracker.confirm_received(project_id, "deposit", expected)
        active = self.get_all_active()
        phase = self._load(project_id).get("phase")
        followups = self.follow_up_tracker.get_overdue() + self.follow_up_tracker.get_due_today()
        project_followups = [f for f in followups if f.get("project_id") == project_id and f.get("status") == "pending"]
        return {
            "project_id": project_id,
            "phase": phase,
            "followups_pending": len(project_followups),
            "active_projects_count": len(active),
        }
