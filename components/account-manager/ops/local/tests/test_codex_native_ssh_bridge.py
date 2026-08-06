import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


import sys

TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

import codex_native_ssh_bridge as bridge


class CodexNativeSshBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = Path(self.tmp.name)
        self.home = self.manager / "home"
        self.home.mkdir()
        (self.home / "auth.json").write_text("{}", encoding="utf-8")
        self.exe = self.manager / "codex.exe"
        self.exe.write_bytes(b"test")

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, **updates):
        data = {
            "schema_version": 2,
            "running": True,
            "target_account": "other@example.invalid",
            "native_home": str(self.home),
            "native_codex_exe": str(self.exe),
        }
        data.update(updates)
        (self.manager / bridge.STATE_NAME).write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_target_requires_ready_native_home(self):
        self.write_state()
        state, home, exe = bridge._target(self.manager)
        self.assertEqual(state["target_account"], "other@example.invalid")
        self.assertEqual(home, self.home.resolve())
        self.assertEqual(exe, self.exe.resolve())

        (self.home / "auth.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "CODEX_HOME"):
            bridge._target(self.manager)

    def test_update_state_preserves_target_and_upgrades_schema(self):
        self.write_state(schema_version=1)
        result = bridge._update_state(self.manager, {"native_server_pid": 123})
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["target_account"], "other@example.invalid")
        self.assertEqual(result["native_server_pid"], 123)

    def test_stop_refuses_unverified_process_identity(self):
        with mock.patch(
            "codex_native_ssh_bridge._process_identity",
            return_value=(Path(sys.executable), 999),
        ), mock.patch.object(bridge, "_KERNEL32") as kernel32:
            stopped = bridge._terminate_owned(
                os.getpid(), sys.executable, 1000
            )
        self.assertFalse(stopped)
        kernel32.TerminateProcess.assert_not_called()

    def test_bootstrap_is_quiet_for_current_desktop_flow(self):
        self.write_state()
        self.assertEqual(bridge.command_bootstrap(self.manager), 0)


if __name__ == "__main__":
    unittest.main()
