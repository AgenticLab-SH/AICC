import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(TOOL_ROOT))

import codex_multi as cm  # noqa: E402


def local_hhmm(iso_utc: str) -> str:
    """Expected local rendering of a UTC instant on the current host.

    The formatter converts to local time, so a fixed string would only pass in
    one timezone. Deriving the expectation keeps the test honest anywhere.
    """
    return datetime.fromisoformat(iso_utc).astimezone().strftime("%Y-%m-%d %H:%M")


class CodexMultiResetCreditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)

    def test_only_available_unexpired_credits_define_nearest_deadline(self):
        payload = {
            "ok": True,
            "available_count": 2,
            "total_earned_count": 4,
            "credits": [
                {
                    "id": "must-not-leak",
                    "profile_user_id": "must-not-leak-either",
                    "status": "redeemed",
                    "expires_at": "2026-07-10T06:00:00Z",
                },
                {
                    "status": "available",
                    "expires_at": "2026-07-12T03:30:00Z",
                    "granted_at": "2026-07-01T00:00:00Z",
                },
                {
                    "status": "available",
                    "expires_at": "2026-07-11T01:15:00Z",
                    "granted_at": "2026-07-02T00:00:00Z",
                },
            ],
        }

        result = cm.format_reset_credit_status(payload, now=self.now)

        self.assertEqual(result["available"], 2)
        self.assertEqual(result["total_earned"], 4)
        self.assertEqual(
            result["nearest_expiry_local"], local_hhmm("2026-07-11T01:15:00+00:00")
        )
        self.assertEqual(result["nearest_remaining_text"], "1일 01시간 15분")
        self.assertEqual(len([c for c in result["credits"] if c["is_available"]]), 2)
        self.assertNotIn("id", result["credits"][0])
        self.assertNotIn("profile_user_id", result["credits"][0])

    def test_expired_available_item_is_not_usable(self):
        result = cm.format_reset_credit_status({
            "ok": True,
            "credits": [{"status": "available", "expires_at": "2026-07-09T23:59:00Z"}],
        }, now=self.now)

        self.assertEqual(result["available"], 0)
        self.assertEqual(result["expiries"], [])
        self.assertIsNone(result["nearest_expiry_local"])

    def test_epoch_milliseconds_and_relative_time_are_supported(self):
        parsed = cm._parse_expiry_value(1783645200000)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(cm.remaining_duration_text(183900), "2일 03시간 05분")
        self.assertEqual(cm.remaining_duration_text(300), "5분")
        self.assertEqual(cm.remaining_duration_text(0), "만료")

    def test_error_result_has_complete_safe_shape(self):
        result = cm.format_reset_credit_status({"ok": False, "error": "expired"})
        self.assertTrue(result["expired"])
        self.assertEqual(result["credits"], [])
        self.assertEqual(result["nearest_remaining_text"], "-")


if __name__ == "__main__":
    unittest.main()
