"""Windows-native app-server bridge for Codex Desktop SSH connections.

The Codex Desktop SSH transport expects a POSIX remote shell and a Unix-domain
WebSocket listener.  On this machine WSL supplies only the SSH/login-shell
transport.  When the SSH client opens ``codex app-server proxy``, this helper
starts the selected account's native Windows ``codex.exe`` on an ephemeral
loopback WebSocket port and forwards the SSH stdio stream byte-for-byte.

The native app-server is a child of the proxy and is stopped when the SSH
stream closes.  No TCP listener is exposed beyond Windows loopback.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


STATE_NAME = "wsl-ssh-runtime.json"
LOG_NAME = "native-ssh-app-server.log"
LOG_PREVIOUS_NAME = "native-ssh-app-server.previous.log"
MAX_LOG_BYTES = 2 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
STILL_ACTIVE = 259

if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _KERNEL32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    _KERNEL32.GetProcessTimes.restype = wintypes.BOOL
    _KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateProcess.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
else:  # pragma: no cover - bridge execution is Windows-only
    _KERNEL32 = None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _state_path(manager_dir: Path) -> Path:
    return manager_dir / STATE_NAME


def _update_state(manager_dir: Path, updates: dict) -> dict:
    path = _state_path(manager_dir)
    state = _read_json(path)
    state.update(updates)
    state["schema_version"] = max(2, int(state.get("schema_version") or 0))
    _write_json(path, state)
    return state


def _target(manager_dir: Path) -> tuple[dict, Path, Path]:
    state = _read_json(_state_path(manager_dir))
    home_text = str(state.get("native_home") or "").strip()
    exe_text = str(state.get("native_codex_exe") or "").strip()
    if not state.get("running") or not home_text or not exe_text:
        raise RuntimeError("cm SSH target is not prepared")
    home = Path(home_text).resolve()
    exe = Path(exe_text).resolve()
    if not home.is_dir() or not (home / "auth.json").is_file():
        raise RuntimeError("selected account's native CODEX_HOME is not ready")
    if not exe.is_file() or exe.name.casefold() != "codex.exe":
        raise RuntimeError("native Windows codex.exe is unavailable")
    return state, home, exe


def _rotate_log(manager_dir: Path) -> Path:
    log = manager_dir / LOG_NAME
    previous = manager_dir / LOG_PREVIOUS_NAME
    try:
        if log.stat().st_size > MAX_LOG_BYTES:
            if previous.exists():
                previous.unlink()
            os.replace(log, previous)
    except OSError:
        pass
    return log


def _creation_marker(pid: int) -> int | None:
    if os.name != "nt":
        return None
    process_query_limited_information = 0x1000
    handle = _KERNEL32.OpenProcess(
        process_query_limited_information, False, int(pid)
    )
    if not handle:
        return None
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        ok = _KERNEL32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    finally:
        _KERNEL32.CloseHandle(handle)


def _process_identity(pid: object) -> tuple[Path, int] | None:
    if os.name != "nt":
        return None
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return None
    if pid_value <= 0:
        return None

    process_query_limited_information = 0x1000
    handle = _KERNEL32.OpenProcess(
        process_query_limited_information, False, pid_value
    )
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value != STILL_ACTIVE:
            return None

        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _KERNEL32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return None
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not _KERNEL32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        marker = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return Path(buffer.value), marker
    finally:
        _KERNEL32.CloseHandle(handle)


def _terminate_owned(pid: object, expected_exe: object, expected_created: object) -> bool:
    try:
        pid_value = int(pid)
        marker = int(expected_created)
        expected = Path(str(expected_exe)).resolve()
    except (TypeError, ValueError, OSError):
        return False
    identity = _process_identity(pid_value)
    if identity is None:
        return False
    actual, actual_marker = identity
    if actual_marker != marker or os.path.normcase(str(actual.resolve())) != os.path.normcase(str(expected)):
        return False

    process_terminate = 0x0001
    handle = _KERNEL32.OpenProcess(process_terminate, False, pid_value)
    if not handle:
        return False
    try:
        return bool(_KERNEL32.TerminateProcess(handle, 0))
    finally:
        _KERNEL32.CloseHandle(handle)


def _wait_ready(port: int, process: subprocess.Popen, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    request = b"GET /readyz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"native app-server exited with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5) as probe:
                probe.sendall(request)
                response = probe.recv(256)
                if b" 200 " in response.split(b"\r\n", 1)[0]:
                    return
        except OSError as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"native app-server did not become ready: {last_error}")


def _start_native_server(manager_dir: Path) -> tuple[subprocess.Popen, int, Path]:
    _, home, exe = _target(manager_dir)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    log_path = _rotate_log(manager_dir)
    log_handle = log_path.open("ab", buffering=0)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    args = [
        str(exe),
        "-c",
        "features.code_mode_host=true",
        "app-server",
        "--listen",
        f"ws://127.0.0.1:{port}",
    ]
    try:
        process = subprocess.Popen(
            args,
            cwd=str(Path.home()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        )
    except Exception:
        log_handle.close()
        raise
    process._codex_log_handle = log_handle  # type: ignore[attr-defined]
    try:
        _wait_ready(port, process)
    except Exception:
        _stop_child(process)
        raise
    return process, port, exe


def _stop_child(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=4)
    handle = getattr(process, "_codex_log_handle", None)
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass


def _pump_stdin(connection: socket.socket) -> None:
    try:
        while True:
            # BufferedReader.read(size) can wait for the full size on a pipe,
            # which deadlocks the WebSocket handshake while the SSH stream is
            # intentionally kept open. os.read returns the currently available
            # bytes as soon as the client writes them.
            chunk = os.read(sys.stdin.fileno(), 65536)
            if not chunk:
                break
            connection.sendall(chunk)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    finally:
        try:
            connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def command_proxy(manager_dir: Path) -> int:
    state, _, _ = _target(manager_dir)
    helper_created = _creation_marker(os.getpid())
    _update_state(
        manager_dir,
        {
            "native_bridge_pid": os.getpid(),
            "native_bridge_created": helper_created,
            "native_bridge_exe": sys.executable,
            "native_server_pid": None,
            "native_server_created": None,
            "native_server_port": None,
            "native_connected_at": time.time(),
        },
    )
    process: subprocess.Popen | None = None
    connection: socket.socket | None = None
    try:
        process, port, exe = _start_native_server(manager_dir)
        server_created = _creation_marker(process.pid)
        _update_state(
            manager_dir,
            {
                "native_server_pid": process.pid,
                "native_server_created": server_created,
                "native_server_exe": str(exe),
                "native_server_port": port,
            },
        )
        connection = socket.create_connection(("127.0.0.1", port), timeout=10)
        connection.settimeout(None)
        sender = threading.Thread(target=_pump_stdin, args=(connection,), daemon=True)
        sender.start()
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        return 0
    except Exception as exc:
        print(f"native Codex SSH bridge failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        if process is not None:
            _stop_child(process)
        latest = _read_json(_state_path(manager_dir))
        if latest.get("native_bridge_pid") == os.getpid():
            _update_state(
                manager_dir,
                {
                    "native_bridge_pid": None,
                    "native_bridge_created": None,
                    "native_bridge_exe": None,
                    "native_server_pid": None,
                    "native_server_created": None,
                    "native_server_exe": None,
                    "native_server_port": None,
                    "native_disconnected_at": time.time(),
                },
            )


def command_stop(manager_dir: Path) -> int:
    state = _read_json(_state_path(manager_dir))
    _terminate_owned(
        state.get("native_server_pid"),
        state.get("native_server_exe"),
        state.get("native_server_created"),
    )
    _terminate_owned(
        state.get("native_bridge_pid"),
        state.get("native_bridge_exe"),
        state.get("native_bridge_created"),
    )
    _update_state(
        manager_dir,
        {
            "native_bridge_pid": None,
            "native_bridge_created": None,
            "native_bridge_exe": None,
            "native_server_pid": None,
            "native_server_created": None,
            "native_server_exe": None,
            "native_server_port": None,
            "native_disconnected_at": time.time(),
        },
    )
    return 0


def command_version(manager_dir: Path) -> int:
    _, home, exe = _target(manager_dir)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    result = subprocess.run(
        [str(exe), "--version"],
        cwd=str(Path.home()),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    output = (result.stdout or result.stderr).strip()
    if output:
        print(output)
    return int(result.returncode)


def command_bootstrap(manager_dir: Path, *, daemon_json: bool = False) -> int:
    state, _, exe = _target(manager_dir)
    if daemon_json:
        version = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        ).stdout.strip()
        payload = {
            "status": "bootstrapped",
            "backend": "windows-native-ssh-bridge",
            "managedCodexPath": str(exe),
            "managedCodexVersion": version.replace("codex-cli ", ""),
            "cliVersion": version.replace("codex-cli ", ""),
            "appServerVersion": version.replace("codex-cli ", ""),
            "targetAccount": state.get("target_account"),
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def command_daemon_version(manager_dir: Path) -> int:
    state, _, exe = _target(manager_dir)
    identity = _process_identity(state.get("native_server_pid"))
    version = subprocess.run(
        [str(exe), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    ).stdout.strip().replace("codex-cli ", "")
    payload = {
        "status": "running" if identity else "stopped",
        "backend": "windows-native-ssh-bridge",
        "managedCodexPath": str(exe),
        "managedCodexVersion": version,
        "cliVersion": version,
        "appServerVersion": version,
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "daemon-bootstrap", "daemon-version", "proxy", "stop", "version"))
    parser.add_argument("--manager-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manager_dir = args.manager_dir.resolve()
    if args.command == "proxy":
        return command_proxy(manager_dir)
    if args.command == "stop":
        return command_stop(manager_dir)
    if args.command == "version":
        return command_version(manager_dir)
    if args.command == "daemon-version":
        return command_daemon_version(manager_dir)
    return command_bootstrap(manager_dir, daemon_json=args.command == "daemon-bootstrap")


if __name__ == "__main__":
    raise SystemExit(main())
