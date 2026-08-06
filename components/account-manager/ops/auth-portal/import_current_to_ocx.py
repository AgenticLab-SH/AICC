#!/usr/bin/env python3
"""Safely hand a stored or portal OAuth credential to the OCX account pool."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import mac_sync  # noqa: E402

OCX = os.environ.get("AICC_OCX_EXECUTABLE", "ocx").strip() or "ocx"
HEALTH_URL = mac_sync.OCX_BASE_URL + "/healthz"


def _run(*args: str, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [OCX, *args], check=False, capture_output=True, text=True, timeout=timeout
    )


def _healthy() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=1) as response:
            payload = json.loads(response.read())
        return response.status == 200 and payload.get("status") == "ok"
    except (OSError, ValueError, URLError, json.JSONDecodeError):
        return False


def _wait_for_health(expected: bool, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthy() is expected:
            return
        time.sleep(0.2)
    raise RuntimeError("OpenCodex 상태 전환을 확인하지 못했습니다.")


def _stop_proxy() -> None:
    if not _healthy():
        return
    result = _run("service", "stop")
    if result.returncode != 0:
        raise RuntimeError("실행 중인 OpenCodex를 안전하게 중지하지 못했습니다.")
    _wait_for_health(False)


def _start_gate_process() -> subprocess.Popen[bytes]:
    env = {**os.environ, "OPENCODEX_ENABLE_UNVERIFIED_CODEX_IMPORT": "1"}
    port = urlparse(mac_sync.OCX_BASE_URL).port
    if port is None:
        raise RuntimeError("OpenCodex loopback 포트를 확인할 수 없습니다.")
    process = subprocess.Popen(
        [OCX, "start", "--port", str(port)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        _wait_for_health(True)
    except Exception:
        _stop_process(process)
        raise
    return process


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass


def _start_service() -> None:
    result = _run("service", "start", timeout=60)
    if result.returncode != 0:
        result = _run("service", timeout=90)
    if result.returncode != 0:
        raise RuntimeError("gate 없는 OpenCodex 백그라운드 서비스를 시작하지 못했습니다.")
    _wait_for_health(True, timeout=30)


def _gate_persisted() -> bool:
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    for path in launch_agents.glob("*opencodex*.plist"):
        try:
            if "OPENCODEX_ENABLE_UNVERIFIED_CODEX_IMPORT" in path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def main() -> int:
    portal_mode = sys.argv[1:] == ["--portal"]
    if sys.argv[1:] not in ([], ["--portal"]):
        print(json.dumps({"ok": False, "error": "usage: import_current_to_ocx.py [--portal]"}))
        return 2
    gate_process: subprocess.Popen[bytes] | None = None
    backup: Path | None = None
    portal_job_id: str | None = None
    error: str | None = None
    no_change = False
    touched_proxy = False
    imported = False
    changed = False
    try:
        target = mac_sync._require_target_account()
        mac_sync._require_ocx_target_account()
        if portal_mode:
            latest = mac_sync.fetch_latest()
            if latest is None:
                no_change = True
                auth = None
            else:
                portal_job_id, auth = latest
                mac_sync.import_auth(auth)
        else:
            auth = mac_sync.cm.read_auth(target)
        if no_change:
            pass
        elif not isinstance(auth, dict) or not mac_sync.cm._has_usable_chatgpt_auth(auth):
            raise RuntimeError("지정된 cm 계정의 사용 가능한 인증을 찾지 못했습니다.")
        elif mac_sync.opencodex_target_matches(auth):
            mac_sync.verify_opencodex_target()
            imported = True
        else:
            mac_sync.ensure_opencodex_idle()
            backup = mac_sync.backup_ocx_state()
            touched_proxy = True
            _stop_proxy()
            gate_process = _start_gate_process()
            mac_sync.import_into_opencodex(auth)
            mac_sync.verify_opencodex_target()
            imported = True
            changed = True
    except Exception as exc:
        error = str(exc)
    finally:
        if gate_process is not None:
            _stop_process(gate_process)
            try:
                _wait_for_health(False, timeout=15)
            except RuntimeError:
                pass
        if touched_proxy and error is not None and backup is not None:
            try:
                mac_sync.restore_ocx_state(backup)
            except Exception as restore_exc:
                error = f"{error}; OpenCodex 백업 복원 실패: {restore_exc}"
        if touched_proxy:
            try:
                _start_service()
            except Exception as service_exc:
                if error is None:
                    error = str(service_exc)

    if no_change:
        gate_persisted = _gate_persisted()
        healthy = _healthy()
        payload = {
            "ok": healthy and not gate_persisted,
            "changed": False,
            "portal": True,
            "serviceHealthy": healthy,
            "gatePersisted": gate_persisted,
        }
        print(json.dumps(payload))
        return 0 if payload["ok"] else 1

    if _gate_persisted():
        error = "OpenCodex import gate가 서비스 설정에 남아 있어 완료로 처리하지 않았습니다."
    if error is None and portal_job_id is not None:
        try:
            mac_sync.acknowledge_latest(portal_job_id)
        except Exception as ack_exc:
            error = str(ack_exc)
    payload = {
        "ok": error is None and imported and _healthy(),
        "imported": imported,
        "changed": changed,
        "portal": portal_mode,
        "serviceHealthy": _healthy(),
        "gatePersisted": _gate_persisted(),
    }
    if error:
        payload["error"] = error
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
