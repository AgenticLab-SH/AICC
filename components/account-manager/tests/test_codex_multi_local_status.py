import importlib.util
import sys
from pathlib import Path
from unittest import TestCase, mock


LOCAL_TOOL_ROOT = Path(__file__).resolve().parents[1] / "ops" / "local"
sys.path.insert(0, str(LOCAL_TOOL_ROOT))
SPEC = importlib.util.spec_from_file_location("aicc_local_codex_multi", LOCAL_TOOL_ROOT / "codex_multi.py")
cm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cm)


class LocalStatusTests(TestCase):
    def test_local_status_avoids_remote_quota_calls(self):
        with mock.patch.object(cm, "ensure_dirs"), \
                mock.patch.object(cm, "list_accounts", return_value=["first", "second"]), \
                mock.patch.object(cm, "get_live_app_context", return_value={"active": "second"}), \
                mock.patch.object(cm, "get_cli_accounts", return_value=["first"]), \
                mock.patch.object(cm, "get_expiry", side_effect=[None, "2026-09-01"]), \
                mock.patch.object(cm, "fetch_account_remote_rows") as remote:
            payload = cm.local_status_payload()

        remote.assert_not_called()
        self.assertEqual(payload["account_count"], 2)
        self.assertEqual(payload["active_account"], "second")
        self.assertTrue(payload["accounts"][0]["is_cli_active"])
        self.assertTrue(payload["accounts"][1]["is_app_active"])
