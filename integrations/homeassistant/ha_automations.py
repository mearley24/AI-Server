"""
ha_automations.py — Symphony Smart Homes
Automation Manager for Bob the Conductor

Bob can create, manage, trigger, and roll back Home Assistant automations via this module.
Includes a library of Symphony-specific automation templates for common AV/smart home workflows.

Usage:
    manager = AutomationManager(ha_client)
    automation_id = await manager.create_from_template(
        "welcome_scene",
        context={"person_entity": "person.homeowner", "scene": "scene.welcome"}
    )
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("symphony.ha_automations")


# ---------------------------------------------------------------------------
# Symphony Automation Templates
# ---------------------------------------------------------------------------
# Each template is a HA automation config skeleton.
# {{ variables }} are replaced by AutomationManager at creation time.

SYMPHONY_TEMPLATES: Dict[str, dict] = {

    # --- Welcome Scene ---
    "welcome_scene": {
        "_description": "When a client/resident arrives home, trigger the welcome scene",
        "_variables": ["person_entity", "scene_entity", "notify_bob"],
        "alias": "Symphony — Welcome Home",
        "description": "Activates welcome scene when resident arrives home",
        "mode": "single",
        "trigger": [
            {
                "platform": "state",
                "entity_id": "{{ person_entity }}",
                "from": "not_home",
                "to": "home",
            }
        ],
        "condition": [],
        "action": [
            {
                "service": "scene.turn_on",
                "target": {"entity_id": "{{ scene_entity }}"},
            },
            {
                "condition": "template",
                "value_template": "{{ notify_bob | default(false) }}",
            },
            {
                "service": "mqtt.publish",
                "data": {
                    "topic": "symphony/bob/status",
                    "payload": '{"event": "resident_arrived", "person": "{{ person_entity }}"}',
                },
            },
        ],
    },

    # --- Night Motion Alert ---
    "night_motion_alert": {
        "_description": "If camera detects motion at night, alert Bob and start recording",
        "_variables": ["camera_entity", "motion_sensor", "start_time", "end_time"],
        "alias": "Symphony — Night Motion Alert",
        "description": "Triggers security workflow when motion detected after hours",
        "mode": "parallel",
        "max": 5,
        "trigger": [
            {
                "platform": "state",
                "entity_id": "{{ motion_sensor }}",
                "to": "on",
            }
        ],
        "condition": [
            {
                "condition": "time",
                "after": "{{ start_time | default('22:00:00') }}",
                "before": "{{ end_time | default('06:00:00') }}",
            }
        ],
        "action": [
            {
                "service": "camera.snapshot",
                "data": {
                    "entity_id": "{{ camera_entity }}",
                    "filename": "/config/www/motion_{{ now().strftime('%Y%m%d_%H%M%S') }}.jpg",
                },
            },
            {
                "service": "mqtt.publish",
                "data": {
                    "topic": "symphony/bob/commands",
                    "payload_template": (
                        '{"command": "security_alert", "camera": "{{ camera_entity }}", '
                        '"sensor": "{{ motion_sensor }}", '
                        '"timestamp": "{{ now().isoformat() }}"}'
                    ),
                },
            },
        ],
    },

    # --- Network Device Offline ---
    "network_device_offline": {
        "_description": "When an Araknis network device goes offline, notify Bob",
        "_variables": ["device_entity", "device_name"],
        "alias": "Symphony — Network Device Offline: {{ device_name }}",
        "description": "Notifies Bob when a managed network device goes offline",
        "mode": "single",
        "trigger": [
            {
                "platform": "state",
                "entity_id": "{{ device_entity }}",
                "to": "unavailable",
                "for": {"minutes": 2},
            }
        ],
        "condition": [],
        "action": [
            {
                "service": "mqtt.publish",
                "data": {
                    "topic": "araknis/{{ device_name }}/alert",
                    "payload_template": (
                        '{"status": "offline", "device": "{{ device_name }}", '
                        '"timestamp": "{{ now().isoformat() }}", "entity": "{{ device_entity }}"}'
                    ),
                    "retain": True,
                },
            },
        ],
    },

    # --- Morning Routine ---
    "morning_routine": {
        "_description": "Gradually brighten lights and adjust shades on a schedule",
        "_variables": [
            "wake_time", "light_entities", "shade_entities",
            "final_brightness", "transition_minutes"
        ],
        "alias": "Symphony — Morning Routine",
        "description": "Gradual morning light transition for comfortable wake-up",
        "mode": "single",
        "trigger": [
            {
                "platform": "time",
                "at": "{{ wake_time | default('07:00:00') }}",
            }
        ],
        "condition": [
            {
                "condition": "time",
                "weekday": ["mon", "tue", "wed", "thu", "fri"],
            }
        ],
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "{{ light_entities }}"},
                "data": {
                    "brightness_pct": 10,
                    "transition": 0,
                },
            },
            {
                "delay": {"minutes": "{{ (transition_minutes | default(20)) // 2 }}"},
            },
            {
                "service": "light.turn_on",
                "target": {"entity_id": "{{ light_entities }}"},
                "data": {
                    "brightness_pct": "{{ final_brightness | default(80) }}",
                    "color_temp_kelvin": 4000,
                    "transition": "{{ (transition_minutes | default(20)) * 30 }}",
                },
            },
            {
                "service": "cover.set_cover_position",
                "target": {"entity_id": "{{ shade_entities }}"},
                "data": {"position": 50},
            },
        ],
    },

    # --- AV Scene Trigger ---
    "av_scene_trigger": {
        "_description": "Trigger AV/lighting scene from Control4 or Lutron keypad event",
        "_variables": ["trigger_entity", "trigger_state", "scene_entity", "sonos_playlist"],
        "alias": "Symphony — AV Scene: {{ scene_entity }}",
        "description": "Activates an AV scene including audio when a keypad button is pressed",
        "mode": "restart",
        "trigger": [
            {
                "platform": "state",
                "entity_id": "{{ trigger_entity }}",
                "to": "{{ trigger_state }}",
            }
        ],
        "condition": [],
        "action": [
            {
                "service": "scene.turn_on",
                "target": {"entity_id": "{{ scene_entity }}"},
            },
            {
                "condition": "template",
                "value_template": "{{ sonos_playlist | default('') != '' }}",
            },
            {
                "service": "media_player.shuffle_set",
                "target": {"entity_id": "media_player.sonos_living_room"},
                "data": {"shuffle": True},
            },
            {
                "service": "media_player.play_media",
                "target": {"entity_id": "media_player.sonos_living_room"},
                "data": {
                    "media_content_id": "{{ sonos_playlist }}",
                    "media_content_type": "playlist",
                },
            },
        ],
    },

    # --- Security Arm on Departure ---
    "security_arm_departure": {
        "_description": "Arm security system when all residents leave",
        "_variables": ["person_entities", "alarm_entity", "lock_entities"],
        "alias": "Symphony — Arm Security on Departure",
        "description": "Arms the security system and locks doors when everyone leaves",
        "mode": "single",
        "trigger": [
            {
                "platform": "state",
                "entity_id": "{{ person_entities }}",
                "to": "not_home",
            }
        ],
        "condition": [
            {
                "condition": "template",
                "value_template": "{{ states.person | selectattr('state', 'eq', 'home') | list | count == 0 }}",
            }
        ],
        "action": [
            {
                "service": "alarm_control_panel.alarm_arm_away",
                "target": {"entity_id": "{{ alarm_entity }}"},
            },
            {
                "service": "lock.lock",
                "target": {"entity_id": "{{ lock_entities }}"},
            },
            {
                "service": "mqtt.publish",
                "data": {
                    "topic": "symphony/bob/status",
                    "payload": '{"event": "security_armed", "mode": "away", "trigger": "auto_departure"}',
                },
            },
        ],
    },

    # --- Bob MQTT Command Handler ---
    "bob_command_relay": {
        "_description": "Relay Bob's commands from MQTT to HA actions",
        "_variables": ["mqtt_topic"],
        "alias": "Symphony — Bob Command Relay",
        "description": "Listens for Bob's MQTT commands and executes corresponding HA actions",
        "mode": "queued",
        "max": 10,
        "trigger": [
            {
                "platform": "mqtt",
                "topic": "{{ mqtt_topic | default('symphony/ha/commands') }}",
            }
        ],
        "condition": [],
        "action": [
            {
                "service": "script.turn_on",
                "data": {
                    "entity_id": "script.process_bob_command",
                    "variables": {
                        "payload": "{{ trigger.payload_json }}",
                    },
                },
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_automation_config(config: dict) -> List[str]:
    """
    Validate an automation config dict before sending to HA.
    Returns a list of error messages (empty = valid).
    """
    errors = []
    required_fields = ["alias", "trigger", "action"]
    for field in required_fields:
        if field not in config:
            errors.append(f"Missing required field: '{field}'")

    # Validate trigger is a list
    if "trigger" in config and not isinstance(config["trigger"], list):
        errors.append("'trigger' must be a list")

    # Validate action is a list
    if "action" in config and not isinstance(config["action"], list):
        errors.append("'action' must be a list")

    # Check mode is valid
    valid_modes = {"single", "parallel", "queued", "restart"}
    if "mode" in config and config["mode"] not in valid_modes:
        errors.append(f"Invalid mode '{config['mode']}'; must be one of {valid_modes}")

    # Safety: flag security-critical actions
    action_str = json.dumps(config.get("action", []))
    safety_keywords = ["alarm_control_panel", "lock", "garage", "gate"]
    for kw in safety_keywords:
        if kw in action_str:
            errors.append(
                f"WARNING: Automation contains safety-critical action ({kw}). "
                "Owner confirmation required before deployment."
            )

    return errors


def _render_template_vars(template_obj: Any, variables: dict) -> Any:
    """
    Simple {{ var }} substitution in automation config dicts.
    Handles nested dicts, lists, and strings.
    """
    if isinstance(template_obj, str):
        for key, value in variables.items():
            placeholder = "{{ " + key + " }}"
            if placeholder in template_obj:
                if isinstance(value, list):
                    template_obj = template_obj.replace(placeholder, json.dumps(value))
                else:
                    template_obj = template_obj.replace(placeholder, str(value))
        return template_obj
    elif isinstance(template_obj, dict):
        return {k: _render_template_vars(v, variables) for k, v in template_obj.items()}
    elif isinstance(template_obj, list):
        return [_render_template_vars(item, variables) for item in template_obj]
    return template_obj


# ---------------------------------------------------------------------------
# Automation Manager
# ---------------------------------------------------------------------------

class AutomationManager:
    """
    Manages Home Assistant automations on behalf of Bob the Conductor.

    Create automations from templates or raw configs, update them,
    trigger them manually, and roll back to previous states.
    """

    def __init__(self, ha_client):
        self._ha = ha_client
        self._created_ids: List[str] = []         # track IDs created this session
        self._backup_store: Dict[str, dict] = {}  # automation_id → backup config

    # ------------------------------------------------------------------
    # Template-based creation
    # ------------------------------------------------------------------

    def list_templates(self) -> List[dict]:
        """List all available Symphony automation templates."""
        return [
            {
                "name": name,
                "description": tmpl.get("_description", ""),
                "variables": tmpl.get("_variables", []),
                "alias": tmpl.get("alias", ""),
            }
            for name, tmpl in SYMPHONY_TEMPLATES.items()
        ]

    async def create_from_template(
        self,
        template_name: str,
        variables: Optional[dict] = None,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        Create a new HA automation from a named Symphony template.

        Args:
            template_name: Key from SYMPHONY_TEMPLATES (e.g. "welcome_scene")
            variables: Dict of variable values to substitute into the template
            dry_run: If True, validate and return config without creating

        Returns:
            The automation ID string, or None if dry_run=True.

        Raises:
            ValueError if template not found or validation fails.
        """
        if template_name not in SYMPHONY_TEMPLATES:
            available = ", ".join(SYMPHONY_TEMPLATES.keys())
            raise ValueError(f"Unknown template '{template_name}'. Available: {available}")

        # Deep copy to avoid mutating the template
        config = copy.deepcopy(SYMPHONY_TEMPLATES[template_name])

        # Strip internal metadata keys
        config = {k: v for k, v in config.items() if not k.startswith("_")}

        # Substitute variables
        if variables:
            config = _render_template_vars(config, variables)

        # Validate
        errors = _validate_automation_config(config)
        safety_warnings = [e for e in errors if e.startswith("WARNING:")]
        hard_errors = [e for e in errors if not e.startswith("WARNING:")]

        if hard_errors:
            raise ValueError(f"Automation validation failed:\n" + "\n".join(hard_errors))

        if safety_warnings:
            for w in safety_warnings:
                logger.warning(f"Safety check: {w}")

        if dry_run:
            logger.info(f"Dry run — automation config valid:\n{json.dumps(config, indent=2)}")
            return None

        return await self.create_automation(config)

    # ------------------------------------------------------------------
    # Raw CRUD
    # ------------------------------------------------------------------

    async def create_automation(self, config: dict) -> str:
        """
        Create a new automation from a raw HA config dict.

        Returns:
            The new automation's ID string.
        """
        # Validate first
        errors = _validate_automation_config(config)
        hard_errors = [e for e in errors if not e.startswith("WARNING:")]
        if hard_errors:
            raise ValueError(f"Automation validation failed: {'; '.join(hard_errors)}")

        result = await self._ha.create_automation(config)
        automation_id = result.get("automation_id") or result.get("id", "")

        if automation_id:
            self._created_ids.append(automation_id)
            logger.info(f"Created automation: {automation_id} — '{config.get('alias', '')}'")
        else:
            logger.warning(f"Automation created but no ID returned: {result}")

        return automation_id

    async def get_automation(self, automation_id: str) -> dict:
        """Fetch an automation config by ID."""
        return await self._ha.get_automation_config(automation_id)

    async def list_automations(self) -> List[dict]:
        """List all automations in Home Assistant."""
        return await self._ha.list_automations()

    async def update_automation(
        self,
        automation_id: str,
        config: dict,
        backup: bool = True,
    ) -> dict:
        """
        Update an existing automation.

        Args:
            automation_id: The automation to update
            config: New config dict
            backup: If True, save the current config for potential rollback
        """
        if backup:
            try:
                current = await self.get_automation(automation_id)
                self._backup_store[automation_id] = current
                logger.debug(f"Backed up automation {automation_id}")
            except Exception as exc:
                logger.warning(f"Could not backup automation {automation_id}: {exc}")

        result = await self._ha.update_automation(automation_id, config)
        logger.info(f"Updated automation: {automation_id}")
        return result

    async def delete_automation(self, automation_id: str) -> bool:
        """
        Delete an automation.

        Returns:
            True if deleted successfully.
        """
        # Backup before deletion
        try:
            current = await self.get_automation(automation_id)
            self._backup_store[automation_id] = current
        except Exception:
            pass

        await self._ha.delete_automation(automation_id)
        if automation_id in self._created_ids:
            self._created_ids.remove(automation_id)
        logger.info(f"Deleted automation: {automation_id}")
        return True

    async def trigger_automation(self, automation_id: str):
        """Manually trigger an automation."""
        result = await self._ha.trigger_automation(automation_id)
        logger.info(f"Triggered automation: {automation_id} — success={result.success}")
        return result

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    async def rollback(self, automation_id: str) -> bool:
        """
        Roll back an automation to its backed-up state.

        Returns:
            True if rollback succeeded.
        """
        backup = self._backup_store.get(automation_id)
        if not backup:
            logger.error(f"No backup found for automation {automation_id}")
            return False

        await self._ha.update_automation(automation_id, backup)
        del self._backup_store[automation_id]
        logger.info(f"Rolled back automation: {automation_id}")
        return True

    async def rollback_all_session(self):
        """Roll back all automations created or modified this session."""
        for automation_id in list(self._backup_store.keys()):
            await self.rollback(automation_id)

        # Delete automations created this session (no prior state to restore)
        for automation_id in list(self._created_ids):
            await self.delete_automation(automation_id)

        logger.info(f"Session rollback complete")

    # ------------------------------------------------------------------
    # Natural language helpers
    # ------------------------------------------------------------------

    def parse_nl_to_template(self, description: str) -> Optional[Tuple[str, dict]]:
        """
        Attempt to map a natural language description to a Symphony template.

        Returns:
            Tuple of (template_name, suggested_variables) or None if no match.

        Examples:
            "turn on welcome scene when client arrives" → ("welcome_scene", {...})
            "alert when motion detected at night" → ("night_motion_alert", {...})
        """
        description_lower = description.lower()

        # Simple keyword-based matching
        if any(kw in description_lower for kw in ["arrive", "welcome", "home", "arrival"]):
            return "welcome_scene", {
                "person_entity": "person.resident",
                "scene_entity": "scene.welcome",
                "notify_bob": "true",
            }
        elif any(kw in description_lower for kw in ["motion", "night", "alert", "security camera"]):
            return "night_motion_alert", {
                "camera_entity": "camera.luma_front_door",
                "motion_sensor": "binary_sensor.front_door_motion",
                "start_time": "22:00:00",
                "end_time": "06:00:00",
            }
        elif any(kw in description_lower for kw in ["morning", "wake", "gradually", "lights up", "sunrise"]):
            return "morning_routine", {
                "wake_time": "07:00:00",
                "light_entities": ["light.bedroom", "light.hallway"],
                "shade_entities": ["cover.bedroom_shade"],
                "final_brightness": "80",
                "transition_minutes": "20",
            }
        elif any(kw in description_lower for kw in ["network", "offline", "device down", "router"]):
            return "network_device_offline", {
                "device_entity": "binary_sensor.araknis_router",
                "device_name": "araknis_router",
            }
        elif any(kw in description_lower for kw in ["leave", "depart", "arm", "away", "lock"]):
            return "security_arm_departure", {
                "person_entities": ["person.resident"],
                "alarm_entity": "alarm_control_panel.home",
                "lock_entities": ["lock.front_door", "lock.back_door"],
            }
        elif any(kw in description_lower for kw in ["scene", "av", "theater", "keypad"]):
            return "av_scene_trigger", {
                "trigger_entity": "sensor.lutron_keypad_button",
                "trigger_state": "on",
                "scene_entity": "scene.theater",
                "sonos_playlist": "",
            }

        return None

    async def create_from_nl(
        self,
        description: str,
        variables_override: Optional[dict] = None,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        Create an automation from a natural language description.

        This is the primary interface for Bob's AI agents to create automations
        without needing to know HA configuration syntax.

        Args:
            description: Natural language description of the desired automation
            variables_override: Override specific template variables
            dry_run: Validate without creating

        Returns:
            Automation ID, or None if no template matched or dry_run.
        """
        match = self.parse_nl_to_template(description)
        if not match:
            logger.warning(f"No matching template for: '{description}'")
            return None

        template_name, suggested_vars = match
        if variables_override:
            suggested_vars.update(variables_override)

        logger.info(f"Matched '{description}' → template '{template_name}'")
        return await self.create_from_template(template_name, suggested_vars, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Typing fix
# ---------------------------------------------------------------------------
from typing import Tuple  # noqa: E402
