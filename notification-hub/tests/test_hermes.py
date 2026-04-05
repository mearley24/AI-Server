"""Tests for Hermes routing (API-6)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes import NotificationRequest, resolve_channel  # noqa: E402


class HermesTests(unittest.TestCase):
    def test_resolve_system_log_telegram(self):
        req = NotificationRequest(
            recipient="Matt",
            message="log line",
            channel="auto",
            message_type="system_log",
        )
        self.assertEqual(resolve_channel(req), ["telegram"])

    def test_resolve_urgent_both(self):
        req = NotificationRequest(
            recipient="+19705550000",
            message="urgent",
            channel="auto",
            priority="urgent",
            message_type="alert",
        )
        self.assertEqual(resolve_channel(req), ["imessage", "email"])

    def test_resolve_client_prefix_email(self):
        req = NotificationRequest(
            recipient="client:bob@example.com",
            message="hello",
            channel="auto",
        )
        self.assertEqual(resolve_channel(req), ["email"])

    def test_resolve_explicit_imessage(self):
        req = NotificationRequest(recipient="x", message="m", channel="imessage")
        self.assertEqual(resolve_channel(req), ["imessage"])


if __name__ == "__main__":
    unittest.main()
