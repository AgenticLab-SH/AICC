from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import codex_macos_ssh as ssh


class MacOsSshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_config_defaults_to_loopback_high_port(self):
        config = ssh.load_config(self.manager)
        self.assertTrue(config["enabled"])
        self.assertEqual(config["port"], 2222)

    def test_connection_details_use_manager_owned_key(self):
        with mock.patch.dict(os.environ, {"USER": "sample"}, clear=False):
            details = ssh.connection_details(self.manager)
        self.assertEqual(details["host"], "sample@127.0.0.1")
        self.assertEqual(details["port"], 2222)
        self.assertEqual(details["identity_file"], str(self.manager / "ssh" / "client_ed25519"))

    def test_status_does_not_start_sshd(self):
        with mock.patch("codex_macos_ssh._owned_sshd_alive", return_value=False), mock.patch(
            "codex_macos_ssh._port_open"
        ) as port_open:
            result = ssh.status(self.manager)
        self.assertFalse(result["ssh_active"])
        port_open.assert_not_called()

    def test_connected_remote_is_not_idle_without_target_app(self):
        ssh.save_state(self.manager, {"sshd_pid": 1234, "target_app_pid": None})
        with mock.patch("codex_macos_ssh._owned_sshd_alive", return_value=True), mock.patch(
            "codex_macos_ssh._port_open", return_value=True
        ), mock.patch("codex_macos_ssh._connection_count", return_value=1):
            result = ssh.status(self.manager)
        self.assertEqual(result["connections"], 1)
        self.assertFalse(result["idle"])

    def test_sync_known_host_preserves_other_hosts_and_replaces_loopback(self):
        ssh_dir = self.manager / "ssh"
        ssh_dir.mkdir()
        (ssh_dir / "host_ed25519.pub").write_text(
            "ssh-ed25519 AAAACURRENT local-host\n", encoding="utf-8"
        )
        home = self.manager / "fake-home"
        known_hosts = home / ".ssh" / "known_hosts"
        known_hosts.parent.mkdir(parents=True)
        known_hosts.write_text(
            "example.com ssh-ed25519 AAAAOTHER\n"
            "[127.0.0.1]:2222 ssh-ed25519 AAAAOLD\n",
            encoding="utf-8",
        )

        def remove_host(args, timeout=20):
            host = args[3]
            lines = [
                line
                for line in known_hosts.read_text(encoding="utf-8").splitlines()
                if not line.startswith(host + " ")
            ]
            known_hosts.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("codex_macos_ssh.Path.home", return_value=home), mock.patch(
            "codex_macos_ssh._run", side_effect=remove_host
        ):
            ssh._sync_known_host(self.manager, 2222)

        content = known_hosts.read_text(encoding="utf-8")
        self.assertIn("example.com ssh-ed25519 AAAAOTHER", content)
        self.assertNotIn("AAAAOLD", content)
        self.assertIn("[127.0.0.1]:2222 ssh-ed25519 AAAACURRENT", content)
        self.assertTrue((ssh_dir / "known_hosts.before-local-ssh").is_file())

    def test_dispatch_uses_selected_home_and_embedded_runtime(self):
        home = self.manager / "home"
        home.mkdir()
        (home / "auth.json").write_text("{}", encoding="utf-8")
        codex = self.manager / "codex"
        codex.write_text("", encoding="utf-8")
        ssh.save_state(
            self.manager,
            {
                "running": True,
                "target_account": "target@example.invalid",
                "native_home": str(home),
                "native_codex_exe": str(codex),
            },
        )
        with mock.patch("codex_macos_ssh.os.execve", side_effect=RuntimeError("captured")) as execve:
            with self.assertRaisesRegex(RuntimeError, "captured"):
                ssh.dispatch(self.manager, ["--version"])
        args = execve.call_args.args
        self.assertEqual(args[0], str(codex.resolve()))
        self.assertEqual(args[1], [str(codex.resolve()), "--version"])
        self.assertEqual(args[2]["CODEX_HOME"], str(home.resolve()))
        self.assertEqual(args[2]["CODEX_MULTI_REMOTE_TARGET"], "target@example.invalid")

    def test_stop_only_terminates_owned_sshd(self):
        ssh.save_state(self.manager, {"sshd_pid": 1234, "running": True})
        with mock.patch("codex_macos_ssh._owned_sshd_alive", return_value=False), mock.patch(
            "codex_macos_ssh.os.kill"
        ) as kill:
            result = ssh.stop(self.manager)
        kill.assert_not_called()
        self.assertFalse(result["running"])
        self.assertIsNone(result["sshd_pid"])


if __name__ == "__main__":
    unittest.main()
