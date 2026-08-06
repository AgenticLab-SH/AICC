import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import sys

PORTAL_DIR = Path(__file__).resolve().parents[1]
MANAGER_DIR = PORTAL_DIR.parent
sys.path.insert(0, str(PORTAL_DIR))
sys.path.insert(0, str(MANAGER_DIR))

import broker
import import_current_to_ocx as ocx_import
import mac_sync


ACCOUNT_ID = "account-portal-test"
TEST_EMAIL = "operator@example.invalid"


def auth_payload(account_id=ACCOUNT_ID):
    return {"auth_mode": "chatgpt", "tokens": {"account_id": account_id, "access_token": "token"}}


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = broker.Config(
            bind="127.0.0.1",
            port=0,
            allowed_email=TEST_EMAIL,
            mac_token="mac-secret",
            expected_account_hash=hashlib.sha256(ACCOUNT_ID.encode()).hexdigest(),
            codex_command="codex",
            state_dir=Path(self.temp.name),
            session_secret="session-secret-for-tests",
            public_origin="https://cm-auth.example.invalid",
            firebase_api_key="public-test-key",
            firebase_project_id="cm-auth-test",
            firebase_auth_domain="auth.example.invalid",
            firebase_app_id="test-app-id",
            firebase_sender_id="test-sender-id",
            portal_title="Test Codex Login",
        )
        self.broker = broker.Broker(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_auth_is_accepted(self):
        path = Path(self.temp.name) / "auth.json"
        path.write_text(json.dumps(auth_payload()), encoding="utf-8")
        self.assertEqual(self.broker._load_and_validate_auth(path), auth_payload())

    def test_wrong_account_is_rejected(self):
        path = Path(self.temp.name) / "auth.json"
        path.write_text(json.dumps(auth_payload("wrong")), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "다른 OpenAI 계정"):
            self.broker._load_and_validate_auth(path)

    def test_ack_retains_latest_auth_and_records_receipt(self):
        path = self.broker.pending_dir / "abc.json"
        path.write_text(json.dumps(auth_payload()), encoding="utf-8")
        self.assertEqual(self.broker.pending()[0], "abc")
        self.assertTrue(self.broker.acknowledge("abc"))
        self.assertEqual(self.broker.pending()[0], "abc")
        self.assertIsNone(self.broker.pending("abc"))
        self.assertTrue(self.broker.latest_path.is_file())
        self.assertEqual(json.loads(self.broker.receipt_path.read_text())["jobId"], "abc")

    def test_new_login_can_replace_retained_latest_auth(self):
        self.broker._write_private_json(
            self.broker.latest_path,
            {"jobId": "abc", "storedAt": 1, "auth": auth_payload()},
        )
        with mock.patch.object(self.broker, "_run_login"):
            created, state = self.broker.start_login()
        self.assertTrue(created)
        self.assertEqual(state["status"], "starting")

    def test_defer_latest_is_private_secret_free_and_idempotent(self):
        created, _ = self.broker.defer_latest()
        self.assertFalse(created)
        self.broker._write_private_json(
            self.broker.latest_path,
            {"jobId": "later-job", "storedAt": 1, "auth": auth_payload()},
        )

        for _ in range(2):
            created, state = self.broker.defer_latest()
            self.assertTrue(created)
            self.assertTrue(state["hasStoredLogin"])
            self.assertTrue(state["deferred"])

        marker = json.loads(self.broker.deferred_path.read_text(encoding="utf-8"))
        self.assertEqual(marker["jobId"], "later-job")
        self.assertIn("requestedAt", marker)
        self.assertNotIn("auth", marker)
        self.assertEqual(self.broker.deferred_path.stat().st_mode & 0o777, 0o600)

    def test_fake_codex_login_reaches_stored_state(self):
        fake = Path(self.temp.name) / "fake-codex"
        fake.write_text(
            """#!/usr/bin/env python3
import json, os, pathlib, sys
for line in sys.stdin:
    msg=json.loads(line)
    if msg.get('id') == 1:
        print(json.dumps({'id':1,'result':{'userAgent':'fake'}}), flush=True)
    elif msg.get('id') == 2:
        pathlib.Path(os.environ['CODEX_HOME'],'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'account_id':'account-portal-test','access_token':'token'}}))
        print(json.dumps({'id':2,'result':{'type':'chatgptDeviceCode','loginId':'login-1','verificationUrl':'https://auth.openai.com/codex/device','userCode':'ABCD-1234'}}), flush=True)
        print(json.dumps({'method':'account/login/completed','params':{'loginId':'login-1','success':True,'error':None}}), flush=True)
""",
            encoding="utf-8",
        )
        fake.chmod(0o700)
        self.broker.config = broker.Config(
            **{**self.config.__dict__, "codex_command": str(fake)}
        )
        created, _ = self.broker.start_login()
        self.assertTrue(created)
        deadline = time.time() + 5
        state = self.broker.state()
        while state["status"] not in {"stored", "error"} and time.time() < deadline:
            time.sleep(0.05)
            state = self.broker.state()
        self.assertEqual(state["status"], "stored", state)
        self.assertIsNotNone(self.broker.pending())

    def test_session_is_signed_and_expires(self):
        value, csrf = self.broker.create_session(TEST_EMAIL)
        session = self.broker.validate_session(value)
        self.assertEqual(session["email"], TEST_EMAIL)
        self.assertEqual(session["csrf"], csrf)
        self.assertIsNone(self.broker.validate_session(value + "tampered"))

    def test_firebase_token_requires_verified_allowlisted_email(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {"users": [{"localId": "firebase-user", "email": TEST_EMAIL, "emailVerified": True}]}
        ).encode()
        with mock.patch.object(broker, "urlopen", return_value=response) as lookup:
            user = self.broker.authenticate_firebase("firebase-id-token")
        self.assertEqual(user["email"], TEST_EMAIL)
        sent = json.loads(lookup.call_args.args[0].data)
        self.assertEqual(sent, {"idToken": "firebase-id-token"})

    def test_firebase_token_rejects_unverified_email(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {"users": [{"localId": "firebase-user", "email": TEST_EMAIL, "emailVerified": False}]}
        ).encode()
        with mock.patch.object(broker, "urlopen", return_value=response):
            with self.assertRaises(PermissionError):
                self.broker.authenticate_firebase("firebase-id-token")

    def test_portal_contains_firebase_gate_without_secrets(self):
        page = broker.portal_html(self.config).decode("utf-8")
        self.assertIn("Google로 계속", page)
        self.assertIn('id="google" type="button" disabled>로그인 준비 중…', page)
        self.assertIn("if(!gate.hidden){google.disabled=false", page)
        self.assertIn("signInWithRedirect", page)
        self.assertIn("getRedirectResult", page)
        self.assertNotIn("signInWithPopup", page)
        self.assertIn("errorCode", page)
        self.assertIn("showGoogleError", page)
        self.assertIn("포털 관리자로 승인되지 않았습니다", page)
        self.assertIn("Google 로그인으로 이동 중", page)
        self.assertNotIn("private-account-alias", page)
        self.assertIn("나중에 Mac으로 가져오기", page)
        self.assertIn("/api/login/defer", page)
        self.assertIn("Mac이 꺼져 있어도", page)
        self.assertIn("www.gstatic.com/firebasejs/10.9.0", page)
        self.assertIn('projectId:"cm-auth-test"', page)
        self.assertNotIn("session-secret-for-tests", page)

    def test_deploy_restarts_an_existing_broker_after_install(self):
        deploy = (PORTAL_DIR / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl enable cm-auth-broker.service", deploy)
        self.assertIn("systemctl restart cm-auth-broker.service", deploy)
        self.assertNotIn("systemctl enable --now cm-auth-broker.service", deploy)

    def test_http_root_public_but_login_api_requires_session_and_csrf(self):
        server = broker.Server(("127.0.0.1", 0), self.broker)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base + "/", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(
                    "frame-src https://auth.example.invalid",
                    response.headers["Content-Security-Policy"],
                )
                self.assertIn(
                    "script-src 'unsafe-inline' https://www.gstatic.com https://apis.google.com",
                    response.headers["Content-Security-Policy"],
                )
                self.assertIn("Google로 계속", response.read().decode())
            with self.assertRaises(HTTPError) as unauthorized:
                urlopen(base + "/api/login/status", timeout=2)
            self.assertEqual(unauthorized.exception.code, 401)
            unauthorized.exception.close()

            cookie, csrf = self.broker.create_session(TEST_EMAIL)
            with urlopen(
                Request(base + "/api/login/status", headers={"Cookie": f"{broker.SESSION_COOKIE}={cookie}"}),
                timeout=2,
            ) as response:
                self.assertEqual(response.status, 200)

            request = Request(
                base + "/api/login/start",
                data=b"{}",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Cookie": f"{broker.SESSION_COOKIE}={cookie}",
                    "Origin": self.config.public_origin,
                    "X-CSRF-Token": csrf + "wrong",
                },
            )
            with self.assertRaises(HTTPError) as forbidden:
                urlopen(request, timeout=2)
            self.assertEqual(forbidden.exception.code, 403)
            forbidden.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_defer_requires_session_and_csrf_then_records_latest(self):
        server = broker.Server(("127.0.0.1", 0), self.broker)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            def request(cookie="", csrf=""):
                headers = {
                    "Content-Type": "application/json",
                    "Origin": self.config.public_origin,
                }
                if cookie:
                    headers["Cookie"] = f"{broker.SESSION_COOKIE}={cookie}"
                if csrf:
                    headers["X-CSRF-Token"] = csrf
                return Request(
                    base + "/api/login/defer",
                    data=b"{}",
                    method="POST",
                    headers=headers,
                )

            with self.assertRaises(HTTPError) as unauthorized:
                urlopen(request(), timeout=2)
            self.assertEqual(unauthorized.exception.code, 401)
            unauthorized.exception.close()

            cookie, csrf = self.broker.create_session(TEST_EMAIL)
            with self.assertRaises(HTTPError) as forbidden:
                urlopen(request(cookie, csrf + "wrong"), timeout=2)
            self.assertEqual(forbidden.exception.code, 403)
            forbidden.exception.close()

            with self.assertRaises(HTTPError) as empty:
                urlopen(request(cookie, csrf), timeout=2)
            self.assertEqual(empty.exception.code, 409)
            empty.exception.close()

            self.broker._write_private_json(
                self.broker.latest_path,
                {"jobId": "later-http", "storedAt": 1, "auth": auth_payload()},
            )
            with urlopen(request(cookie, csrf), timeout=2) as response:
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
            self.assertTrue(payload["deferred"])
            self.assertNotIn("auth", payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class MacSyncTests(unittest.TestCase):
    def setUp(self):
        self.target_account = mock.patch.object(mac_sync, "TARGET_ACCOUNT", TEST_EMAIL)
        self.ocx_target = mock.patch.object(mac_sync, "OCX_TARGET_ACCOUNT", "portal-test")
        self.target_account.start()
        self.ocx_target.start()

    def tearDown(self):
        self.ocx_target.stop()
        self.target_account.stop()

    @staticmethod
    def write_ocx_state(root: Path, account_id: str, *, access="old-access", refresh="old-refresh"):
        (root / "config.json").write_text(
            json.dumps({
                "activeCodexAccountId": "existing",
                "codexAccounts": [{
                    "id": account_id,
                    "email": TEST_EMAIL,
                    "plan": "team",
                    "alias": "owner",
                    "isMain": False,
                }],
            }),
            encoding="utf-8",
        )
        (root / "codex-accounts.json").write_text(
            json.dumps({
                account_id: {
                    "credential": {
                        "accessToken": access,
                        "refreshToken": refresh,
                        "expiresAt": 1,
                        "chatgptAccountId": ACCOUNT_ID,
                    }
                }
            }),
            encoding="utf-8",
        )

    def test_import_preserves_wrong_account(self):
        with mock.patch.object(mac_sync.cm, "read_auth", return_value=auth_payload()), mock.patch.object(
            mac_sync.cm, "save_auth"
        ) as save:
            with self.assertRaisesRegex(RuntimeError, "계정 ID"):
                mac_sync.import_auth(auth_payload("wrong"))
            save.assert_not_called()

    def test_import_saves_matching_account(self):
        with mock.patch.object(mac_sync.cm, "read_auth", return_value=auth_payload()), mock.patch.object(
            mac_sync.cm, "fetch_quota", return_value={"ok": True}
        ), mock.patch.object(mac_sync.cm, "save_auth") as save, mock.patch.object(
            mac_sync.cm, "get_active_account", return_value="another@gmail.com"
        ):
            self.assertEqual(mac_sync.import_auth(auth_payload()), mac_sync.TARGET_ACCOUNT)
            save.assert_called_once_with(mac_sync.TARGET_ACCOUNT, auth_payload())

    def test_opencodex_import_uses_explicit_target_and_restores_active(self):
        payload = auth_payload()
        payload["tokens"]["refresh_token"] = "refresh"
        calls = []

        def api(path, *, method="GET", payload=None):
            calls.append((path, method, payload))
            if path == "/api/codex-auth/accounts" and method == "GET":
                return 200, {"accounts": [{"id": "existing"}]}
            if path == "/api/codex-auth/active" and method == "GET":
                return 200, {"activeCodexAccountId": "existing"}
            if path == "/api/codex-auth/accounts" and method == "POST":
                return 200, {"ok": True}
            if path == "/api/codex-auth/accounts?refresh=1":
                return 200, {"accounts": [{"id": mac_sync.OCX_TARGET_ACCOUNT, "hasCredential": True, "needsReauth": False}]}
            return 200, {"ok": True}

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(mac_sync, "OCX_HOME", Path(temp)), mock.patch.object(
            mac_sync, "OCX_LOCK", Path(temp) / ".lock"
        ), mock.patch.object(
            mac_sync, "OCX_BACKUP_ROOT", Path(temp) / "backups"
        ), mock.patch.object(mac_sync, "_json_request", side_effect=api):
            self.assertEqual(mac_sync.import_into_opencodex(payload), mac_sync.OCX_TARGET_ACCOUNT)
        post = next(call for call in calls if call[0] == "/api/codex-auth/accounts" and call[1] == "POST")
        self.assertEqual(post[2]["id"], mac_sync.OCX_TARGET_ACCOUNT)
        self.assertEqual(calls[-1], ("/api/codex-auth/active", "PUT", {"accountId": "existing"}))

    def test_opencodex_management_request_uses_native_admin_token(self):
        token = "ocx_admin_" + ("a" * 43)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"activeTurnCount":0,"isDraining":false}'
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            mac_sync, "OCX_ADMIN_TOKEN_FILE", Path(temp) / "admin-api-token"
        ), mock.patch.object(mac_sync, "urlopen", return_value=response) as open_request:
            mac_sync.OCX_ADMIN_TOKEN_FILE.write_text(token, encoding="utf-8")
            mac_sync.OCX_ADMIN_TOKEN_FILE.chmod(0o600)
            mac_sync.ensure_opencodex_idle()
        request = open_request.call_args.args[0]
        self.assertEqual(request.get_header("X-opencodex-api-key"), token)

    def test_opencodex_active_turn_defers_update(self):
        with mock.patch.object(
            mac_sync, "_json_request",
            return_value=(200, {"activeTurnCount": 1, "isDraining": False}),
        ), self.assertRaisesRegex(RuntimeError, "다음 주기"):
            mac_sync.ensure_opencodex_idle()

    def test_opencodex_import_replaces_existing_target_and_preserves_metadata(self):
        payload = auth_payload()
        payload["tokens"]["refresh_token"] = "new-refresh"
        calls = []

        def api(path, *, method="GET", payload=None):
            calls.append((path, method, payload))
            if path == "/api/codex-auth/accounts" and method == "GET":
                return 200, {"accounts": [{"id": mac_sync.OCX_TARGET_ACCOUNT, "paused": False}]}
            if path == "/api/codex-auth/active" and method == "GET":
                return 200, {"activeCodexAccountId": "existing"}
            if path == "/api/codex-auth/accounts?refresh=1":
                return 200, {"accounts": [{"id": mac_sync.OCX_TARGET_ACCOUNT, "hasCredential": True, "needsReauth": False}]}
            return 200, {"ok": True}

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(mac_sync, "OCX_HOME", Path(temp)), mock.patch.object(
            mac_sync, "OCX_LOCK", Path(temp) / ".lock"
        ), mock.patch.object(
            mac_sync, "OCX_BACKUP_ROOT", Path(temp) / "backups"
        ), mock.patch.object(mac_sync, "_json_request", side_effect=api):
            self.write_ocx_state(Path(temp), mac_sync.OCX_TARGET_ACCOUNT)
            self.assertEqual(mac_sync.import_into_opencodex(payload), mac_sync.OCX_TARGET_ACCOUNT)
        delete_index = next(i for i, call in enumerate(calls) if call[1] == "DELETE")
        post_index = next(i for i, call in enumerate(calls) if call[1] == "POST")
        self.assertLess(delete_index, post_index)
        post = calls[post_index][2]
        self.assertEqual(post["refreshToken"], "new-refresh")
        self.assertEqual(post["plan"], "team")
        self.assertIn(
            ("/api/codex-auth/accounts/alias", "PUT", {"id": mac_sync.OCX_TARGET_ACCOUNT, "alias": "owner"}),
            calls,
        )

    def test_opencodex_replace_failure_restores_old_credential(self):
        payload = auth_payload()
        payload["tokens"]["refresh_token"] = "new-refresh"
        posts = []

        def api(path, *, method="GET", payload=None):
            if path == "/api/codex-auth/accounts" and method == "GET":
                return 200, {"accounts": [{"id": mac_sync.OCX_TARGET_ACCOUNT, "paused": False}]}
            if path == "/api/codex-auth/active" and method == "GET":
                return 200, {"activeCodexAccountId": "existing"}
            if path == "/api/codex-auth/accounts" and method == "POST":
                posts.append(payload)
                if len(posts) == 1:
                    return 400, {"error": "rejected"}
                return 200, {"ok": True}
            return 200, {"ok": True}

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(mac_sync, "OCX_HOME", Path(temp)), mock.patch.object(
            mac_sync, "OCX_LOCK", Path(temp) / ".lock"
        ), mock.patch.object(
            mac_sync, "OCX_BACKUP_ROOT", Path(temp) / "backups"
        ), mock.patch.object(mac_sync, "_json_request", side_effect=api):
            self.write_ocx_state(Path(temp), mac_sync.OCX_TARGET_ACCOUNT)
            with self.assertRaisesRegex(RuntimeError, "native import"):
                mac_sync.import_into_opencodex(payload)
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[1]["accessToken"], "old-access")
        self.assertEqual(posts[1]["refreshToken"], "old-refresh")

    def test_opencodex_gate_failure_restores_active_without_tokens_in_error(self):
        payload = auth_payload()
        payload["tokens"]["refresh_token"] = "refresh-secret"

        def api(path, *, method="GET", payload=None):
            if path == "/api/codex-auth/accounts" and method == "GET":
                return 200, {"accounts": []}
            if path == "/api/codex-auth/active" and method == "GET":
                return 200, {"activeCodexAccountId": "existing"}
            if path == "/api/codex-auth/accounts" and method == "POST":
                return 403, {"code": "manual_import_disabled"}
            return 200, {"ok": True}

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(mac_sync, "OCX_HOME", Path(temp)), mock.patch.object(
            mac_sync, "OCX_LOCK", Path(temp) / ".lock"
        ), mock.patch.object(
            mac_sync, "OCX_BACKUP_ROOT", Path(temp) / "backups"
        ), mock.patch.object(mac_sync, "_json_request", side_effect=api):
            with self.assertRaisesRegex(RuntimeError, "일회성") as raised:
                mac_sync.import_into_opencodex(payload)
        self.assertNotIn("refresh-secret", str(raised.exception))

    def test_opencodex_target_access_test_uses_native_cli_without_switching(self):
        output = json.dumps(
            {"accounts": [{"id": mac_sync.OCX_TARGET_ACCOUNT, "needsReauth": False}]}
        )
        completed = mock.Mock(returncode=0, stdout=output, stderr="")
        with mock.patch.object(mac_sync.subprocess, "run", return_value=completed) as run:
            self.assertTrue(mac_sync.verify_opencodex_target())
        self.assertEqual(
            run.call_args.args[0], ["ocx", "account", "refresh", "openai", "--json"]
        )

    def test_fetch_latest_uses_checkpoint_and_ack_updates_it(self):
        response = mock.Mock(status=200)
        response.read.return_value = json.dumps({"jobId": "new-job", "auth": auth_payload()}).encode()
        ack = mock.Mock(status=200)
        ack.read.return_value = b'{"ok":true}'
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            mac_sync, "SYNC_STATE_FILE", Path(temp) / "sync.json"
        ), mock.patch.object(mac_sync, "_token", return_value="secret"), mock.patch.object(
            mac_sync, "_request", side_effect=[response, ack]
        ) as request:
            mac_sync._write_private_json(mac_sync.SYNC_STATE_FILE, {"jobId": "old-job"})
            self.assertEqual(mac_sync.fetch_latest("https://portal.example.invalid")[0], "new-job")
            self.assertIn("after=old-job", request.call_args_list[0].args[2])
            mac_sync.acknowledge_latest("new-job", "https://portal.example.invalid")
            self.assertEqual(mac_sync.last_applied_job_id(), "new-job")


class OcxImportOrchestratorTests(unittest.TestCase):
    def test_portal_without_new_version_does_not_touch_proxy(self):
        with mock.patch.object(sys, "argv", ["import_current_to_ocx.py", "--portal"]), mock.patch.object(
            ocx_import.mac_sync, "_require_target_account", return_value=TEST_EMAIL
        ), mock.patch.object(
            ocx_import.mac_sync, "_require_ocx_target_account", return_value="stable"
        ), mock.patch.object(
            ocx_import.mac_sync, "fetch_latest", return_value=None
        ), mock.patch.object(
            ocx_import, "_healthy", return_value=True
        ), mock.patch.object(
            ocx_import, "_gate_persisted", return_value=False
        ), mock.patch.object(ocx_import, "_stop_proxy") as stop:
            self.assertEqual(ocx_import.main(), 0)
        stop.assert_not_called()

    def test_stop_failure_restores_snapshot_and_restarts_service(self):
        auth = auth_payload()
        auth["tokens"]["refresh_token"] = "refresh"
        backup = Path("/private/backup")
        with mock.patch.object(sys, "argv", ["import_current_to_ocx.py"]), mock.patch.object(
            ocx_import.mac_sync, "_require_target_account", return_value=TEST_EMAIL
        ), mock.patch.object(
            ocx_import.mac_sync, "_require_ocx_target_account", return_value="stable"
        ), mock.patch.object(
            ocx_import.mac_sync.cm, "read_auth", return_value=auth
        ), mock.patch.object(
            ocx_import.mac_sync.cm, "_has_usable_chatgpt_auth", return_value=True
        ), mock.patch.object(
            ocx_import.mac_sync, "opencodex_target_matches", return_value=False
        ), mock.patch.object(
            ocx_import.mac_sync, "ensure_opencodex_idle"
        ), mock.patch.object(
            ocx_import.mac_sync, "backup_ocx_state", return_value=backup
        ), mock.patch.object(
            ocx_import, "_stop_proxy", side_effect=RuntimeError("stop failed")
        ), mock.patch.object(
            ocx_import.mac_sync, "restore_ocx_state"
        ) as restore, mock.patch.object(
            ocx_import, "_start_service"
        ) as start, mock.patch.object(
            ocx_import, "_healthy", return_value=True
        ), mock.patch.object(
            ocx_import, "_gate_persisted", return_value=False
        ):
            self.assertEqual(ocx_import.main(), 1)
        restore.assert_called_once_with(backup)
        start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
