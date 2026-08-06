#!/usr/bin/env python3
"""Fetch one pending auth payload and import it into a configured cm account."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LOCAL_DIR = Path(__file__).resolve().parents[1] / "local"
PORTAL_DIR = Path(__file__).resolve().parent
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

import codex_multi as cm  # noqa: E402


LOCAL_CONFIG_FILE = Path(
    os.environ.get(
        "CM_AUTH_LOCAL_CONFIG",
        str(
            Path(
                os.environ.get(
                    "AICC_ACCOUNT_MANAGER_STATE_ROOT",
                    Path(os.environ.get("AICC_STATE_ROOT", Path.home() / ".ai-control-center"))
                    / "account-manager",
                )
            )
            / "auth-portal.env"
        ),
    )
).expanduser()


def _load_local_config(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("CM_AUTH_") or key == "OPENCODEX_HOME":
            os.environ.setdefault(key, value.strip().strip("\"'"))


_load_local_config(LOCAL_CONFIG_FILE)

TARGET_ACCOUNT = os.environ.get("CM_AUTH_TARGET_ACCOUNT", "").strip()
OCX_TARGET_ACCOUNT = os.environ.get("CM_AUTH_OCX_TARGET_ACCOUNT", "").strip()
KEYCHAIN_SERVICE = os.environ.get(
    "CM_AUTH_KEYCHAIN_SERVICE", "com.aicc.account-manager.auth-portal"
).strip()
OCX_BASE_URL = os.environ.get("CM_AUTH_OCX_BASE_URL", "http://127.0.0.1:10100").rstrip("/")
PORTAL_URL = os.environ.get("CM_AUTH_PORTAL_URL", "").rstrip("/")
OCX_HOME = Path(os.environ.get("OPENCODEX_HOME", str(Path.home() / ".opencodex"))).expanduser()
OCX_LOCK = OCX_HOME / ".cm-auth-import.lock"
OCX_BACKUP_FILES = ("config.json", "codex-accounts.json")
OCX_ADMIN_TOKEN_FILE = OCX_HOME / "admin-api-token"
OCX_BACKUP_ROOT = OCX_HOME / "cm-auth-backups"
SYNC_STATE_FILE = LOCAL_CONFIG_FILE.with_name("auth-portal-sync.json")
BACKUPS_TO_KEEP = 3


def _token() -> str:
    from_env = os.environ.get("CM_AUTH_PORTAL_MAC_TOKEN", "").strip()
    if from_env:
        return from_env
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Mac Keychain에 인증 포털 키가 없습니다.")
    return result.stdout.strip()


def _require_target_account() -> str:
    if not TARGET_ACCOUNT:
        raise RuntimeError(
            f"CM_AUTH_TARGET_ACCOUNT is not configured in {LOCAL_CONFIG_FILE}"
        )
    return TARGET_ACCOUNT


def _require_ocx_target_account() -> str:
    if not OCX_TARGET_ACCOUNT:
        raise RuntimeError(
            f"CM_AUTH_OCX_TARGET_ACCOUNT is not configured in {LOCAL_CONFIG_FILE}"
        )
    return OCX_TARGET_ACCOUNT


def _request(base_url: str, token: str, path: str, *, payload: dict[str, Any] | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        method="GET" if payload is None else "POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "cm-auth-sync/1.0",
        },
    )
    try:
        return urlopen(request, timeout=20)
    except HTTPError as exc:
        if exc.code == 204:
            return exc
        raise RuntimeError(f"인증 포털 HTTP 오류: {exc.code}") from None
    except URLError as exc:
        raise RuntimeError("인증 포털에 연결할 수 없습니다.") from exc


def _ocx_admin_token() -> str:
    from_env = os.environ.get("OPENCODEX_ADMIN_AUTH_TOKEN", "").strip()
    if from_env:
        token = from_env
    else:
        try:
            info = OCX_ADMIN_TOKEN_FILE.lstat()
            if not stat.S_ISREG(info.st_mode) or OCX_ADMIN_TOKEN_FILE.is_symlink():
                raise RuntimeError
            if info.st_size > 512 or info.st_mode & 0o077:
                raise RuntimeError
            token = OCX_ADMIN_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except (OSError, RuntimeError):
            raise RuntimeError("OpenCodex 관리 인증 파일을 안전하게 읽을 수 없습니다.") from None
    if not re.fullmatch(r"ocx_admin_[A-Za-z0-9_-]{43}", token):
        raise RuntimeError("OpenCodex 관리 인증 형식이 올바르지 않습니다.")
    return token


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    staging = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    staging.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staging.chmod(0o600)
    os.replace(staging, path)


def last_applied_job_id() -> str:
    return str(_read_json(SYNC_STATE_FILE).get("jobId") or "")


def fetch_latest(base_url: str | None = None) -> tuple[str, dict[str, Any]] | None:
    base_url = (base_url or PORTAL_URL).rstrip("/")
    if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
        raise RuntimeError(
            f"CM_AUTH_PORTAL_URL must be HTTPS or loopback in {LOCAL_CONFIG_FILE}"
        )
    after = last_applied_job_id()
    path = "/api/mac/pending"
    if after:
        path += "?after=" + quote(after, safe="")
    response = _request(base_url, _token(), path)
    if getattr(response, "status", None) == 204:
        return None
    body = json.loads(response.read())
    job_id = str(body.get("jobId") or "")
    auth = body.get("auth")
    if not job_id or not isinstance(auth, dict):
        raise RuntimeError("인증 포털 응답이 올바르지 않습니다.")
    return job_id, auth


def acknowledge_latest(job_id: str, base_url: str | None = None) -> None:
    base_url = (base_url or PORTAL_URL).rstrip("/")
    ack = _request(base_url, _token(), "/api/mac/ack", payload={"jobId": job_id})
    result = json.loads(ack.read())
    if result.get("ok") is not True:
        raise RuntimeError("토큰은 반영했지만 서버 수령 확인에 실패했습니다.")
    _write_private_json(
        SYNC_STATE_FILE,
        {"jobId": job_id, "appliedAt": datetime.now().astimezone().isoformat()},
    )


def import_auth(auth: dict[str, Any]) -> str:
    target_account = _require_target_account()
    current = cm.read_auth(target_account)
    old_id = cm._account_id(current)
    new_id = cm._account_id(auth)
    if not old_id or not new_id or old_id != new_id:
        raise RuntimeError("대상 계정 ID가 일치하지 않아 저장하지 않았습니다.")
    if not cm._has_usable_chatgpt_auth(auth):
        raise RuntimeError("가져온 대상 인증이 유효하지 않습니다.")
    quota = cm.fetch_quota(auth, account_name=target_account)
    if not quota.get("ok") and quota.get("error") == "expired":
        raise RuntimeError("가져온 대상 인증이 이미 만료되었습니다.")
    cm.save_auth(target_account, auth)
    if cm.get_active_account() == target_account:
        cm.shutil.copy2(cm.get_auth_path(target_account), cm.CODEX_HOME / "auth.json")
    return target_account


def _json_request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        OCX_BASE_URL + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Origin": OCX_BASE_URL,
            "X-OpenCodex-API-Key": _ocx_admin_token(),
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except (ValueError, json.JSONDecodeError):
            body = {}
        return exc.code, body
    except URLError as exc:
        raise RuntimeError("OpenCodex loopback API에 연결할 수 없습니다.") from exc


def ensure_opencodex_idle() -> None:
    status, payload = _json_request("/api/system/memory")
    if status != 200 or not isinstance(payload.get("activeTurnCount"), int):
        raise RuntimeError("OpenCodex 실행 중 요청 수를 확인할 수 없습니다.")
    if payload["activeTurnCount"] > 0 or payload.get("isDraining") is True:
        raise RuntimeError("OpenCodex에 진행 중인 응답이 있어 OAuth 갱신을 다음 주기로 미룹니다.")


@contextmanager
def _single_writer_lock():
    OCX_HOME.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(OCX_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError("다른 OpenCodex 인증 가져오기가 진행 중입니다.") from None
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        OCX_LOCK.unlink(missing_ok=True)


def backup_ocx_state() -> Path:
    OCX_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    OCX_BACKUP_ROOT.chmod(0o700)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=OCX_BACKUP_ROOT))
    os.chmod(backup, 0o700)
    for name in OCX_BACKUP_FILES:
        source = OCX_HOME / name
        if source.is_file():
            shutil.copy2(source, backup / name)
    backups = sorted((path for path in OCX_BACKUP_ROOT.iterdir() if path.is_dir()), reverse=True)
    for old in backups[BACKUPS_TO_KEEP:]:
        shutil.rmtree(old)
    return backup


def restore_ocx_state(backup: Path) -> None:
    """Restore a stopped OCX service from a private pre-import snapshot."""
    backup = Path(backup).resolve()
    if backup.parent != OCX_BACKUP_ROOT.resolve():
        raise RuntimeError("OpenCodex 백업 경로가 올바르지 않습니다.")
    for name in OCX_BACKUP_FILES:
        source = backup / name
        if not source.is_file():
            continue
        destination = OCX_HOME / name
        staging = destination.with_name(f".{destination.name}.restore-{os.getpid()}")
        shutil.copy2(source, staging)
        staging.chmod(0o600)
        os.replace(staging, destination)


def _stored_ocx_account(account_id: str) -> dict[str, Any] | None:
    config = _read_json(OCX_HOME / "config.json")
    rows = config.get("codexAccounts")
    row = next(
        (
            value for value in rows or []
            if isinstance(value, dict) and value.get("id") == account_id and not value.get("isMain")
        ),
        None,
    )
    records = _read_json(OCX_HOME / "codex-accounts.json")
    record = records.get(account_id)
    credential = record.get("credential") if isinstance(record, dict) else None
    if not isinstance(row, dict) or not isinstance(credential, dict):
        return None
    return {"row": row, "credential": credential}


def _restore_ocx_metadata(stored: dict[str, Any], *, paused: bool) -> None:
    alias = stored["row"].get("alias")
    if alias:
        status, result = _json_request(
            "/api/codex-auth/accounts/alias",
            method="PUT",
            payload={"id": OCX_TARGET_ACCOUNT, "alias": alias},
        )
        if status != 200 or result.get("ok") is not True:
            raise RuntimeError("OpenCodex 대상 별칭 복구에 실패했습니다.")
    if paused:
        status, result = _json_request(
            "/api/codex-auth/accounts/pause",
            method="PUT",
            payload={"id": OCX_TARGET_ACCOUNT, "paused": True},
        )
        if status != 200 or result.get("ok") is not True:
            raise RuntimeError("OpenCodex 대상 일시 중지 상태 복구에 실패했습니다.")


def _ocx_tokens(auth: dict[str, Any]) -> dict[str, str]:
    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    if not isinstance(tokens, dict):
        raise RuntimeError("OpenCodex에 가져올 인증 토큰이 없습니다.")
    result = {
        "accessToken": str(tokens.get("access_token") or "").strip(),
        "refreshToken": str(tokens.get("refresh_token") or "").strip(),
        "chatgptAccountId": str(tokens.get("account_id") or "").strip(),
    }
    if not all(result.values()):
        raise RuntimeError("OpenCodex native import에 필요한 인증 필드가 없습니다.")
    return result


def opencodex_target_matches(auth: dict[str, Any]) -> bool:
    """Return whether the stable slot already contains this exact credential."""
    _require_ocx_target_account()
    tokens = _ocx_tokens(auth)
    stored = _stored_ocx_account(OCX_TARGET_ACCOUNT)
    if stored is None:
        return False
    row = stored["row"]
    credential = stored["credential"]
    if str(row.get("email") or "").strip().lower() != TARGET_ACCOUNT.lower():
        raise RuntimeError("OpenCodex 대상 슬롯의 계정 이메일이 일치하지 않습니다.")
    if str(credential.get("chatgptAccountId") or "") != tokens["chatgptAccountId"]:
        raise RuntimeError("OpenCodex 대상 슬롯의 ChatGPT 계정 ID가 일치하지 않습니다.")
    return (
        credential.get("accessToken") == tokens["accessToken"]
        and credential.get("refreshToken") == tokens["refreshToken"]
    )


def import_into_opencodex(auth: dict[str, Any]) -> str:
    """Create or replace one explicit OCX pool slot through the native API."""
    _require_ocx_target_account()
    tokens = _ocx_tokens(auth)
    with _single_writer_lock():
        status, before = _json_request("/api/codex-auth/accounts")
        if status != 200 or not isinstance(before.get("accounts"), list):
            raise RuntimeError("OpenCodex 계정 목록을 확인할 수 없습니다.")
        target_before = next(
            (
                row for row in before["accounts"]
                if isinstance(row, dict) and row.get("id") == OCX_TARGET_ACCOUNT
            ),
            None,
        )
        active_status, active = _json_request("/api/codex-auth/active")
        if active_status != 200:
            raise RuntimeError("OpenCodex 활성 계정을 확인할 수 없습니다.")
        prior_active = active.get("activeCodexAccountId")
        backup_ocx_state()
        created = False
        replaced = False
        stored = _stored_ocx_account(OCX_TARGET_ACCOUNT) if target_before else None
        if target_before:
            if stored is None:
                raise RuntimeError("OpenCodex 기존 대상 자격증명을 안전하게 확인할 수 없습니다.")
            old_row = stored["row"]
            old_credential = stored["credential"]
            if opencodex_target_matches(auth):
                return OCX_TARGET_ACCOUNT
            status, result = _json_request(
                f"/api/codex-auth/accounts?id={quote(OCX_TARGET_ACCOUNT, safe='')}",
                method="DELETE",
            )
            if status != 200 or result.get("ok") is not True:
                raise RuntimeError("OpenCodex 기존 대상 슬롯을 갱신 준비 상태로 만들지 못했습니다.")
            replaced = True
        try:
            status, result = _json_request(
                "/api/codex-auth/accounts",
                method="POST",
                payload={
                    "id": OCX_TARGET_ACCOUNT,
                    "email": TARGET_ACCOUNT,
                    **(
                        {"plan": stored["row"].get("plan")}
                        if stored and stored["row"].get("plan")
                        else {}
                    ),
                    **tokens,
                },
            )
            if status != 200 or result.get("ok") is not True:
                code = result.get("code") if isinstance(result, dict) else None
                if code == "manual_import_disabled":
                    raise RuntimeError("OpenCodex 일회성 native import gate가 준비되지 않았습니다.")
                raise RuntimeError("OpenCodex native import 검증에 실패했습니다.")
            created = True
            if stored:
                _restore_ocx_metadata(
                    stored,
                    paused=bool(target_before and target_before.get("paused") is True),
                )
            status, after = _json_request("/api/codex-auth/accounts?refresh=1")
            rows = after.get("accounts") if status == 200 else None
            target = next(
                (row for row in rows or [] if isinstance(row, dict) and row.get("id") == OCX_TARGET_ACCOUNT),
                None,
            )
            if not target or target.get("hasCredential") is not True or target.get("needsReauth") is True:
                raise RuntimeError("OpenCodex 대상 계정 검증 결과가 올바르지 않습니다.")
            return OCX_TARGET_ACCOUNT
        except Exception:
            if created:
                rollback_status, rollback = _json_request(
                    f"/api/codex-auth/accounts?id={quote(OCX_TARGET_ACCOUNT, safe='')}", method="DELETE"
                )
                if rollback_status != 200 or rollback.get("ok") is not True:
                    raise RuntimeError("OpenCodex native rollback에 실패했습니다.") from None
            if replaced and stored:
                old = stored["credential"]
                rollback_status, rollback = _json_request(
                    "/api/codex-auth/accounts",
                    method="POST",
                    payload={
                        "id": OCX_TARGET_ACCOUNT,
                        "email": stored["row"]["email"],
                        **({"plan": stored["row"].get("plan")} if stored["row"].get("plan") else {}),
                        "accessToken": old.get("accessToken"),
                        "refreshToken": old.get("refreshToken"),
                        "chatgptAccountId": old.get("chatgptAccountId"),
                    },
                )
                if rollback_status != 200 or rollback.get("ok") is not True:
                    raise RuntimeError("OpenCodex 기존 자격증명 rollback에 실패했습니다.") from None
                _restore_ocx_metadata(
                    stored,
                    paused=bool(target_before and target_before.get("paused") is True),
                )
            raise
        finally:
            _json_request("/api/codex-auth/active", method="PUT", payload={"accountId": prior_active})


def verify_opencodex_target() -> bool:
    """Confirm the imported target through the native CLI without selecting it."""
    _require_ocx_target_account()
    result = subprocess.run(
        ["ocx", "account", "refresh", "openai", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("OpenCodex target access test에 실패했습니다.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("OpenCodex target access test 응답이 올바르지 않습니다.") from None
    rows = payload.get("accounts") if isinstance(payload, dict) else None
    target = next(
        (row for row in rows or [] if isinstance(row, dict) and row.get("id") == OCX_TARGET_ACCOUNT),
        None,
    )
    if not target or target.get("needsReauth") is True:
        raise RuntimeError("OpenCodex target access test가 인증을 확인하지 못했습니다.")
    return True


def sync_once(base_url: str | None = None) -> bool:
    latest = fetch_latest(base_url)
    if latest is None:
        return False
    job_id, auth = latest
    import_auth(auth)
    if os.environ.get("CM_AUTH_SYNC_OPENCODEX", "").strip() == "1":
        import_into_opencodex(auth)
        verify_opencodex_target()
    acknowledge_latest(job_id, base_url)
    return True


def main() -> int:
    if os.environ.get("CM_AUTH_SYNC_OPENCODEX", "").strip() == "1":
        result = subprocess.run(
            [sys.executable, str(PORTAL_DIR / "import_current_to_ocx.py"), "--portal"],
            check=False,
        )
        return result.returncode
    try:
        changed = sync_once()
    except Exception as exc:
        print(f"cm auth sync: {exc}", file=sys.stderr)
        return 1
    print("cm auth sync: 인증을 가져왔습니다." if changed else "cm auth sync: 대기 중인 인증이 없습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
