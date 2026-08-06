#!/usr/bin/env python3
"""Small self-hosted portal for asynchronous Codex device login.

The service is intentionally bound to loopback and is expected to sit behind
Cloudflare Tunnel + Access. It never prints auth payloads or account IDs.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen


MAX_BODY_BYTES = 64 * 1024
SESSION_COOKIE = "cm_auth_session"
SESSION_MAX_AGE = 60 * 60
@dataclass(frozen=True)
class Config:
    bind: str
    port: int
    allowed_email: str
    mac_token: str
    expected_account_hash: str
    codex_command: str
    state_dir: Path
    session_secret: str = ""
    public_origin: str = ""
    firebase_api_key: str = ""
    firebase_project_id: str = ""
    firebase_auth_domain: str = ""
    firebase_app_id: str = ""
    firebase_sender_id: str = ""
    portal_title: str = "Codex 로그인"

    @classmethod
    def from_env(cls) -> "Config":
        required = {
            "CM_AUTH_ALLOWED_EMAIL": os.environ.get("CM_AUTH_ALLOWED_EMAIL", ""),
            "CM_AUTH_MAC_TOKEN": os.environ.get("CM_AUTH_MAC_TOKEN", ""),
            "CM_AUTH_EXPECTED_ACCOUNT_ID_SHA256": os.environ.get(
                "CM_AUTH_EXPECTED_ACCOUNT_ID_SHA256", ""
            ),
            "CM_AUTH_SESSION_SECRET": os.environ.get("CM_AUTH_SESSION_SECRET", ""),
            "CM_AUTH_PUBLIC_ORIGIN": os.environ.get("CM_AUTH_PUBLIC_ORIGIN", ""),
            "CM_AUTH_FIREBASE_API_KEY": os.environ.get("CM_AUTH_FIREBASE_API_KEY", ""),
            "CM_AUTH_FIREBASE_PROJECT_ID": os.environ.get("CM_AUTH_FIREBASE_PROJECT_ID", ""),
            "CM_AUTH_FIREBASE_AUTH_DOMAIN": os.environ.get("CM_AUTH_FIREBASE_AUTH_DOMAIN", ""),
            "CM_AUTH_FIREBASE_APP_ID": os.environ.get("CM_AUTH_FIREBASE_APP_ID", ""),
            "CM_AUTH_FIREBASE_SENDER_ID": os.environ.get("CM_AUTH_FIREBASE_SENDER_ID", ""),
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise RuntimeError("Missing required settings: " + ", ".join(missing))
        expected_hash = required["CM_AUTH_EXPECTED_ACCOUNT_ID_SHA256"].lower()
        if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
            raise RuntimeError("CM_AUTH_EXPECTED_ACCOUNT_ID_SHA256 must be SHA-256 hex")
        firebase_auth_domain = required["CM_AUTH_FIREBASE_AUTH_DOMAIN"].strip()
        if any(not (c.isalnum() or c in ".-") for c in firebase_auth_domain):
            raise RuntimeError("CM_AUTH_FIREBASE_AUTH_DOMAIN must be a hostname")
        state_dir = Path(os.environ.get("CM_AUTH_STATE_DIR", "/var/lib/cm-auth-broker"))
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.chmod(0o700)
        return cls(
            bind=os.environ.get("CM_AUTH_BIND", "127.0.0.1"),
            port=int(os.environ.get("CM_AUTH_PORT", "8110")),
            allowed_email=required["CM_AUTH_ALLOWED_EMAIL"].strip().lower(),
            mac_token=required["CM_AUTH_MAC_TOKEN"].strip(),
            expected_account_hash=expected_hash,
            codex_command=os.environ.get("CM_AUTH_CODEX_COMMAND", "codex"),
            state_dir=state_dir,
            session_secret=required["CM_AUTH_SESSION_SECRET"].strip(),
            public_origin=required["CM_AUTH_PUBLIC_ORIGIN"].rstrip("/"),
            firebase_api_key=required["CM_AUTH_FIREBASE_API_KEY"].strip(),
            firebase_project_id=required["CM_AUTH_FIREBASE_PROJECT_ID"].strip(),
            firebase_auth_domain=firebase_auth_domain,
            firebase_app_id=required["CM_AUTH_FIREBASE_APP_ID"].strip(),
            firebase_sender_id=required["CM_AUTH_FIREBASE_SENDER_ID"].strip(),
            portal_title=os.environ.get("CM_AUTH_PORTAL_TITLE", "Codex 로그인").strip(),
        )


@dataclass
class LoginState:
    status: str = "idle"
    job_id: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    message: str = "로그인을 시작할 수 있습니다."
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "jobId": self.job_id,
            "verificationUrl": self.verification_url,
            "userCode": self.user_code,
            "message": self.message,
            "updatedAt": int(self.updated_at),
        }


class Broker:
    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()
        self._state = LoginState()
        self._login_thread: threading.Thread | None = None
        self.pending_dir = config.state_dir / "pending"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.pending_dir.chmod(0o700)
        self.latest_path = config.state_dir / "latest.json"
        self.receipt_path = config.state_dir / "last-ack.json"
        self.deferred_path = config.state_dir / "deferred.json"
        if self.latest_path.is_file() or any(self.pending_dir.glob("*.json")):
            self._state = LoginState(
                status="stored",
                message="최신 로그인이 보관되어 있습니다. 새 로그인으로 갱신할 수 있습니다.",
            )

    @staticmethod
    def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
        staging = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        staging.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        staging.chmod(0o600)
        os.replace(staging, path)

    def authenticate_firebase(self, id_token: str) -> dict[str, str]:
        """Validate a Firebase ID token server-side and apply the server allowlist."""
        if not id_token or len(id_token) > 16_384:
            raise PermissionError("invalid token")
        request = Request(
            "https://identitytoolkit.googleapis.com/v1/accounts:lookup?key="
            + quote(self.config.firebase_api_key, safe=""),
            data=json.dumps({"idToken": id_token}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "cm-auth-broker/1.0"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read(MAX_BODY_BYTES + 1))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PermissionError("firebase verification failed") from exc
        users = payload.get("users") if isinstance(payload, dict) else None
        user = users[0] if isinstance(users, list) and len(users) == 1 else None
        if not isinstance(user, dict):
            raise PermissionError("firebase user missing")
        email = str(user.get("email") or "").strip().lower()
        verified = user.get("emailVerified") is True
        local_id = str(user.get("localId") or "").strip()
        if not verified or not local_id or not hmac.compare_digest(
            email, self.config.allowed_email
        ):
            raise PermissionError("firebase user forbidden")
        return {"email": email, "localId": local_id}

    def create_session(self, email: str) -> tuple[str, str]:
        now = int(time.time())
        csrf = secrets.token_urlsafe(24)
        payload = {"email": email, "iat": now, "exp": now + SESSION_MAX_AGE, "csrf": csrf}
        encoded = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64url(
            hmac.new(
                self.config.session_secret.encode("utf-8"),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"{encoded}.{signature}", csrf

    def validate_session(self, value: str) -> dict[str, Any] | None:
        try:
            encoded, supplied = value.split(".", 1)
            expected = _b64url(
                hmac.new(
                    self.config.session_secret.encode("utf-8"),
                    encoded.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(supplied, expected):
                return None
            payload = json.loads(_b64url_decode(encoded))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        email = str(payload.get("email") or "").strip().lower()
        exp = payload.get("exp")
        csrf = payload.get("csrf")
        if (
            not isinstance(exp, int)
            or exp <= int(time.time())
            or not isinstance(csrf, str)
            or not csrf
            or not hmac.compare_digest(email, self.config.allowed_email)
        ):
            return None
        return payload

    def _latest_job_id(self) -> str:
        if self.latest_path.is_file():
            try:
                payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return ""
            return str(payload.get("jobId") or "") if isinstance(payload, dict) else ""
        files = sorted(self.pending_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        return files[0].stem if files else ""

    def _is_deferred(self, job_id: str) -> bool:
        if not job_id or not self.deferred_path.is_file():
            return False
        try:
            payload = json.loads(self.deferred_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        deferred_job_id = str(payload.get("jobId") or "") if isinstance(payload, dict) else ""
        return bool(deferred_job_id) and hmac.compare_digest(deferred_job_id, job_id)

    def state(self) -> dict[str, Any]:
        with self._lock:
            public = self._state.public()
        latest_job_id = self._latest_job_id()
        public["hasStoredLogin"] = bool(latest_job_id)
        public["deferred"] = self._is_deferred(latest_job_id)
        return public

    def defer_latest(self) -> tuple[bool, dict[str, Any]]:
        """Durably record the owner's intent to fetch the retained login later.

        The credential remains in latest.json and the Mac polling API is left
        unchanged. This marker contains no auth material and is safe to repeat.
        """
        with self._lock:
            if self._login_thread and self._login_thread.is_alive():
                return False, self._state.public()
            job_id = self._latest_job_id()
            if not job_id:
                return False, self._state.public()
            self._write_private_json(
                self.deferred_path,
                {"jobId": job_id, "requestedAt": int(time.time())},
            )
        return True, self.state()

    def start_login(self) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if self._login_thread and self._login_thread.is_alive():
                return False, self._state.public()
            job_id = str(uuid.uuid4())
            self._state = LoginState(
                status="starting",
                job_id=job_id,
                message="OpenAI 로그인 준비 중입니다.",
            )
            self._login_thread = threading.Thread(
                target=self._run_login,
                args=(job_id,),
                name=f"cm-auth-{job_id[:8]}",
                daemon=True,
            )
            self._login_thread.start()
            return True, self._state.public()

    def _set_state(self, job_id: str, **values: Any) -> None:
        with self._lock:
            if self._state.job_id != job_id:
                return
            for key, value in values.items():
                setattr(self._state, key, value)
            self._state.updated_at = time.time()

    def _run_login(self, job_id: str) -> None:
        temp_root = self.config.state_dir / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_home = Path(tempfile.mkdtemp(prefix="login-", dir=temp_root))
        temp_home.chmod(0o700)
        proc: subprocess.Popen[Any] | None = None
        try:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(temp_home)
            env.pop("OPENAI_API_KEY", None)
            env.pop("CODEX_ACCESS_TOKEN", None)
            proc = subprocess.Popen(
                [self.config.codex_command, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=False,
                bufsize=0,
                env=env,
            )
            assert proc.stdin is not None and proc.stdout is not None
            self._send(
                proc,
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "cm-auth-broker",
                            "title": "CM Auth Broker",
                            "version": "1.0.0",
                        },
                        "capabilities": {},
                    },
                },
            )
            self._wait_response(proc, 1, timeout=20)
            self._send(proc, {"method": "initialized", "params": {}})
            self._send(
                proc,
                {
                    "method": "account/login/start",
                    "id": 2,
                    "params": {"type": "chatgptDeviceCode"},
                },
            )
            login = self._wait_response(proc, 2, timeout=30)
            result = login.get("result") if isinstance(login, dict) else None
            if not isinstance(result, dict):
                raise RuntimeError("Codex did not return a device login")
            login_id = str(result.get("loginId") or "")
            verification_url = str(result.get("verificationUrl") or "")
            user_code = str(result.get("userCode") or "")
            if not login_id or not verification_url.startswith("https://") or not user_code:
                raise RuntimeError("Codex returned an incomplete device login")
            self._set_state(
                job_id,
                status="waiting",
                verification_url=verification_url,
                user_code=user_code,
                message="아래 OpenAI 페이지에서 로그인해 주세요.",
            )

            completed = self._wait_completion(proc, login_id, timeout=20 * 60)
            if not completed.get("success"):
                raise RuntimeError(str(completed.get("error") or "OpenAI login failed"))
            auth_path = temp_home / "auth.json"
            deadline = time.time() + 10
            while not auth_path.exists() and time.time() < deadline:
                time.sleep(0.1)
            auth = self._load_and_validate_auth(auth_path)
            self._write_private_json(
                self.latest_path,
                {"jobId": job_id, "storedAt": int(time.time()), "auth": auth},
            )
            self._set_state(
                job_id,
                status="stored",
                verification_url=None,
                user_code=None,
                message="로그인 완료. 최신 인증을 보관했고 Mac이 자동으로 가져갑니다.",
            )
        except Exception as exc:
            self._set_state(
                job_id,
                status="error",
                verification_url=None,
                user_code=None,
                message=self._safe_error(exc),
            )
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            if proc:
                if proc.stdin:
                    proc.stdin.close()
                if proc.stdout:
                    proc.stdout.close()
            shutil.rmtree(temp_home, ignore_errors=True)

    @staticmethod
    def _send(proc: subprocess.Popen[Any], payload: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        proc.stdin.flush()

    @staticmethod
    def _read_message(proc: subprocess.Popen[Any], deadline: float) -> dict[str, Any]:
        assert proc.stdout is not None
        queued = getattr(proc, "_cm_messages", None)
        if queued is None:
            queued = []
            setattr(proc, "_cm_messages", queued)
            setattr(proc, "_cm_buffer", b"")
        if queued:
            return queued.pop(0)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            if not selector.select(timeout=remaining):
                break
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                if proc.poll() is not None:
                    raise RuntimeError("Codex app-server stopped unexpectedly")
                time.sleep(0.05)
                continue
            buffer = getattr(proc, "_cm_buffer", b"") + chunk
            lines = buffer.split(b"\n")
            setattr(proc, "_cm_buffer", lines.pop())
            for line in lines:
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    queued.append(parsed)
            if queued:
                return queued.pop(0)
        raise TimeoutError("Codex login timed out")

    def _wait_response(
        self, proc: subprocess.Popen[Any], request_id: int, *, timeout: float
    ) -> dict[str, Any]:
        deadline = time.time() + timeout
        while True:
            message = self._read_message(proc, deadline)
            if message.get("id") == request_id:
                if message.get("error"):
                    raise RuntimeError("Codex rejected the login request")
                return message

    def _wait_completion(
        self, proc: subprocess.Popen[Any], login_id: str, *, timeout: float
    ) -> dict[str, Any]:
        deadline = time.time() + timeout
        while True:
            message = self._read_message(proc, deadline)
            if message.get("method") != "account/login/completed":
                continue
            params = message.get("params")
            if isinstance(params, dict) and str(params.get("loginId") or "") == login_id:
                return params

    def _load_and_validate_auth(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise RuntimeError("Codex login completed without an auth file")
        auth = json.loads(path.read_text(encoding="utf-8"))
        tokens = auth.get("tokens") if isinstance(auth, dict) else None
        account_id = tokens.get("account_id") if isinstance(tokens, dict) else None
        access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
        if not isinstance(account_id, str) or not isinstance(access_token, str) or not access_token:
            raise RuntimeError("Codex returned an invalid auth file")
        digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, self.config.expected_account_hash):
            raise RuntimeError("다른 OpenAI 계정으로 로그인했습니다. 구성된 대상 계정으로 다시 시도해 주세요.")
        return auth

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip()
        allowed = (
            "다른 OpenAI 계정",
            "Codex login timed out",
            "OpenAI login failed",
        )
        if any(message.startswith(prefix) for prefix in allowed):
            return message
        return "로그인을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."

    def pending(self, after_job_id: str = "") -> tuple[str, dict[str, Any]] | None:
        if self.latest_path.is_file():
            payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
            job_id = str(payload.get("jobId") or "") if isinstance(payload, dict) else ""
            auth = payload.get("auth") if isinstance(payload, dict) else None
            if not job_id or not isinstance(auth, dict):
                raise RuntimeError("stored auth envelope is invalid")
            if after_job_id and hmac.compare_digest(after_job_id, job_id):
                return None
            return job_id, auth

        # Migrate the original one-shot pending format without dropping its
        # credential. The first successful acknowledgement writes latest.json.
        files = sorted(self.pending_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        path = files[0]
        if after_job_id and hmac.compare_digest(after_job_id, path.stem):
            return None
        return path.stem, json.loads(path.read_text(encoding="utf-8"))

    def acknowledge(self, job_id: str) -> bool:
        if not job_id or any(c not in "0123456789abcdef-" for c in job_id.lower()):
            return False
        current = self.pending()
        if current is None or not hmac.compare_digest(current[0], job_id):
            return False
        if not self.latest_path.is_file():
            self._write_private_json(
                self.latest_path,
                {"jobId": job_id, "storedAt": int(time.time()), "auth": current[1]},
            )
            (self.pending_dir / f"{job_id}.json").unlink(missing_ok=True)
        self._write_private_json(
            self.receipt_path,
            {"jobId": job_id, "acknowledgedAt": int(time.time())},
        )
        return True


def _b64url(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def portal_html(config: Config) -> bytes:
    title = html.escape(config.portal_title)
    page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Segoe UI",sans-serif;background:#071018;color:#f4f6f8}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px}}.card{{width:min(560px,100%);padding:32px;border:1px solid #253747;border-radius:20px;background:#0f1a24;box-shadow:0 24px 70px #0008}}h1{{font-size:clamp(24px,5vw,32px);line-height:1.25;margin:0 0 12px}}p{{font-size:16px;line-height:1.6;color:#aab8c5}}.status{{margin:24px 0;padding:16px;border-radius:12px;background:#09141d;border:1px solid #203242;min-height:80px}}.code{{font:700 28px/1.3 ui-monospace,SFMono-Regular,monospace;letter-spacing:.06em;color:#7dd3fc;margin-top:10px;user-select:all}}button,a.action{{min-height:48px;border-radius:12px;padding:12px 16px;font:700 16px/1.2 inherit;text-decoration:none;display:inline-grid;place-items:center;border:0;cursor:pointer}}button{{width:100%;background:#38bdf8;color:#06202b}}button.secondary{{margin-top:12px;background:#172735;color:#d8e6ef;border:1px solid #365166}}button:disabled{{cursor:default;opacity:.68}}a.action{{margin-top:12px;width:100%;background:#fff;color:#14202a}}.later-status{{min-height:22px;margin:10px 2px 0;font-size:14px;color:#8fd9b4}}.muted{{font-size:14px;color:#7f91a2}}.error{{color:#ff9b8b}}[hidden]{{display:none!important}}@media(max-width:480px){{.card{{padding:24px 20px}}}}
</style></head><body><main class="card"><h1>{title}</h1><section id="gate"><p>승인된 Google 계정으로 먼저 로그인해 주세요.</p><button id="google" type="button" disabled>로그인 준비 중…</button></section><section id="portal" hidden><p>지금 로그인해 두면 등록된 장치가 다음 동기화 때 안전하게 가져갑니다.</p><div class="status" aria-live="polite"><div id="message">상태 확인 중…</div><div id="code" class="code"></div><a id="open" class="action" hidden target="_blank" rel="noopener">OpenAI 로그인 열기</a></div><button id="start" type="button">새 로그인 시작</button><button id="later" class="secondary" type="button" hidden>나중에 Mac으로 가져오기</button><div id="later-status" class="later-status" aria-live="polite"></div><p class="muted">Mac이 꺼져 있어도 예약한 로그인은 서버에 보관됩니다. Mac에 로그인하면 자동 동기화가 실행되고, 이후에는 최대 15분 간격으로 다시 확인합니다.</p><p class="muted">Google 로그인은 포털 접근만 확인합니다. OpenAI 비밀번호는 이 사이트에 입력하지 않고 공식 OpenAI 화면에서 각 사용자가 직접 승인합니다.</p></section><p id="auth-error" class="error"></p></main><script type="module">
import {{initializeApp}} from 'https://www.gstatic.com/firebasejs/10.9.0/firebase-app.js';
import {{GoogleAuthProvider,getAuth,getRedirectResult,setPersistence,browserSessionPersistence,signInWithRedirect}} from 'https://www.gstatic.com/firebasejs/10.9.0/firebase-auth.js';
const firebaseConfig={{apiKey:{json.dumps(config.firebase_api_key)},authDomain:{json.dumps(config.firebase_auth_domain)},projectId:{json.dumps(config.firebase_project_id)},appId:{json.dumps(config.firebase_app_id)},messagingSenderId:{json.dumps(config.firebase_sender_id)}}};
const auth=getAuth(initializeApp(firebaseConfig));await setPersistence(auth,browserSessionPersistence);
const gate=document.querySelector('#gate'),portal=document.querySelector('#portal'),authError=document.querySelector('#auth-error'),google=document.querySelector('#google'),message=document.querySelector('#message'),code=document.querySelector('#code'),open=document.querySelector('#open'),start=document.querySelector('#start'),later=document.querySelector('#later'),laterStatus=document.querySelector('#later-status');let csrf='',laterBusy=false;
async function raw(path,options={{}}){{const headers={{'Content-Type':'application/json',...(options.headers||{{}})}};if(csrf)headers['X-CSRF-Token']=csrf;return fetch(path,{{cache:'no-store',credentials:'same-origin',...options,headers}})}}
async function api(path,options){{const r=await raw(path,options);if(!r.ok){{let payload={{}};try{{payload=await r.json()}}catch{{}}const error=new Error(String(payload.error||r.status));error.status=r.status;error.code=String(payload.error||'');throw error}}return r.status===204?null:r.json()}}
function enter(s){{csrf=s.csrf;gate.hidden=true;portal.hidden=false;authError.textContent='';refresh()}}
async function resume(){{const r=await raw('/api/session');if(r.ok)enter(await r.json())}}
async function acceptFirebase(result){{if(!result||!result.user)return false;const idToken=await result.user.getIdToken(true);enter(await api('/api/session',{{method:'POST',body:JSON.stringify({{idToken}})}}));return true}}
function showGoogleError(error){{const status=Number(error&&error.status||0),rawCode=String(error&&error.code||''),errorCode=rawCode.startsWith('auth/')?rawCode.slice(5):rawCode;if(status===403||errorCode==='forbidden'){{authError.textContent='이 Google 계정은 포털 관리자로 승인되지 않았습니다. 승인된 관리자 계정을 선택해 주세요.'}}else{{authError.textContent='Google 로그인을 완료하지 못했습니다.'+(errorCode?' ('+errorCode+')':'')}}google.disabled=false;google.textContent='Google로 계속'}}
try{{const redirectResult=await getRedirectResult(auth);if(redirectResult)await acceptFirebase(redirectResult)}}catch(error){{showGoogleError(error)}}
google.addEventListener('click',async()=>{{google.disabled=true;google.textContent='Google 로그인으로 이동 중…';authError.textContent='';const provider=new GoogleAuthProvider();provider.setCustomParameters({{prompt:'select_account'}});try{{await signInWithRedirect(auth,provider)}}catch(error){{showGoogleError(error)}}}});
function draw(s){{message.textContent=s.message||'';message.className=s.status==='error'?'error':'';code.textContent=s.userCode||'';if(s.verificationUrl){{open.href=s.verificationUrl;open.hidden=false}}else{{open.hidden=true}}const loginBusy=['starting','waiting'].includes(s.status);start.disabled=loginBusy;start.textContent=loginBusy?'로그인 진행 중…':'새 로그인 시작';later.hidden=!s.hasStoredLogin||loginBusy;later.disabled=laterBusy||Boolean(s.deferred);later.textContent=laterBusy?'예약 중…':s.deferred?'Mac 가져오기 예약됨':'나중에 Mac으로 가져오기';laterStatus.textContent=s.deferred?'예약 완료 — Mac에 로그인하면 자동으로 가져옵니다.':'';laterStatus.className='later-status'}}
async function refresh(){{if(portal.hidden)return;try{{draw(await api('/api/login/status'))}}catch{{message.textContent='서버 상태를 불러오지 못했습니다.';message.className='error'}}}}
start.addEventListener('click',async()=>{{start.disabled=true;try{{draw(await api('/api/login/start',{{method:'POST',body:'{{}}'}}))}}catch{{message.textContent='로그인을 시작하지 못했습니다.';message.className='error';start.disabled=false}}}});
later.addEventListener('click',async()=>{{laterBusy=true;later.disabled=true;later.textContent='예약 중…';laterStatus.textContent='';try{{draw(await api('/api/login/defer',{{method:'POST',body:'{{}}'}}))}}catch{{laterStatus.textContent='예약하지 못했습니다. 잠시 후 다시 시도해 주세요.';laterStatus.className='later-status error'}}finally{{laterBusy=false}}}});await resume();if(!gate.hidden){{google.disabled=false;google.textContent='Google로 계속'}}setInterval(refresh,2000);
</script></body></html>"""
    return page.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "cm-auth-broker"

    @property
    def broker(self) -> Broker:
        return self.server.broker  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Access and systemd already record request metadata. Never log headers/bodies.
        return

    def _cookie(self, name: str) -> str:
        for item in self.headers.get("Cookie", "").split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key == name:
                return value
        return ""

    def _human_session(self) -> dict[str, Any] | None:
        session = self.broker.validate_session(self._cookie(SESSION_COOKIE))
        if not session:
            return None
        access_email = self.headers.get(
            "Cf-Access-Authenticated-User-Email", ""
        ).strip().lower()
        if access_email and not hmac.compare_digest(access_email, str(session["email"])):
            return None
        return session

    def _same_origin(self) -> bool:
        return hmac.compare_digest(
            self.headers.get("Origin", "").rstrip("/"), self.broker.config.public_origin
        )

    def _csrf_allowed(self, session: dict[str, Any]) -> bool:
        supplied = self.headers.get("X-CSRF-Token", "")
        return self._same_origin() and bool(supplied) and hmac.compare_digest(
            supplied, str(session.get("csrf") or "")
        )

    def _mac_allowed(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
        return bool(supplied) and hmac.compare_digest(supplied, self.broker.config.mac_token)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("invalid body")
        data = self.rfile.read(length) if length else b"{}"
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("invalid json")
        return parsed

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/api/mac/pending":
            if not self._mac_allowed():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            after_job_id = parse_qs(urlparse(self.path).query).get("after", [""])[0]
            pending = self.broker.pending(after_job_id)
            if not pending:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            job_id, auth = pending
            self._json(HTTPStatus.OK, {"jobId": job_id, "auth": auth})
            return
        if path == "/api/session":
            session = self._human_session()
            if not session:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            self._json(
                HTTPStatus.OK,
                {"email": session["email"], "csrf": session["csrf"]},
            )
            return
        if path == "/":
            body = portal_html(self.broker.config)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'unsafe-inline' https://www.gstatic.com https://apis.google.com; "
                "style-src 'unsafe-inline'; "
                "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com; "
                f"frame-src https://{self.broker.config.firebase_auth_domain}; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)
            return
        session = self._human_session()
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if path == "/api/login/status":
            self._json(HTTPStatus.OK, self.broker.state())
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_request"})
            return
        if path == "/api/mac/ack":
            if not self._mac_allowed():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            ok = self.broker.acknowledge(str(payload.get("jobId") or ""))
            self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
            return
        if path == "/api/session":
            if not self._same_origin():
                self._json(HTTPStatus.FORBIDDEN, {"error": "origin_forbidden"})
                return
            try:
                user = self.broker.authenticate_firebase(str(payload.get("idToken") or ""))
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                return
            cookie, csrf = self.broker.create_session(user["email"])
            self.send_response(HTTPStatus.OK)
            body = json.dumps(
                {"email": user["email"], "csrf": csrf}, separators=(",", ":")
            ).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={cookie}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; Secure; SameSite=Strict",
            )
            self.end_headers()
            self.wfile.write(body)
            return
        session = self._human_session()
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if not self._csrf_allowed(session):
            self._json(HTTPStatus.FORBIDDEN, {"error": "csrf_forbidden"})
            return
        if path == "/api/login/start":
            created, state = self.broker.start_login()
            self._json(HTTPStatus.ACCEPTED if created else HTTPStatus.CONFLICT, state)
            return
        if path == "/api/login/defer":
            created, state = self.broker.defer_latest()
            self._json(HTTPStatus.OK if created else HTTPStatus.CONFLICT, state)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], broker: Broker):
        self.broker = broker
        super().__init__(address, Handler)


def main() -> None:
    config = Config.from_env()
    server = Server((config.bind, config.port), Broker(config))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    print(f"cm-auth-broker listening on {config.bind}:{config.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
