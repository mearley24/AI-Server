"""
Rules-based decision engine for Bob's Brain context.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

try:
    from context_store import ContextStore, DEFAULT_SECTIONS
except ImportError:
    from openclaw.context_store import ContextStore, DEFAULT_SECTIONS

logger = logging.getLogger("openclaw.context_engine")


@dataclass
class Rule:
    name: str
    description: str
    condition_spec: dict[str, Any]
    action_name: str


def _path_get(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class DecisionEngine:
    def __init__(
        self,
        context_store: ContextStore,
        agent_bus: Any,
        rules_path: Path,
        plugins_dir: Path | None = None,
    ):
        self.context = context_store
        self.bus = agent_bus
        self.rules_path = rules_path
        self.plugins_dir = plugins_dir
        self.rules: list[Rule] = []
        self.plugin_rules: list[Callable[[dict[str, Any], Any, ContextStore], Any]] = []
        self._load_rules()
        self._load_plugin_rules()

    def _load_rules(self) -> None:
        self.rules = []
        if not self.rules_path.exists():
            logger.warning("[context-engine] rules file missing: %s", self.rules_path)
            return
        data = yaml.safe_load(self.rules_path.read_text(encoding="utf-8")) or {}
        for raw in data.get("rules", []):
            self.rules.append(
                Rule(
                    name=raw.get("name", "unnamed"),
                    description=raw.get("description", ""),
                    condition_spec=raw.get("condition", {}) or {},
                    action_name=raw.get("action", ""),
                )
            )
        logger.info("[context-engine] loaded %d yaml rules", len(self.rules))

    def _load_plugin_rules(self) -> None:
        self.plugin_rules = []
        if not self.plugins_dir or not self.plugins_dir.exists():
            return
        for py_file in sorted(self.plugins_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                register = getattr(mod, "register_rules", None)
                if callable(register):
                    added = register()
                    if isinstance(added, list):
                        self.plugin_rules.extend(added)
            except Exception as exc:
                logger.warning("[context-engine] plugin load failed (%s): %s", py_file.name, exc)
        if self.plugin_rules:
            logger.info("[context-engine] loaded %d plugin rules", len(self.plugin_rules))

    async def evaluate(self) -> dict[str, Any]:
        """
        Evaluate all YAML and plugin rules.
        Returns counts for telemetry.
        """
        snapshot = await self.context.get_snapshot(DEFAULT_SECTIONS)
        triggered: list[str] = []

        for rule in self.rules:
            try:
                if self._condition_matches(rule.condition_spec, snapshot):
                    await self._execute_action(rule.action_name, snapshot, rule)
                    triggered.append(rule.name)
            except Exception as exc:
                logger.warning("[context-engine] rule failed (%s): %s", rule.name, exc)

        for func in self.plugin_rules:
            try:
                result = func(snapshot, self.bus, self.context)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.warning("[context-engine] plugin rule failed: %s", exc)

        if triggered:
            logger.info("[context-engine] rules triggered: %s", ",".join(triggered))
        return {"evaluated": len(self.rules), "triggered": triggered}

    def _condition_matches(self, spec: dict[str, Any], snapshot: dict[str, Any]) -> bool:
        if not spec:
            return False

        metric = spec.get("metric")
        operator = spec.get("operator")
        threshold = spec.get("threshold")

        if metric and operator:
            actual = _path_get(snapshot, metric)
            if actual is None:
                return False
            return self._compare(actual, operator, threshold)

        # Event-like condition backed by context.
        evt = spec.get("event_type")
        if evt == "email_received":
            pending = _path_get(snapshot, "email.pending_count") or 0
            if int(pending) <= 0:
                return False

            contains = [str(x).lower() for x in spec.get("payload_contains", [])]
            subject = str(_path_get(snapshot, "email.last_subject") or "").lower()
            if contains and not any(token in subject for token in contains):
                return False

            sender = str(_path_get(snapshot, "email.last_sender") or "").lower()
            if spec.get("sender_in") == "known_clients":
                clients = snapshot.get("project", {}).get("known_clients") or []
                clients_l = [str(c).lower() for c in clients]
                if clients_l and not any(c in sender for c in clients_l):
                    return False
            return True

        return False

    @staticmethod
    def _compare(actual: Any, operator: str, threshold: Any) -> bool:
        try:
            a = float(actual)
            b = float(threshold)
        except Exception:
            a = actual
            b = threshold

        if operator == "less_than":
            return a < b
        if operator == "less_than_or_equal":
            return a <= b
        if operator == "greater_than":
            return a > b
        if operator == "greater_than_or_equal":
            return a >= b
        if operator == "equal":
            return a == b
        if operator == "not_equal":
            return a != b
        return False

    async def _execute_action(self, action_name: str, snapshot: dict[str, Any], rule: Rule) -> None:
        handlers = {
            "trigger_proposal_checker": self._action_trigger_proposal_checker,
            "alert_matt_and_pause_trades": self._action_alert_matt_and_pause_trades,
            "send_meeting_reminder": self._action_send_meeting_reminder,
            "draft_follow_up_emails": self._action_draft_follow_up_emails,
        }
        func = handlers.get(action_name)
        if not func:
            logger.warning("[context-engine] unknown action: %s", action_name)
            return
        await func(snapshot, rule)

    async def _action_trigger_proposal_checker(self, snapshot: dict[str, Any], rule: Rule) -> None:
        payload = {
            "event_type": "proposal_check_requested",
            "source": "context_engine",
            "rule": rule.name,
            "email": snapshot.get("email", {}),
        }
        await self.bus.publish("context_engine", "proposals_agent", "request", payload)

    async def _action_alert_matt_and_pause_trades(self, snapshot: dict[str, Any], rule: Rule) -> None:
        payload = {
            "event_type": "risk_alert",
            "source": "context_engine",
            "rule": rule.name,
            "message": "Portfolio drawdown threshold crossed; pause new trades.",
            "portfolio": snapshot.get("portfolio", {}),
        }
        await self.bus.publish("context_engine", "broadcast", "alert", payload)

    async def _action_send_meeting_reminder(self, snapshot: dict[str, Any], rule: Rule) -> None:
        payload = {
            "event_type": "calendar_reminder",
            "source": "context_engine",
            "rule": rule.name,
            "calendar": snapshot.get("calendar", {}),
        }
        await self.bus.publish("context_engine", "broadcast", "alert", payload)

    async def _action_draft_follow_up_emails(self, snapshot: dict[str, Any], rule: Rule) -> None:
        payload = {
            "event_type": "follow_up_draft_requested",
            "source": "context_engine",
            "rule": rule.name,
            "project": snapshot.get("project", {}),
        }
        await self.bus.publish("context_engine", "bob_conductor", "request", payload)
