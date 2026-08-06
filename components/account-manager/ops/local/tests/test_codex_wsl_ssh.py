import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


import sys

TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

import codex_wsl_ssh as ssh


class CodexWslSshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self):
        return ssh.save_config(
            self.manager,
            {
                "enabled": True,
                "main_account": "main@example.invalid",
                "distro": "Ubuntu-24.04",
                "linux_user": "tester",
                "port": 2222,
            },
        )

    def test_status_does_not_enter_stopped_distro(self):
        self.configure()
        with mock.patch("codex_wsl_ssh.distro_running", return_value=False), mock.patch(
            "codex_wsl_ssh._wsl"
        ) as run_wsl:
            result = ssh.status(self.manager)

        self.assertFalse(result["wsl_running"])
        self.assertFalse(result["ssh_active"])
        run_wsl.assert_not_called()

    def test_windows_gui_safe_pid_probe_accepts_live_process(self):
        self.assertTrue(ssh._pid_alive(os.getpid()))

    def test_same_live_target_is_not_restarted(self):
        self.configure()
        native_home = self.manager / "native-home"
        native_home.mkdir()
        (native_home / "auth.json").write_text("{}", encoding="utf-8")
        native_exe = self.manager / "codex.exe"
        native_exe.write_bytes(b"test")
        ssh.save_state(
            self.manager,
            {
                "bridge_mode": "windows-native",
                "native_home": str(native_home.resolve()),
                "native_codex_exe": str(native_exe.resolve()),
            },
        )
        existing = {
            "ssh_active": True,
            "target_account": "other@example.invalid",
            "keeper_running": True,
        }
        with mock.patch("codex_wsl_ssh.status", return_value=existing), mock.patch(
            "codex_wsl_ssh._start_keeper"
        ) as keeper, mock.patch("codex_wsl_ssh._stop_daemon_if_running") as stop_daemon:
            result = ssh.start_for_account(
                self.manager,
                account_name="other@example.invalid",
                account_key="acct-key",
                auth_path=Path("C:/fake/auth.json"),
                app_home=Path("C:/fake/.codex"),
                native_home=native_home,
                native_codex_exe=native_exe,
                app_pid=1234,
            )

        keeper.assert_not_called()
        stop_daemon.assert_not_called()
        self.assertEqual(result["target_app_pid"], 1234)

    def test_idle_cleanup_stops_only_when_policy_and_idle_match(self):
        self.configure()
        with mock.patch("codex_wsl_ssh.status", return_value={"idle": False}), mock.patch(
            "codex_wsl_ssh.stop"
        ) as stop:
            self.assertFalse(ssh.stop_if_idle(self.manager))
            stop.assert_not_called()

        with mock.patch("codex_wsl_ssh.status", return_value={"idle": True}), mock.patch(
            "codex_wsl_ssh.stop"
        ) as stop:
            self.assertTrue(ssh.stop_if_idle(self.manager))
            stop.assert_called_once_with(self.manager, reason="idle-on-cm-start")

    def test_active_connection_is_not_idle_even_without_target_app(self):
        self.configure()
        ssh.save_state(self.manager, {"target_app_pid": None})
        completed = mock.Mock(returncode=0, stdout="active\n", stderr="")
        connection = mock.Mock(returncode=0, stdout="1\n", stderr="")
        size = mock.Mock(returncode=0, stdout="1024\n", stderr="")
        with mock.patch("codex_wsl_ssh.distro_running", return_value=True), mock.patch(
            "codex_wsl_ssh._wsl", side_effect=[completed, size]
        ), mock.patch("codex_wsl_ssh._wsl_shell", return_value=connection):
            result = ssh.status(self.manager)

        self.assertEqual(result["connections"], 1)
        self.assertFalse(result["idle"])
        self.assertEqual(result["runtime_bytes"], 1024)


if __name__ == "__main__":
    unittest.main()
