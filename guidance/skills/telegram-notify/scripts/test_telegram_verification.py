from __future__ import annotations

import argparse
import importlib.util
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("telegram_verification.py")
SPEC = importlib.util.spec_from_file_location("telegram_verification", MODULE_PATH)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class TelegramVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_root = Path(self.temp.name)
        self.request_id = "a" * 24
        self.updates: list[dict] = []
        self.sent: list[tuple[str, dict]] = []

    def fake_api(self, _token: str, method: str, params: dict | None = None, timeout: int = 15) -> dict:
        self.sent.append((method, dict(params or {})))
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": ""}}
        if method == "getUpdates":
            result, self.updates = self.updates, []
            return {"ok": True, "result": result}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 10}}
        if method == "answerCallbackQuery":
            return {"ok": True, "result": True}
        raise AssertionError(method)

    @staticmethod
    def fake_send_message(_token: str, _chat_id: str, _text: str) -> dict:
        return {"ok": True, "result": {"message_id": 20}}

    def invoke(self, function, **values):
        output = io.StringIO()
        with (
            patch.object(verification, "STATE_ROOT", self.state_root),
            patch.object(verification, "config", return_value=("token", "42", {"42"})),
            patch.object(verification, "api", side_effect=self.fake_api),
            patch.object(verification.secrets, "token_hex", return_value=self.request_id),
            patch.object(verification.secrets, "token_urlsafe", return_value="nonce-value"),
            redirect_stdout(output),
        ):
            code = function(argparse.Namespace(**values))
        return code, json.loads(output.getvalue())

    def state(self) -> dict:
        return json.loads((self.state_root / f"{self.request_id}.json").read_text(encoding="utf-8"))

    def test_readiness_code_and_finish_without_code_persistence(self) -> None:
        code, result = self.invoke(verification.command_start, site="Example", expiry_minutes=5)
        self.assertEqual((code, result["status"]), (0, "pending"))
        current_state = self.state()
        self.assertEqual(current_state["stage"], "waiting_ready")
        self.assertNotIn("chat_id", current_state)
        self.assertNotIn("allowed_users", current_state)

        self.updates = [{
            "update_id": 1,
            "callback_query": {
                "id": "callback-1",
                "data": f"auth_ready:{self.request_id}:nonce-value",
                "from": {"id": 42},
                "message": {"chat": {"id": 42}},
            },
        }]
        code, result = self.invoke(
            verification.command_poll_ready,
            request_id=self.request_id,
            wait_seconds=0,
        )
        self.assertEqual((code, result["status"]), (0, "ready"))

        code, result = self.invoke(verification.command_ask_code, request_id=self.request_id)
        self.assertEqual((code, result["stage"]), (0, "waiting_code"))

        one_time_value = "7" * 6
        self.updates = [{
            "update_id": 2,
            "message": {
                "from": {"id": 42},
                "chat": {"id": 42},
                "date": int(time.time()) + 1,
                "text": one_time_value,
                "reply_to_message": {"message_id": 10},
            },
        }]
        code, result = self.invoke(
            verification.command_poll_code,
            request_id=self.request_id,
            wait_seconds=0,
        )
        self.assertEqual((code, result["status"]), (0, "code_received"))
        self.assertEqual(result["code"], one_time_value)
        self.assertNotIn(one_time_value, (self.state_root / f"{self.request_id}.json").read_text(encoding="utf-8"))

        output = io.StringIO()
        with patch.object(verification, "STATE_ROOT", self.state_root), redirect_stdout(output):
            code = verification.command_close(argparse.Namespace(request_id=self.request_id), "finished")
        result = json.loads(output.getvalue())
        self.assertEqual((code, result["status"]), (0, "finished"))
        self.assertFalse((self.state_root / f"{self.request_id}.json").exists())

    def test_expiry_requires_fresh_readiness(self) -> None:
        self.invoke(verification.command_start, site="Example", expiry_minutes=5)
        state = self.state()
        state["stage"] = "waiting_code"
        (self.state_root / f"{self.request_id}.json").write_text(json.dumps(state), encoding="utf-8")

        code, result = self.invoke(verification.command_expire, request_id=self.request_id)
        self.assertEqual((code, result["stage"]), (0, "waiting_ready"))
        self.assertEqual(self.state()["stage"], "waiting_ready")

    def test_numeric_message_not_replying_to_prompt_is_ignored(self) -> None:
        self.invoke(verification.command_start, site="Example", expiry_minutes=5)
        state = self.state()
        state["stage"] = "waiting_code"
        state["code_prompt_at"] = time.time()
        state["code_prompt_message_id"] = 10
        (self.state_root / f"{self.request_id}.json").write_text(json.dumps(state), encoding="utf-8")
        self.updates = [{
            "update_id": 3,
            "message": {
                "from": {"id": 42},
                "chat": {"id": 42},
                "date": int(state["code_prompt_at"]) - 10,
                "text": "8" * 6,
            },
        }]
        code, result = self.invoke(
            verification.command_poll_code,
            request_id=self.request_id,
            wait_seconds=0,
        )
        self.assertEqual((code, result["status"]), (0, "pending"))
        self.assertEqual(self.state()["stage"], "waiting_code")

        code, result = self.invoke(verification.command_ask_code, request_id=self.request_id)
        self.assertEqual((code, result["status"]), (2, "invalid_stage"))

    def test_unmatched_sender_and_callback_stay_pending(self) -> None:
        self.invoke(verification.command_start, site="Example", expiry_minutes=5)
        self.updates = [{
            "update_id": 1,
            "callback_query": {
                "id": "callback-1",
                "data": f"auth_ready:{self.request_id}:wrong-nonce",
                "from": {"id": 99},
                "message": {"chat": {"id": 42}},
            },
        }]
        code, result = self.invoke(
            verification.command_poll_ready,
            request_id=self.request_id,
            wait_seconds=0,
        )
        self.assertEqual((code, result["status"]), (0, "pending"))
        self.assertEqual(self.state()["stage"], "waiting_ready")

    def test_second_active_request_is_rejected(self) -> None:
        self.invoke(verification.command_start, site="Example", expiry_minutes=5)
        output = io.StringIO()
        with (
            patch.object(verification, "STATE_ROOT", self.state_root),
            patch.object(verification, "config", return_value=("token", "42", {"42"})),
            patch.object(verification, "api", side_effect=self.fake_api),
            patch.object(verification.secrets, "token_hex", return_value="b" * 24),
            redirect_stdout(output),
        ):
            with self.assertRaises(verification.SafeError):
                verification.command_start(argparse.Namespace(site="Other", expiry_minutes=5))

    def test_private_state_stays_under_aicc_state_root(self) -> None:
        self.assertEqual(
            verification.STATE_ROOT,
            verification.AICC_STATE_ROOT / "telegram" / "verification-state",
        )
        self.assertEqual(
            verification.ENV_FILE,
            verification.AICC_STATE_ROOT / "telegram" / "agent-bridge.env",
        )


if __name__ == "__main__":
    unittest.main()
