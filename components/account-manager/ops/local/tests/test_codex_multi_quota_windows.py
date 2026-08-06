import sys
import unittest
from pathlib import Path
from unittest import mock

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT))

import codex_multi as cm  # noqa: E402


def usage_payload(plan: str, primary: dict | None, secondary: dict | None = None) -> dict:
    return {
        "ok": True,
        "email": "user@example.invalid",
        "plan_type": plan,
        "rate_limit": {"primary_window": primary, "secondary_window": secondary},
        "additional_rate_limits": None,
    }


class UsageWindowTests(unittest.TestCase):
    def test_plus_plan_keeps_five_hour_and_weekly_slots(self):
        data = usage_payload(
            "plus",
            {"used_percent": 20, "limit_window_seconds": 5 * 3600, "reset_after_seconds": 1800},
            {"used_percent": 40, "limit_window_seconds": 7 * 86400, "reset_after_seconds": 86400},
        )
        q = cm.format_quota(data)
        self.assertEqual(q["quota1_label"], "5h")
        self.assertEqual(q["quota2_label"], "주간")
        self.assertEqual(q["5h_remain"], 80)
        self.assertEqual(q["long_remain"], 60)

    def test_business_monthly_window_lands_in_long_slot(self):
        # Team/Business accounts report a single ~30d window and no secondary
        # window. It must not be rendered as if it were the 5h limit.
        data = usage_payload(
            "team",
            {"used_percent": 0, "limit_window_seconds": 2628000, "reset_after_seconds": 2628000},
        )
        q = cm.format_quota(data)
        self.assertEqual(q["quota1_label"], "-")
        self.assertEqual(q["5h_reset"], "-")
        self.assertEqual(q["quota2_label"], "월간")
        self.assertEqual(q["long_remain"], 100)
        self.assertEqual(q["wk_remain"], 100)
        self.assertTrue(q["long_reset"].startswith("30d"))

    def test_monthly_only_plan_summary_uses_the_reported_window(self):
        data = usage_payload(
            "team",
            {"used_percent": 25, "limit_window_seconds": 2628000, "reset_after_seconds": 600},
        )
        label, usage = cm.primary_quota_display(cm.format_quota(data))
        self.assertEqual(label, "월간")
        self.assertEqual(usage, "75%")

    def test_additional_rate_limits_are_classified_by_duration(self):
        data = {
            "ok": True,
            "email": "user@example.invalid",
            "plan_type": "pro",
            "rate_limit": {"primary_window": None, "secondary_window": None},
            "additional_rate_limits": [
                {"rate_limit": {
                    "primary_window": {
                        "used_percent": 10,
                        "limit_window_seconds": 5 * 3600,
                        "reset_after_seconds": 60,
                    },
                    "secondary_window": {
                        "used_percent": 30,
                        "limit_window_seconds": 30 * 86400,
                        "reset_after_seconds": 120,
                    },
                }}
            ],
        }
        q = cm.format_quota(data)
        self.assertEqual(q["quota1_label"], "5h")
        self.assertEqual(q["quota2_label"], "월간")

    def test_missing_windows_render_as_dashes(self):
        q = cm.format_quota(usage_payload("plus", None, None))
        self.assertEqual(q["quota1_label"], "-")
        self.assertEqual(q["quota2_label"], "-")
        self.assertEqual(cm.quota_slot_text("-", None, "-", False), ("-", "-"))


class KiroCredentialSourceTests(unittest.TestCase):
    """Two Kiro logins can coexist; only the Desktop one is fully entitled."""

    def _with_tokens(self, active, desktop, cli):
        return (
            mock.patch("codex_multi._find_first_kiro_access_token", return_value=active),
            mock.patch("codex_multi._kiro_desktop_token", return_value=desktop),
            mock.patch("codex_multi._kiro_cli_token", return_value=cli),
        )

    def _resolve(self, active, desktop, cli):
        store = {"kiro": {"accounts": []}}
        patches = self._with_tokens(active, desktop, cli)
        with mock.patch(
            "codex_multi.json.loads", return_value=store
        ), mock.patch("codex_multi.Path.read_text", return_value="{}"), patches[0], patches[1], patches[2]:
            return cm.kiro_credential_source()

    def test_desktop_token_is_reported_as_desktop(self):
        self.assertEqual(self._resolve("desk", "desk", "cli"), "desktop")

    def test_cli_token_is_flagged(self):
        self.assertEqual(self._resolve("cli", "desk", "cli"), "kiro-cli")

    def test_rotated_token_is_reported_as_detached(self):
        self.assertEqual(self._resolve("rotated", "desk", "cli"), "detached")

    def test_missing_token_is_reported_as_none(self):
        self.assertEqual(self._resolve(None, "desk", "cli"), "none")


class CodexCliVersionTests(unittest.TestCase):
    def test_prerelease_ranks_below_its_own_release_but_above_older(self):
        self.assertGreater(
            cm._version_key("codex-cli 0.146.0-alpha.3.1"),
            cm._version_key("codex-cli 0.145.0"),
        )
        self.assertLess(
            cm._version_key("codex-cli 0.146.0-alpha.3.1"),
            cm._version_key("codex-cli 0.146.0"),
        )
        self.assertIsNone(cm._version_key("no version here"))

    def test_resolve_picks_the_highest_version_candidate(self):
        versions = {"/usr/bin/codex": "codex-cli 0.140.0", "/app/codex": "codex-cli 0.146.0"}
        with mock.patch(
            "codex_multi._codex_cli_candidates", return_value=list(versions)
        ), mock.patch(
            "codex_multi._codex_cli_version", side_effect=lambda cmd: versions[cmd]
        ):
            command, version = cm._resolve_codex_cli()
        self.assertEqual(command, "/app/codex")
        self.assertEqual(version, "codex-cli 0.146.0")

    def test_auto_update_skips_when_local_build_is_newer(self):
        cm._CODEX_CLI_CACHE.clear()
        try:
            with mock.patch(
                "codex_multi._resolve_codex_cli",
                return_value=("/app/codex", "codex-cli 0.146.0-alpha.3.1"),
            ), mock.patch(
                "codex_multi.latest_codex_npm_version", return_value="0.145.0"
            ), mock.patch("codex_multi._install_latest_codex_cli") as install:
                self.assertEqual(cm.ensure_codex_cli_current(quiet=True), "/app/codex")
            install.assert_not_called()
        finally:
            cm._CODEX_CLI_CACHE.clear()

    def test_auto_update_installs_when_published_build_is_newer(self):
        cm._CODEX_CLI_CACHE.clear()
        try:
            with mock.patch(
                "codex_multi._resolve_codex_cli",
                return_value=("/usr/bin/codex", "codex-cli 0.140.0"),
            ), mock.patch(
                "codex_multi.latest_codex_npm_version", return_value="0.146.0"
            ), mock.patch(
                "codex_multi._install_latest_codex_cli", return_value=(0, "")
            ) as install:
                cm.ensure_codex_cli_current(quiet=True)
            install.assert_called_once()
        finally:
            cm._CODEX_CLI_CACHE.clear()

    def test_auto_update_respects_opt_out(self):
        cm._CODEX_CLI_CACHE.clear()
        try:
            with mock.patch.dict(cm.os.environ, {"CM_CLI_AUTO_UPDATE": "0"}), mock.patch(
                "codex_multi._resolve_codex_cli",
                return_value=("/usr/bin/codex", "codex-cli 0.140.0"),
            ), mock.patch("codex_multi.latest_codex_npm_version") as latest:
                self.assertEqual(cm.ensure_codex_cli_current(quiet=True), "/usr/bin/codex")
            latest.assert_not_called()
        finally:
            cm._CODEX_CLI_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
