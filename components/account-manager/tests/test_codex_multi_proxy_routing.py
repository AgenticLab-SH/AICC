"""Proxy/app routing checks.

These cover the chain that decides whether the desktop app can use proxy-served
models at all: the app home's own `config.toml` must point at the proxy, and each
isolated account home must inherit that routing.
"""

import sys
import tempfile
import unittest
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(TOOL_ROOT))

import codex_multi as cm  # noqa: E402


class SetupStepOrderTests(unittest.TestCase):
    """`ocx login kiro` needs a running proxy, so `ocx start` must come first.

    Worth pinning: the reverse order reads plausible but fails, because the login
    is served by the running proxy's own management API.
    """

    def test_remaining_steps_are_printed_in_dependency_order(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        buf = io.StringIO()
        with mock.patch("codex_multi.shutil.which", return_value="/usr/local/bin/ocx"), \
                mock.patch("codex_multi._codex_command_version", return_value="1.0.0"), \
                mock.patch("codex_multi._codex_command", return_value="codex"), \
                mock.patch("codex_multi.find_codex_desktop_exe", return_value=None), \
                mock.patch("codex_multi._npm_latest_version", return_value=None), \
                mock.patch("codex_multi._run_text_command", return_value=(0, "1.0.0")), \
                mock.patch("codex_multi.proxy_is_healthy", return_value=False), \
                mock.patch("codex_multi.app_routing_target", return_value=None), \
                mock.patch("codex_multi.proxy_default_provider", return_value=None), \
                mock.patch("codex_multi.kiro_credential_source", return_value="none"), \
                mock.patch("codex_multi.proxy_codex_account_mode", return_value="direct"), \
                mock.patch("codex_multi.list_accounts", return_value=[]), \
                mock.patch("codex_multi.ensure_dirs"):
            with redirect_stdout(buf):
                cm.setup_command(["--check"])

        # Assert on the summary line only. Per-check hints above it also mention
        # these commands, so searching the whole output would match those first
        # and pass regardless of the real ordering.
        summary = next(
            (line for line in buf.getvalue().splitlines() if "남은 단계" in line),
            None,
        )
        self.assertIsNotNone(summary, "setup should print the remaining steps")
        self.assertIn("ocx start", summary)
        self.assertIn("ocx login kiro", summary)
        self.assertLess(
            summary.index("ocx start"),
            summary.index("ocx login kiro"),
            "the proxy must be started before the kiro login is attempted",
        )

    def test_setup_reports_pool_mode_without_rewriting_ocx(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        buf = io.StringIO()
        with mock.patch("codex_multi.shutil.which", side_effect=lambda name: f"/mock/{name}"), \
                mock.patch("codex_multi._npm_executable", return_value="/mock/npm"), \
                mock.patch("codex_multi._codex_command_version", return_value="1.0.0"), \
                mock.patch("codex_multi._codex_command", return_value="codex"), \
                mock.patch("codex_multi.find_codex_desktop_exe", return_value=Path("/mock/ChatGPT")), \
                mock.patch("codex_multi._npm_latest_version", return_value="2.7.42"), \
                mock.patch("codex_multi._run_text_command", return_value=(0, "2.7.42")) as run_text, \
                mock.patch("codex_multi.proxy_is_healthy", return_value=True), \
                mock.patch("codex_multi.app_routing_target", return_value="http://127.0.0.1:10100/v1"), \
                mock.patch("codex_multi.proxy_default_provider", return_value="kiro"), \
                mock.patch("codex_multi.kiro_credential_source", return_value="desktop"), \
                mock.patch("codex_multi.proxy_codex_account_mode", return_value="pool"), \
                mock.patch("codex_multi.list_accounts", return_value=["account@example.invalid"]), \
                mock.patch("codex_multi.resync_account_configs", return_value=0), \
                mock.patch("codex_multi.ensure_dirs"):
            with redirect_stdout(buf):
                cm.setup_command([])

        commands = [call.args[0] for call in run_text.call_args_list]
        self.assertFalse(any(command[1:3] == ["provider", "account-mode"] for command in commands))
        self.assertIn("pool — OCX가 새 작업의 계정을 선택", buf.getvalue())


class AppRoutingTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_home = cm.APP_CODEX_HOME
        cm.APP_CODEX_HOME = Path(self.tmp.name)

    def tearDown(self):
        cm.APP_CODEX_HOME = self.original_home
        self.tmp.cleanup()

    def write_config(self, text: str) -> None:
        (cm.APP_CODEX_HOME / "config.toml").write_text(text, encoding="utf-8")

    def test_missing_config_reports_no_routing(self):
        self.assertIsNone(cm.app_routing_target())

    def test_native_config_reports_no_routing(self):
        self.write_config('model = "gpt-5"\n')
        self.assertIsNone(cm.app_routing_target())

    def test_injected_base_url_is_reported(self):
        self.write_config(
            'model = "gpt-5"\n'
            "# Auto-injected by opencodex\n"
            'openai_base_url = "http://127.0.0.1:10100/v1"\n'
        )
        self.assertEqual(cm.app_routing_target(), "http://127.0.0.1:10100/v1")

    def test_commented_out_routing_is_not_reported(self):
        # A commented line means routing is disabled; treating it as active would
        # tell the user traffic is proxied when it is not.
        self.write_config('# openai_base_url = "http://127.0.0.1:10100/v1"\n')
        self.assertIsNone(cm.app_routing_target())


class AccountConfigResyncTests(unittest.TestCase):
    """A routing change in the app home must reach existing account homes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.originals = {
            name: getattr(cm, name)
            for name in ("APP_CODEX_HOME", "MANAGER_DIR", "ACCOUNTS_DIR", "HOMES_DIR",
                         "APP_PROFILES_DIR", "TRASH_DIR", "ORDER_FILE", "META_FILE",
                         "ACTIVE_CLI_FILE", "CLI_UPDATE_STATE_FILE")
        }
        cm.APP_CODEX_HOME = root / ".codex"
        cm.MANAGER_DIR = root / ".codex-multi"
        cm.ACCOUNTS_DIR = cm.MANAGER_DIR / "accounts"
        cm.HOMES_DIR = cm.MANAGER_DIR / "homes"
        cm.APP_PROFILES_DIR = cm.MANAGER_DIR / "app-profiles"
        cm.TRASH_DIR = cm.MANAGER_DIR / "_trash"
        cm.ORDER_FILE = cm.MANAGER_DIR / "order.json"
        cm.META_FILE = cm.MANAGER_DIR / "meta.json"
        cm.ACTIVE_CLI_FILE = cm.MANAGER_DIR / "active_cli.json"
        cm.CLI_UPDATE_STATE_FILE = cm.MANAGER_DIR / "cli-update.json"
        cm.APP_CODEX_HOME.mkdir(parents=True)
        cm.ensure_dirs()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(cm, name, value)
        self.tmp.cleanup()

    def test_new_account_home_inherits_proxy_routing(self):
        (cm.APP_CODEX_HOME / "config.toml").write_text(
            'openai_base_url = "http://127.0.0.1:10100/v1"\n', encoding="utf-8"
        )
        account = "teammate@example.invalid"
        cm.save_auth(account, {
            "auth_mode": "chatgpt",
            "tokens": {"account_id": "acct-teammate", "access_token": "t"},
        })

        home = cm.setup_isolated_home(account)

        self.assertIn(
            'openai_base_url = "http://127.0.0.1:10100/v1"',
            (home / "config.toml").read_text(encoding="utf-8"),
        )

    def test_resync_propagates_routing_added_after_account_creation(self):
        (cm.APP_CODEX_HOME / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
        account = "later@example.invalid"
        cm.save_auth(account, {
            "auth_mode": "chatgpt",
            "tokens": {"account_id": "acct-later", "access_token": "t"},
        })
        home = cm.setup_isolated_home(account)
        self.assertNotIn("openai_base_url", (home / "config.toml").read_text(encoding="utf-8"))

        # Proxy startup writes routing into the app home only.
        (cm.APP_CODEX_HOME / "config.toml").write_text(
            'model = "gpt-5"\nopenai_base_url = "http://127.0.0.1:10100/v1"\n',
            encoding="utf-8",
        )

        self.assertEqual(cm.resync_account_configs(), 1)
        self.assertIn(
            'openai_base_url = "http://127.0.0.1:10100/v1"',
            (home / "config.toml").read_text(encoding="utf-8"),
        )

    def test_resync_is_idempotent(self):
        (cm.APP_CODEX_HOME / "config.toml").write_text(
            'openai_base_url = "http://127.0.0.1:10100/v1"\n', encoding="utf-8"
        )
        account = "stable@example.invalid"
        cm.save_auth(account, {
            "auth_mode": "chatgpt",
            "tokens": {"account_id": "acct-stable", "access_token": "t"},
        })
        cm.setup_isolated_home(account)

        # Already current, so nothing should be rewritten.
        self.assertEqual(cm.resync_account_configs(), 0)


if __name__ == "__main__":
    unittest.main()
