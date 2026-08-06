import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT))

import codex_multi as cm  # noqa: E402


def fake_auth(account_id: str, token: str) -> dict:
    return {
        "auth_mode": "chatgpt",
        "tokens": {
            "account_id": account_id,
            "access_token": token,
        },
    }


class CodexMultiAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.originals = {
            name: getattr(cm, name)
            for name in (
                "APP_CODEX_HOME", "CODEX_HOME", "MANAGER_DIR", "ACCOUNTS_DIR",
                "HOMES_DIR", "APP_PROFILES_DIR", "TRASH_DIR", "ORDER_FILE",
                "META_FILE", "ACTIVE_CLI_FILE", "CLI_UPDATE_STATE_FILE",
                "SOURCE_DIR", "DEFAULT_MACOS_APP_PROFILE",
            )
        }
        cm.APP_CODEX_HOME = root / ".codex"
        cm.CODEX_HOME = cm.APP_CODEX_HOME
        cm.MANAGER_DIR = root / ".codex-multi"
        cm.ACCOUNTS_DIR = cm.MANAGER_DIR / "accounts"
        cm.HOMES_DIR = cm.MANAGER_DIR / "homes"
        cm.APP_PROFILES_DIR = cm.MANAGER_DIR / "app-profiles"
        cm.DEFAULT_MACOS_APP_PROFILE = root / "app-user-data"
        cm.TRASH_DIR = cm.MANAGER_DIR / "_trash"
        cm.ORDER_FILE = cm.MANAGER_DIR / "order.json"
        cm.META_FILE = cm.MANAGER_DIR / "meta.json"
        cm.ACTIVE_CLI_FILE = cm.MANAGER_DIR / "active_cli.json"
        cm.CLI_UPDATE_STATE_FILE = cm.MANAGER_DIR / "cli-update.json"
        cm.SOURCE_DIR = TOOL_ROOT
        cm.ensure_dirs()
        cm.APP_CODEX_HOME.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(cm, name, value)
        self.tmp.cleanup()

    def write_app_auth(self, data: dict):
        (cm.APP_CODEX_HOME / "auth.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def quiet(self, fn, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args, **kwargs)

    def test_auth_sync_runs_the_canonical_source_script(self):
        completed = mock.Mock(returncode=0)
        with mock.patch("codex_multi.subprocess.run", return_value=completed) as run:
            cm._cmd_auth_sync([])

        run.assert_called_once_with(
            [sys.executable, str(TOOL_ROOT.parent / "auth-portal" / "mac_sync.py")],
            check=False,
        )

    def test_import_app_adds_without_exposing_auth(self):
        data = fake_auth("acct-test-one", "fake-access-token-one")
        self.write_app_auth(data)
        result = self.quiet(cm.import_app_auth, "test@example.invalid")
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "added")
        self.assertEqual(cm.read_auth("test@example.invalid"), data)
        self.assertNotIn("auth", result)

    def test_appx_desktop_executable_uses_manifest_entrypoint(self):
        package = Path(self.tmp.name) / "OpenAI.Codex_1.2.3.4_x64__test"
        executable = package / "app" / "ChatGPT.exe"
        executable.parent.mkdir(parents=True)
        executable.touch()
        (package / "AppxManifest.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
            '<Applications><Application Id="App" Executable="app/ChatGPT.exe" '
            'EntryPoint="Windows.FullTrustApplication" /></Applications></Package>',
            encoding="utf-8",
        )

        self.assertEqual(cm._appx_desktop_executable(package), executable)

    def test_find_desktop_exe_does_not_use_undeclared_codex_helper(self):
        package = Path(self.tmp.name) / "OpenAI.Codex_9.8.7.6_x64__2p2nqsd0c76g0"
        declared = package / "app" / "ChatGPT.exe"
        helper = package / "app" / "Codex.exe"
        declared.parent.mkdir(parents=True)
        declared.touch()
        helper.touch()
        (package / "AppxManifest.xml").write_text(
            '<Package><Applications><Application Executable="app/ChatGPT.exe" />'
            '</Applications></Package>',
            encoding="utf-8",
        )

        with mock.patch.object(cm.sys, "platform", "win32"), mock.patch(
            "codex_multi._registered_codex_packages", return_value=[package]
        ):
            self.assertEqual(cm.find_codex_desktop_exe(), declared)

    def test_macos_app_kill_uses_bundle_id_without_powershell(self):
        bundle = Path(self.tmp.name) / "Codex.app"
        executable = bundle / "Contents" / "MacOS" / "ChatGPT"
        executable.parent.mkdir(parents=True)
        executable.touch()
        with (bundle / "Contents" / "Info.plist").open("wb") as handle:
            import plistlib
            plistlib.dump({"CFBundleIdentifier": "com.example.codex"}, handle)

        completed = mock.Mock(returncode=0)
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._is_codex_app_running", return_value=True
        ), mock.patch("codex_multi.subprocess.run", return_value=completed) as run:
            self.assertTrue(cm._kill_codex_app())

        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["osascript", "-e"])
        self.assertIn("com.example.codex", command[2])
        self.assertNotIn("powershell", " ".join(command).lower())

    def test_macos_app_start_forces_new_default_instance(self):
        bundle = Path(self.tmp.name) / "Codex.app"
        executable = bundle / "Contents" / "MacOS" / "ChatGPT"
        executable.parent.mkdir(parents=True)
        executable.touch()
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch("codex_multi.subprocess.Popen") as popen:
            cm._start_codex_app()

        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        # Without -n, LaunchServices only activates a running per-account
        # instance and the default App never restarts after an auth swap.
        self.assertEqual(command[:3], ["open", "-n", str(bundle)])
        self.assertIn(f"CODEX_HOME={cm.APP_CODEX_HOME}", command)
        self.assertIn(
            f"CODEX_ELECTRON_USER_DATA_PATH={cm.DEFAULT_MACOS_APP_PROFILE}",
            command,
        )
        self.assertNotIn("--user-data-dir", " ".join(command))
        self.assertEqual(environment["CODEX_HOME"], str(cm.APP_CODEX_HOME))
        self.assertEqual(
            environment["CODEX_ELECTRON_USER_DATA_PATH"],
            str(cm.DEFAULT_MACOS_APP_PROFILE),
        )

    def test_macos_default_app_start_drops_isolated_codex_environment(self):
        bundle = Path(self.tmp.name) / "Codex.app"
        executable = bundle / "Contents" / "MacOS" / "ChatGPT"
        executable.parent.mkdir(parents=True)
        executable.touch()
        inherited = {
            "PATH": "/usr/bin",
            "CODEX_HOME": "/tmp/isolated-home",
            "CODEX_ELECTRON_USER_DATA_PATH": "/tmp/isolated-profile",
            "CODEX_MULTI_ACCOUNT_NAME": "isolated@example.invalid",
            "CODEX_SQLITE_HOME": "/tmp/isolated-sqlite",
            "CODEX_THREAD_ID": "thread-from-calling-app",
            "OPENAI_API_KEY": "must-not-reach-desktop",
        }
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch.dict(cm.os.environ, inherited, clear=True), mock.patch(
            "codex_multi.subprocess.Popen"
        ) as popen:
            cm._start_codex_app()

        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment, {
            "PATH": "/usr/bin",
            "CODEX_HOME": str(cm.APP_CODEX_HOME),
            "CODEX_ELECTRON_USER_DATA_PATH": str(cm.DEFAULT_MACOS_APP_PROFILE),
        })

    def test_macos_process_detection_matches_exact_executable(self):
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        process_list = mock.Mock(
            stdout=(
                f" 101 {executable}\n"
                f" 102 {executable} --profile secondary\n"
                " 103 /Applications/Other.app/Contents/MacOS/ChatGPT\n"
            ),
            returncode=0,
        )
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch("codex_multi.subprocess.run", return_value=process_list):
            self.assertEqual(cm._macos_codex_pids(), [101, 102])
            self.assertTrue(cm._is_codex_app_running())

    def test_windows_powershell_prefers_pwsh_7(self):
        with mock.patch.object(cm.os, "name", "nt"), mock.patch(
            "codex_multi.shutil.which",
            side_effect=lambda name: r"C:\\Program Files\\PowerShell\\7\\pwsh.exe"
            if name == "pwsh" else r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        ):
            self.assertEqual(
                cm._windows_powershell_executable(),
                r"C:\\Program Files\\PowerShell\\7\\pwsh.exe",
            )

    def test_app_exit_wait_is_platform_neutral(self):
        with mock.patch(
            "codex_multi._is_codex_app_running", side_effect=[True, False]
        ), mock.patch(
            "codex_multi._database_open_pids", side_effect=[[811], []]
        ), mock.patch("codex_multi.time.sleep"):
            self.quiet(cm._wait_codex_app_exit, timeout=1)

    def test_app_exit_waits_for_orphaned_app_server_database_user(self):
        with mock.patch(
            "codex_multi._is_codex_app_running", return_value=False
        ), mock.patch(
            "codex_multi._database_open_pids", side_effect=[[812], []]
        ) as database_users, mock.patch("codex_multi.time.sleep"):
            self.quiet(cm._wait_codex_app_exit, timeout=1)

        self.assertEqual(database_users.call_count, 2)

    def test_switch_rolls_back_auth_when_app_restart_fails(self):
        old_auth = fake_auth("acct-old", "old-token")
        new_auth = fake_auth("acct-new", "new-token")
        self.write_app_auth(old_auth)
        cm.save_auth("new@example.invalid", new_auth)

        with mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=Path("/fake/Codex")
        ), mock.patch(
            "codex_multi._kill_codex_app", return_value=False
        ), mock.patch(
            "codex_multi._start_codex_app", side_effect=RuntimeError("launch failed")
        ), mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch("codex_multi.notify_account_change") as notify:
            self.quiet(cm.switch_account, "new@example.invalid")

        restored = json.loads((cm.APP_CODEX_HOME / "auth.json").read_text(encoding="utf-8"))
        self.assertEqual(restored, old_auth)
        notify.assert_not_called()

    def _macos_process_list(self, executable: Path, isolated_profile: Path):
        return mock.Mock(
            stdout=(
                f" 201 {executable}\n"
                f" 202 {executable} --user-data-dir={isolated_profile}\n"
            ),
            returncode=0,
        )

    def test_default_app_detection_ignores_per_account_instances(self):
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        profile = cm.APP_PROFILES_DIR / "acct-key"
        process_list = self._macos_process_list(executable, profile)
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch("codex_multi.subprocess.run", return_value=process_list):
            self.assertEqual(cm._macos_default_app_pids(), [201])
            self.assertEqual(cm._macos_isolated_app_pids(), [202])
            self.assertEqual(cm._macos_codex_pids(), [201, 202])

    def test_app_running_check_ignores_per_account_instances(self):
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        profile = cm.APP_PROFILES_DIR / "acct-key"
        only_isolated = mock.Mock(
            stdout=f" 202 {executable} --user-data-dir={profile}\n", returncode=0
        )
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch("codex_multi.subprocess.run", return_value=only_isolated):
            # A per-account App must never make the global switch wait or quit.
            self.assertFalse(cm._is_codex_app_running())
            self.quiet(cm._wait_codex_app_exit, timeout=1)

    def test_kill_app_signals_only_default_instance(self):
        bundle = Path(self.tmp.name) / "Codex.app"
        executable = bundle / "Contents" / "MacOS" / "ChatGPT"
        executable.parent.mkdir(parents=True)
        executable.touch()
        with (bundle / "Contents" / "Info.plist").open("wb") as handle:
            import plistlib
            plistlib.dump({"CFBundleIdentifier": "com.example.codex"}, handle)

        profile = cm.APP_PROFILES_DIR / "acct-key"
        process_list = self._macos_process_list(executable, profile)
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi.subprocess.run", return_value=process_list
        ), mock.patch("codex_multi.os.kill") as kill:
            self.assertTrue(cm._kill_codex_app())

        # A bundle-ID quit would also close the per-account instance.
        self.assertEqual([call.args[0] for call in kill.call_args_list], [201])

    def test_switch_keeps_new_auth_when_app_pid_is_unconfirmed(self):
        old_auth = fake_auth("acct-old", "old-token")
        new_auth = fake_auth("acct-new", "new-token")
        self.write_app_auth(old_auth)
        cm.save_auth("new@example.invalid", new_auth)

        with mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=Path("/fake/Codex")
        ), mock.patch(
            "codex_multi._kill_codex_app", return_value=True
        ), mock.patch("codex_multi._wait_codex_app_exit"), mock.patch(
            "codex_multi._start_codex_app"
        ), mock.patch(
            "codex_multi._wait_for_default_app_pid", return_value=None
        ), mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch("codex_multi.notify_account_change") as notify:
            self.quiet(cm.switch_account, "new@example.invalid")

        live = json.loads((cm.APP_CODEX_HOME / "auth.json").read_text(encoding="utf-8"))
        self.assertEqual(live, new_auth)
        notify.assert_called_once()

    def test_switch_reports_untouched_per_account_instances(self):
        self.write_app_auth(fake_auth("acct-old", "old-token"))
        cm.save_auth("new@example.invalid", fake_auth("acct-new", "new-token"))

        with mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=Path("/fake/Codex")
        ), mock.patch(
            "codex_multi._isolated_app_pids", return_value=[202, 203]
        ), mock.patch(
            "codex_multi._kill_codex_app", return_value=False
        ), mock.patch("codex_multi._start_codex_app"), mock.patch(
            "codex_multi._wait_for_default_app_pid", return_value=999
        ), mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch("codex_multi.notify_account_change"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cm.switch_account("new@example.invalid")

        self.assertIn("계정별 App 2개", out.getvalue())

    def test_sync_command_names_track_every_alias(self):
        names = cm.sync_command_names()
        for alias in ("s", "c", "o", "switch", "cli", "app", "ca", ""):
            self.assertIn(alias, names)

    def test_short_aliases_resolve_to_launch_commands(self):
        self.assertEqual(cm.find_command("s")["names"][0], "switch")
        self.assertEqual(cm.find_command("c")["names"][0], "cli")
        self.assertEqual(cm.find_command("o")["names"][0], "app")

    def test_unknown_command_is_reported(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaisesRegex(SystemExit, "2"):
                cm.dispatch_command(["nope"])
        self.assertIn("알 수 없는 명령: nope", out.getvalue())

    def test_shared_config_reports_external_endpoint_and_foreign_home(self):
        cm.save_auth("one@example.invalid", fake_auth("acct-one", "token-one"))
        cm.save_auth("two@example.invalid", fake_auth("acct-two", "token-two"))
        other_key = cm.stable_account_key("two@example.invalid")
        (cm.APP_CODEX_HOME / "config.toml").write_text(
            'openai_base_url = "http://127.0.0.1:10100/v1"\n'
            f'notify = ["{cm.HOMES_DIR / other_key}/hook"]\n',
            encoding="utf-8",
        )

        info = cm.shared_config_conflicts("one@example.invalid")
        self.assertEqual(info["external_base_urls"], ["http://127.0.0.1:10100/v1"])
        self.assertEqual(info["pinned_accounts"], ["two@example.invalid"])

    def test_shared_config_ignores_official_endpoint_and_own_home(self):
        cm.save_auth("one@example.invalid", fake_auth("acct-one", "token-one"))
        own_key = cm.stable_account_key("one@example.invalid")
        (cm.APP_CODEX_HOME / "config.toml").write_text(
            'openai_base_url = "https://api.openai.com/v1"\n'
            f'notify = ["{cm.HOMES_DIR / own_key}/hook"]\n',
            encoding="utf-8",
        )

        info = cm.shared_config_conflicts("one@example.invalid")
        self.assertEqual(info["external_base_urls"], [])
        self.assertEqual(info["pinned_accounts"], [])

    def test_matching_app_auth_updates_existing_record(self):
        cm.save_auth("known@example.invalid", fake_auth("acct-same", "old-token"))
        self.write_app_auth(fake_auth("acct-same", "new-token"))
        result = cm.sync_matching_app_auth()
        self.assertEqual(result["target"], "known@example.invalid")
        self.assertEqual(result["action"], "updated")
        self.assertEqual(
            cm.read_auth("known@example.invalid")["tokens"]["access_token"],
            "new-token",
        )
        self.assertEqual(len(cm.list_accounts()), 1)

    def test_duplicate_account_id_requires_unambiguous_target(self):
        cm.save_auth("first@example.invalid", fake_auth("acct-duplicate", "old-one"))
        cm.save_auth("second@example.invalid", fake_auth("acct-duplicate", "old-two"))
        self.write_app_auth(fake_auth("acct-duplicate", "new-token"))
        original = cm.resolve_email
        cm.resolve_email = lambda _auth: None
        try:
            ambiguous = self.quiet(cm.import_app_auth, dry_run=True)
            explicit = self.quiet(
                cm.import_app_auth,
                "first@example.invalid",
                dry_run=True,
            )
        finally:
            cm.resolve_email = original
        self.assertFalse(ambiguous["ok"])
        self.assertEqual(ambiguous["error"], "duplicate_account_id")
        self.assertTrue(explicit["ok"])
        self.assertEqual(explicit["target"], "first@example.invalid")

    def test_automatic_sync_refuses_duplicate_account_id(self):
        cm.save_auth("first@example.invalid", fake_auth("acct-duplicate", "old-one"))
        cm.save_auth("second@example.invalid", fake_auth("acct-duplicate", "old-two"))
        self.write_app_auth(fake_auth("acct-duplicate", "new-token"))
        result = cm.sync_matching_app_auth()
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "duplicate_account_id")
        self.assertEqual(
            cm.read_auth("first@example.invalid")["tokens"]["access_token"],
            "old-one",
        )

    def test_active_account_uses_exact_token_before_duplicate_account_id(self):
        first = fake_auth("acct-duplicate", "first-token")
        second = fake_auth("acct-duplicate", "second-token")
        cm.save_auth("first@example.invalid", first)
        cm.save_auth("second@example.invalid", second)
        self.write_app_auth(second)

        self.assertEqual(cm.get_active_account(), "second@example.invalid")

    def test_active_account_does_not_guess_ambiguous_account_id(self):
        cm.save_auth("first@example.invalid", fake_auth("acct-duplicate", "first-token"))
        cm.save_auth("second@example.invalid", fake_auth("acct-duplicate", "second-token"))
        self.write_app_auth(fake_auth("acct-duplicate", "third-token"))

        self.assertIsNone(cm.get_active_account())

    def test_duplicate_account_ids_get_distinct_home_keys(self):
        cm.save_auth("first@example.invalid", fake_auth("acct-duplicate", "first-token"))
        cm.save_auth("second@example.invalid", fake_auth("acct-duplicate", "second-token"))

        first_key = cm.stable_account_key("first@example.invalid")
        second_key = cm.stable_account_key("second@example.invalid")

        self.assertNotEqual(first_key, second_key)
        self.assertTrue(first_key.startswith("acct-duplicate-"))
        self.assertTrue(second_key.startswith("acct-duplicate-"))

    def test_current_calling_app_account_uses_inherited_isolated_home(self):
        first = "first@example.invalid"
        second = "second@example.invalid"
        cm.save_auth(first, fake_auth("acct-first", "first-token"))
        cm.save_auth(second, fake_auth("acct-second", "second-token"))
        isolated = cm.HOMES_DIR / "caller"
        isolated.mkdir(parents=True)
        (isolated / "auth.json").write_text(
            json.dumps(fake_auth("acct-second", "second-token")),
            encoding="utf-8",
        )
        with mock.patch.object(cm, "INHERITED_CODEX_HOME", str(isolated)):
            self.assertEqual(cm.current_calling_app_account([first, second]), second)

    def test_remote_uses_target_home_without_launching_duplicate_app(self):
        current = "current@example.invalid"
        target = "target@example.invalid"
        cm.save_auth(current, fake_auth("acct-current", "current-token"))
        cm.save_auth(target, fake_auth("acct-target", "target-token"))
        self.write_app_auth(fake_auth("acct-current", "current-token"))
        runtime = Path(self.tmp.name) / "codex"
        runtime.touch()
        backend = mock.Mock()
        backend.status.return_value = {"ssh_active": False, "target_account": None}
        backend.start_for_account.return_value = {"running": True}

        with mock.patch("codex_multi.find_codex_runtime_exe", return_value=runtime), mock.patch(
            "codex_multi._remote_backend", return_value=backend
        ), mock.patch(
            "codex_multi.thread_home_activity", return_value={"active": False}
        ), mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch(
            "codex_multi.launch_app_account"
        ) as launch_app, mock.patch("codex_multi.show_remote_status", return_value={}):
            result = self.quiet(cm.start_account_remote, target)

        self.assertEqual(result, {"running": True})
        launch_app.assert_not_called()
        self.assertIsNone(backend.start_for_account.call_args.kwargs["app_pid"])

    def test_duplicate_app_auth_sync_uses_resolved_server_email(self):
        cm.save_auth("first@example.invalid", fake_auth("acct-duplicate", "old-one"))
        cm.save_auth("second@example.invalid", fake_auth("acct-duplicate", "old-two"))
        self.write_app_auth(fake_auth("acct-duplicate", "live-first"))

        with mock.patch("codex_multi.resolve_email", return_value="first@example.invalid"):
            result = cm.sync_matching_app_auth()

        self.assertTrue(result["ok"])
        self.assertEqual(result["target"], "first@example.invalid")
        self.assertEqual(
            cm.read_auth("first@example.invalid")["tokens"]["access_token"],
            "live-first",
        )
        self.assertEqual(
            cm.read_auth("second@example.invalid")["tokens"]["access_token"],
            "old-two",
        )

    def test_remote_rows_use_live_app_auth_override(self):
        cm.save_auth("first@example.invalid", fake_auth("acct-one", "stored-token"))
        live = fake_auth("acct-one", "live-token")
        with mock.patch("codex_multi.fetch_quota", return_value={"ok": True}) as quota, mock.patch(
            "codex_multi.fetch_reset_credits", return_value={"ok": True}
        ) as credits:
            cm.fetch_account_remote_rows(
                ["first@example.invalid"],
                auth_overrides={"first@example.invalid": live},
            )

        quota.assert_called_once_with(live, account_name="first@example.invalid")
        credits.assert_called_once_with(live, account_name="first@example.invalid")

    def test_import_dry_run_does_not_write(self):
        self.write_app_auth(fake_auth("acct-dry-run", "dry-token"))
        result = self.quiet(
            cm.import_app_auth,
            "dry@example.invalid",
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(cm.get_auth_path("dry@example.invalid").exists())

    def test_app_dry_run_path_build_does_not_create_home_or_profile(self):
        cm.save_auth("dry-app@example.invalid", fake_auth("acct-app-dry", "token"))
        _env, home, profile = cm.build_app_account_env(
            "dry-app@example.invalid", prepare=False
        )
        self.assertFalse(home.exists())
        self.assertFalse(profile.exists())

    def test_posix_app_launch_detaches_from_tui_terminal_session(self):
        account = "app-session@example.invalid"
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        cm.save_auth(account, fake_auth("acct-app-session", "token"))
        process = mock.Mock(pid=4321)

        with mock.patch.object(cm.os, "name", "posix"), mock.patch.object(
            cm.sys, "platform", "linux"
        ), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi.subprocess.Popen", return_value=process
        ) as popen, mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch("codex_multi.notify_account_change"):
            result = self.quiet(cm.launch_app_account, account)

        self.assertIs(result, process)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("creationflags", popen.call_args.kwargs)
        self.assertIs(popen.call_args.kwargs["stdin"], cm.subprocess.DEVNULL)

    def test_macos_app_launch_uses_open_new_instance_and_real_profile_pid(self):
        account = "app-macos@example.invalid"
        bundle = Path("/Applications/ChatGPT.app")
        executable = bundle / "Contents" / "MacOS" / "ChatGPT"
        cm.save_auth(account, fake_auth("acct-app-macos", "token"))

        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._macos_app_profile_pids", return_value=[]
        ), mock.patch(
            "codex_multi._wait_for_macos_app_profile_pid", return_value=9876
        ), mock.patch(
            "codex_multi._activate_macos_app_pid", return_value=True
        ) as activate, mock.patch(
            "codex_multi.subprocess.Popen"
        ) as popen, mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ) as sync_threads, mock.patch("codex_multi.notify_account_change") as notify:
            result = self.quiet(cm.launch_app_account, account)

        self.assertEqual(result, 9876)
        command = popen.call_args.args[0]
        self.assertEqual(command[:4], ["open", "-n", "-a", str(bundle)])
        self.assertIn(f"CODEX_HOME={cm.HOMES_DIR / cm.stable_account_key(account)}", command)
        self.assertIn(
            f"--user-data-dir={cm.APP_PROFILES_DIR / cm.stable_account_key(account)}",
            command,
        )
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        sync_threads.assert_called_once_with(
            account,
            home=cm.HOMES_DIR / cm.stable_account_key(account),
        )
        activate.assert_called_once_with(9876)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.kwargs["pid"], 9876)

    def test_macos_existing_profile_activates_exact_pid_without_relaunch(self):
        account = "app-macos-existing@example.invalid"
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        cm.save_auth(account, fake_auth("acct-app-macos-existing", "token"))

        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._macos_app_profile_pids", return_value=[8765]
        ), mock.patch(
            "codex_multi._activate_macos_app_pid", return_value=True
        ) as activate, mock.patch(
            "codex_multi._macos_app_window_count", return_value=2
        ), mock.patch(
            "codex_multi.subprocess.Popen"
        ) as popen, mock.patch("codex_multi.notify_account_change"):
            result = self.quiet(cm.launch_app_account, account)

        self.assertEqual(result, 8765)
        activate.assert_called_once_with(8765)
        popen.assert_not_called()

    def test_macos_windowless_instance_is_restarted_not_just_activated(self):
        account = "app-macos-windowless@example.invalid"
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        cm.save_auth(account, fake_auth("acct-app-windowless", "token"))

        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._macos_app_profile_pids", side_effect=[[8765], []]
        ), mock.patch(
            "codex_multi._activate_macos_app_pid", return_value=True
        ), mock.patch(
            "codex_multi._macos_app_window_count", return_value=0
        ), mock.patch(
            "codex_multi._terminate_pids", return_value=True
        ) as terminate, mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch(
            "codex_multi._wait_for_macos_app_profile_pid", return_value=9999
        ), mock.patch("codex_multi.subprocess.Popen") as popen, mock.patch(
            "codex_multi.notify_account_change"
        ):
            result = self.quiet(cm.launch_app_account, account)

        # Only this account's instance may be terminated, then relaunched.
        terminate.assert_called_once_with([8765])
        popen.assert_called_once()
        self.assertEqual(result, 9999)

    def test_explicit_restart_skips_activation_entirely(self):
        account = "app-macos-forced@example.invalid"
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        cm.save_auth(account, fake_auth("acct-app-forced", "token"))

        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._macos_app_profile_pids", side_effect=[[8765], []]
        ), mock.patch(
            "codex_multi._activate_macos_app_pid"
        ) as activate, mock.patch(
            "codex_multi._terminate_pids", return_value=True
        ) as terminate, mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch(
            "codex_multi._wait_for_macos_app_profile_pid", return_value=4321
        ), mock.patch("codex_multi.subprocess.Popen"), mock.patch(
            "codex_multi.notify_account_change"
        ):
            result = self.quiet(cm.launch_app_account, account, restart=True)

        # The stale instance is never activated; only the fresh one is.
        self.assertEqual([call.args for call in activate.call_args_list], [(4321,)])
        terminate.assert_called_once_with([8765])
        self.assertEqual(result, 4321)

    def test_app_command_parses_restart_flag_without_passing_it_through(self):
        with mock.patch("codex_multi.launch_app_account") as launch:
            cm._cmd_app(["2", "--restart"])
        self.assertEqual(launch.call_args.args, ("2", []))
        self.assertTrue(launch.call_args.kwargs["restart"])

    def test_macos_restart_aborts_when_instance_will_not_exit(self):
        account = "app-macos-stuck@example.invalid"
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        cm.save_auth(account, fake_auth("acct-app-stuck", "token"))

        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._macos_app_profile_pids", return_value=[8765]
        ), mock.patch(
            "codex_multi._activate_macos_app_pid", return_value=False
        ), mock.patch(
            "codex_multi._macos_app_window_count", return_value=None
        ), mock.patch(
            "codex_multi._terminate_pids", return_value=False
        ), mock.patch("codex_multi.subprocess.Popen") as popen:
            result = self.quiet(cm.launch_app_account, account)

        self.assertIsNone(result)
        popen.assert_not_called()

    def test_isolated_home_gets_private_config_with_retargeted_paths(self):
        account = "cfg-owner@example.invalid"
        other = "cfg-other@example.invalid"
        cm.save_auth(account, fake_auth("acct-cfg-owner", "token-owner"))
        cm.save_auth(other, fake_auth("acct-cfg-other", "token-other"))
        other_home = cm.HOMES_DIR / cm.stable_account_key(other)
        (cm.APP_CODEX_HOME / "config.toml").write_text(
            f'notify = ["{other_home}/hook"]\n', encoding="utf-8"
        )

        home = cm.setup_isolated_home(account)
        config = home / "config.toml"
        self.assertFalse(config.is_symlink())
        self.assertIn(str(home), config.read_text(encoding="utf-8"))
        self.assertNotIn(str(other_home), config.read_text(encoding="utf-8"))

    def test_isolated_home_replaces_legacy_config_symlink(self):
        account = "cfg-legacy@example.invalid"
        cm.save_auth(account, fake_auth("acct-cfg-legacy", "token"))
        master = cm.APP_CODEX_HOME / "config.toml"
        master.write_text('model = "gpt-5"\n', encoding="utf-8")
        home = cm.HOMES_DIR / cm.stable_account_key(account)
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.toml").symlink_to(master)

        cm.setup_isolated_home(account)
        config = home / "config.toml"
        self.assertFalse(config.is_symlink())
        self.assertEqual(config.read_text(encoding="utf-8"), 'model = "gpt-5"\n')

    def test_isolated_home_owns_atomic_global_state_copy(self):
        account = "state-owner@example.invalid"
        cm.save_auth(account, fake_auth("acct-state-owner", "token"))
        master = cm.APP_CODEX_HOME / ".codex-global-state.json"
        master.write_text(
            json.dumps({"local-projects": {"one": {"rootPaths": ["/workspace"]}}}),
            encoding="utf-8",
        )
        home = cm.HOMES_DIR / cm.stable_account_key(account)
        home.mkdir(parents=True, exist_ok=True)
        (home / ".codex-global-state.json").symlink_to(master)

        cm.setup_isolated_home(account)
        state = home / ".codex-global-state.json"

        self.assertFalse(state.is_symlink())
        self.assertEqual(json.loads(state.read_text(encoding="utf-8")), json.loads(master.read_text(encoding="utf-8")))

    def test_isolated_home_shares_active_and_archived_rollouts(self):
        account = "history-owner@example.invalid"
        cm.save_auth(account, fake_auth("acct-history-owner", "token"))
        sessions = cm.APP_CODEX_HOME / "sessions"
        archived = cm.APP_CODEX_HOME / "archived_sessions"
        sessions.mkdir()
        archived.mkdir()

        home = cm.setup_isolated_home(account)

        self.assertTrue((home / "sessions").is_symlink())
        self.assertTrue((home / "archived_sessions").is_symlink())
        self.assertEqual((home / "sessions").resolve(), sessions.resolve())
        self.assertEqual((home / "archived_sessions").resolve(), archived.resolve())

    def test_proxy_pool_report_keeps_ocx_account_ids_private(self):
        accounts = [
            {"id": cm.PROXY_MAIN_ACCOUNT_ID},
            {"id": "private-pool-account-id"},
        ]
        output = io.StringIO()
        with mock.patch("codex_multi.proxy_account_pool", return_value=accounts), \
                contextlib.redirect_stdout(output):
            cm.print_proxy_account_pool()

        self.assertIn("OCX 관리 계정 1개", output.getvalue())
        self.assertNotIn("private-pool-account-id", output.getvalue())

    def test_routing_warning_does_not_label_an_unrelated_gateway_as_ocx(self):
        account = "routing-owner@example.invalid"
        cm.save_auth(account, fake_auth("acct-routing", "token"))
        home = cm.HOMES_DIR / cm.stable_account_key(account)
        home.mkdir(parents=True)
        (home / "config.toml").write_text(
            'openai_base_url = "http://127.0.0.1:17841/v1"\n',
            encoding="utf-8",
        )
        output = io.StringIO()
        with mock.patch("codex_multi.proxy_codex_account_mode", return_value="pool") as mode, \
                contextlib.redirect_stdout(output):
            cm.warn_shared_config_conflicts(account)

        self.assertIn("OCX가 아닌", output.getvalue())
        self.assertNotIn("OCX pool", output.getvalue())
        mode.assert_not_called()

    def test_routing_warning_labels_the_exact_ocx_endpoint(self):
        account = "ocx-routing-owner@example.invalid"
        cm.save_auth(account, fake_auth("acct-ocx-routing", "token"))
        home = cm.HOMES_DIR / cm.stable_account_key(account)
        home.mkdir(parents=True)
        (home / "config.toml").write_text(
            'openai_base_url = "http://127.0.0.1:10100/v1"\n',
            encoding="utf-8",
        )
        output = io.StringIO()
        with mock.patch("codex_multi.proxy_codex_account_mode", return_value="pool"), \
                contextlib.redirect_stdout(output):
            cm.warn_shared_config_conflicts(account)

        self.assertIn("OCX pool", output.getvalue())

    def test_app_launch_preserves_active_home_instead_of_second_writer(self):
        account = "app-active-home@example.invalid"
        executable = Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT")
        cm.save_auth(account, fake_auth("acct-active-home", "token"))
        with mock.patch.object(cm.sys, "platform", "darwin"), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._macos_app_profile_pids", return_value=[]
        ), mock.patch(
            "codex_multi.sync_thread_index", return_value={"reason": "home_active"}
        ), mock.patch("codex_multi.subprocess.Popen") as popen:
            result = self.quiet(cm.launch_app_account, account)
        self.assertIsNone(result)
        popen.assert_not_called()

    def test_windows_app_launch_keeps_detached_creation_flags(self):
        account = "app-windows@example.invalid"
        executable = Path("C:/Program Files/WindowsApps/OpenAI.Codex/app/ChatGPT.exe")
        cm.save_auth(account, fake_auth("acct-app-windows", "token"))
        process = mock.Mock(pid=5432)
        working_dir = Path(self.tmp.name)

        with mock.patch.object(cm.os, "name", "nt"), mock.patch.object(
            cm.sys, "platform", "win32"
        ), mock.patch.object(
            cm.subprocess, "CREATE_NEW_PROCESS_GROUP", 1, create=True
        ), mock.patch.object(
            cm.subprocess, "DETACHED_PROCESS", 2, create=True
        ), mock.patch.object(
            cm.Path, "home", return_value=working_dir
        ), mock.patch(
            "codex_multi.find_codex_desktop_exe", return_value=executable
        ), mock.patch(
            "codex_multi._windows_app_profile_pids", return_value=[]
        ), mock.patch(
            "codex_multi.sync_thread_index", return_value={"ok": True}
        ), mock.patch(
            "codex_multi.subprocess.Popen", return_value=process
        ) as popen, mock.patch("codex_multi.notify_account_change"):
            result = self.quiet(cm.launch_app_account, account)

        self.assertIs(result, process)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 3)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)

    def test_bounded_login_success_uses_target_home(self):
        target = cm.HOMES_DIR / "_tmp_test_success"
        target.mkdir(parents=True)
        code = (
            "import json,os,pathlib;"
            "p=pathlib.Path(os.environ['CODEX_HOME']);"
            "p.mkdir(parents=True,exist_ok=True);"
            "(p/'auth.json').write_text(json.dumps({'tokens':{'account_id':'acct-ok',"
            "'access_token':'fake'}}),encoding='utf-8')"
        )
        result = self.quiet(
            cm.run_codex_login,
            target,
            command=[sys.executable, "-c", code],
            timeout_seconds=5,
        )
        self.assertEqual(result, 0)
        self.assertTrue((target / "auth.json").exists())

    def test_default_login_uses_device_auth_and_browser_is_opt_in(self):
        device = cm._login_command()
        browser = cm._login_command(use_browser=True)
        self.assertEqual(device[-2:], ["login", "--device-auth"])
        self.assertEqual(browser[-1], "login")
        self.assertNotIn("--device-auth", browser)

    def test_device_login_has_no_shorter_local_timeout_by_default(self):
        with mock.patch.dict(cm.os.environ, {}, clear=True):
            self.assertIsNone(cm._login_timeout_seconds())
            self.assertEqual(
                cm._login_timeout_seconds(use_browser=True),
                cm.DEFAULT_LOGIN_TIMEOUT_SECONDS,
            )

        with mock.patch.dict(
            cm.os.environ,
            {"CM_LOGIN_TIMEOUT_SECONDS": "unlimited"},
            clear=True,
        ):
            self.assertIsNone(cm._login_timeout_seconds(use_browser=True))

    def test_persistent_device_login_reissues_until_success(self):
        target = cm.HOMES_DIR / "_tmp_test_persistent"
        target.mkdir(parents=True)
        with mock.patch("codex_multi.run_codex_login", side_effect=[1, 0]) as login, mock.patch(
            "codex_multi._login_retry_delay_seconds", return_value=1
        ), mock.patch("codex_multi.time.sleep"):
            result = self.quiet(cm.run_codex_login_persistent, target)

        self.assertEqual(result, 0)
        self.assertEqual(login.call_count, 2)

    def test_add_command_is_persistent_unless_once_or_browser(self):
        with mock.patch("codex_multi.add_account") as add:
            cm._cmd_add([])
            add.assert_called_once_with(use_browser=False, persistent=True)

        with mock.patch("codex_multi.add_account") as add:
            cm._cmd_add(["--once"])
            add.assert_called_once_with(use_browser=False, persistent=False)

        with mock.patch("codex_multi.add_account") as add:
            cm._cmd_add(["--browser"])
            add.assert_called_once_with(use_browser=True, persistent=False)

    def test_newer_isolated_refresh_tokens_are_promoted_to_store(self):
        name = "refresh@example.invalid"
        stored = fake_auth("acct-refresh", "old-access")
        stored["last_refresh"] = "2026-07-18T00:00:00Z"
        cm.save_auth(name, stored)

        home_auth = fake_auth("acct-refresh", "new-access")
        home_auth["tokens"]["refresh_token"] = "new-refresh"
        home_auth["last_refresh"] = "2026-07-18T01:00:00Z"
        home = cm.HOMES_DIR / cm.stable_account_key(name)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(json.dumps(home_auth), encoding="utf-8")

        self.assertTrue(cm.sync_isolated_home_auth(name))
        self.assertEqual(
            cm.read_auth(name)["tokens"]["refresh_token"],
            "new-refresh",
        )

    def test_isolated_auth_for_another_account_is_not_promoted(self):
        name = "safe@example.invalid"
        stored = fake_auth("acct-safe", "safe-access")
        stored["last_refresh"] = "2026-07-18T00:00:00Z"
        cm.save_auth(name, stored)

        other = fake_auth("acct-other", "other-access")
        other["last_refresh"] = "2026-07-18T01:00:00Z"
        home = cm.HOMES_DIR / cm.stable_account_key(name)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(json.dumps(other), encoding="utf-8")

        self.assertFalse(cm.sync_isolated_home_auth(name))
        self.assertEqual(cm.read_auth(name)["tokens"]["account_id"], "acct-safe")

    def test_duplicate_id_home_requires_matching_server_identity(self):
        first = "first@example.invalid"
        second = "second@example.invalid"
        stored = fake_auth("acct-duplicate", "stored-first")
        stored["last_refresh"] = "2026-07-18T00:00:00Z"
        cm.save_auth(first, stored)
        cm.save_auth(second, fake_auth("acct-duplicate", "stored-second"))

        wrong_home = fake_auth("acct-duplicate", "wrong-newer")
        wrong_home["last_refresh"] = "2026-07-18T01:00:00Z"
        home = cm.HOMES_DIR / cm.stable_account_key(first)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(json.dumps(wrong_home), encoding="utf-8")

        with mock.patch("codex_multi.resolve_email", return_value=second):
            self.assertFalse(cm.sync_isolated_home_auth(first))
        self.assertEqual(cm.read_auth(first)["tokens"]["access_token"], "stored-first")

    def test_bounded_login_times_out_and_returns(self):
        target = cm.HOMES_DIR / "_tmp_test_timeout"
        target.mkdir(parents=True)
        result = self.quiet(
            cm.run_codex_login,
            target,
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_seconds=0.3,
        )
        self.assertEqual(result, 124)


if __name__ == "__main__":
    unittest.main()
