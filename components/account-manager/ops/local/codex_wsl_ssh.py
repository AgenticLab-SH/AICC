"""On-demand WSL SSH lifecycle for Codex Desktop remote connections.

This module never starts WSL for a read-only status check.  A target start is
transactional: stop the previous Codex daemon, prepare an account-specific
Linux CODEX_HOME, then start only ssh.service.  The desktop SSH client starts
the Codex app-server when it actually connects.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path


SCHEMA_VERSION = 2
CONFIG_NAME = "wsl-ssh.json"
STATE_NAME = "wsl-ssh-runtime.json"
DEFAULT_DISTRO = "Ubuntu-24.04"
DEFAULT_PORT = 2222
KEEPALIVE_UNIT = "codex-ssh-keepalive.service"
BRIDGE_SOURCE_NAME = "codex_native_ssh_bridge.py"
DISPATCH_SOURCE_NAME = "codex_wsl_native_dispatch.sh"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _default_linux_user() -> str:
    return (
        os.environ.get("CM_WSL_USER", "").strip()
        or os.environ.get("USERNAME", "").strip()
    )


def _linux_user(config: dict) -> str:
    user = str(config.get("linux_user") or _default_linux_user()).strip()
    if not user:
        raise RuntimeError("WSL Linux user is not configured; set CM_WSL_USER or run cm ssh setup")
    return user


def _default_config() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": False,
        "distro": DEFAULT_DISTRO,
        "linux_user": _default_linux_user(),
        "port": DEFAULT_PORT,
        "main_account": None,
        "execution_mode": "windows-native",
        "auto_start_secondary_app": True,
        "auto_stop_idle_on_cm_start": True,
    }


def _json_path(manager_dir: Path, name: str) -> Path:
    return Path(manager_dir) / name


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


def load_config(manager_dir: Path) -> dict:
    result = _default_config()
    result.update(_read_json(_json_path(manager_dir, CONFIG_NAME)))
    return result


def save_config(manager_dir: Path, updates: dict) -> dict:
    config = load_config(manager_dir)
    config.update(updates)
    config["schema_version"] = SCHEMA_VERSION
    _write_json(_json_path(manager_dir, CONFIG_NAME), config)
    return config


def load_state(manager_dir: Path) -> dict:
    return _read_json(_json_path(manager_dir, STATE_NAME))


def save_state(manager_dir: Path, updates: dict) -> dict:
    state = load_state(manager_dir)
    state.update(updates)
    state["schema_version"] = SCHEMA_VERSION
    _write_json(_json_path(manager_dir, STATE_NAME), state)
    return state


def _run(args: list[str], *, timeout: float = 15, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
    )


def _clean_wsl_output(value: str) -> str:
    return (value or "").replace("\x00", "").replace("\r", "").strip()


def _running_distros() -> set[str]:
    if os.name != "nt":
        return set()
    try:
        result = _run(["wsl.exe", "--list", "--running", "--quiet"], timeout=5)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in _clean_wsl_output(result.stdout).splitlines() if line.strip()}


def distro_running(distro: str) -> bool:
    return distro.casefold() in {name.casefold() for name in _running_distros()}


def _wsl(
    distro: str,
    args: list[str],
    *,
    user: str | None = None,
    timeout: float = 20,
    check: bool = False,
) -> subprocess.CompletedProcess:
    command = ["wsl.exe", "-d", distro]
    if user:
        command += ["-u", user]
    command += ["--"] + list(args)
    return _run(command, timeout=timeout, check=check)


def _wsl_shell(
    distro: str,
    script: str,
    *,
    user: str | None = None,
    timeout: float = 20,
    check: bool = False,
) -> subprocess.CompletedProcess:
    return _wsl(distro, ["bash", "-lc", script], user=user, timeout=timeout, check=check)


def windows_to_wsl_path(distro: str, path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if len(drive) != 1 or not drive.isalpha():
        raise RuntimeError(f"Only local Windows drive paths are supported: {path}")
    normalized = resolved.as_posix()
    prefix = f"{drive.upper()}:/"
    if normalized[:3].casefold() != prefix.casefold():
        raise RuntimeError(f"Windows path prefix could not be converted: {path}")
    relative = normalized[3:]
    value = f"/mnt/{drive}/{relative}"
    check_result = _wsl(distro, ["test", "-e", value], timeout=10)
    if check_result.returncode != 0:
        raise RuntimeError(f"WSL path does not exist: {path}")
    return value


def _pid_alive(pid: object) -> bool:
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_value <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid_value
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            try:
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid_value, 0)
        return True
    except OSError:
        return False


def _bridge_source_path() -> Path:
    return Path(__file__).with_name(BRIDGE_SOURCE_NAME).resolve()


def _dispatch_source_path() -> Path:
    return Path(__file__).with_name(DISPATCH_SOURCE_NAME).resolve()


def _stop_native_bridge(manager_dir: Path) -> None:
    bridge = _bridge_source_path()
    if not bridge.is_file():
        return
    _run(
        [
            sys.executable,
            str(bridge),
            "stop",
            "--manager-dir",
            str(Path(manager_dir).resolve()),
        ],
        timeout=12,
    )


def status(manager_dir: Path) -> dict:
    config = load_config(manager_dir)
    state = load_state(manager_dir)
    distro = str(config.get("distro") or DEFAULT_DISTRO)
    result = {
        "configured": bool(config.get("enabled") and config.get("main_account")),
        "enabled": bool(config.get("enabled")),
        "distro": distro,
        "linux_user": str(config.get("linux_user") or ""),
        "port": int(config.get("port") or DEFAULT_PORT),
        "main_account": config.get("main_account"),
        "target_account": state.get("target_account"),
        "target_app_pid": state.get("target_app_pid"),
        "target_app_running": _pid_alive(state.get("target_app_pid")),
        "execution_mode": config.get("execution_mode") or "windows-native",
        "native_bridge_running": _pid_alive(state.get("native_bridge_pid")),
        "native_server_running": _pid_alive(state.get("native_server_pid")),
        "native_server_port": state.get("native_server_port"),
        "native_home": state.get("native_home"),
        "keeper_running": _pid_alive(state.get("keeper_pid")),
        "wsl_running": False,
        "ssh_active": False,
        "connections": 0,
        "runtime_bytes": 0,
        "idle": False,
        "error": None,
    }
    if not distro_running(distro):
        return result

    result["wsl_running"] = True
    try:
        active = _wsl(distro, ["systemctl", "is-active", "ssh.service"], user="root", timeout=5)
        result["ssh_active"] = _clean_wsl_output(active.stdout) == "active"
        if result["ssh_active"]:
            port = int(result["port"])
            connections = _wsl_shell(
                distro,
                f"ss -Htn state established '( sport = :{port} )' 2>/dev/null | wc -l",
                user="root",
                timeout=5,
            )
            text = _clean_wsl_output(connections.stdout)
            result["connections"] = int(text) if text.isdigit() else 0
        user_name = str(result["linux_user"])
        size = _wsl(
            distro,
            ["du", "-sb", f"/home/{user_name}/.codex-ssh", f"/home/{user_name}/.codex-ssh-shared"],
            user="root",
            timeout=5,
        )
        total_size = 0
        for line in _clean_wsl_output(size.stdout).splitlines():
            first = line.split(maxsplit=1)[0] if line.strip() else ""
            if first.isdigit():
                total_size += int(first)
        result["runtime_bytes"] = total_size
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        result["error"] = exc.__class__.__name__

    result["idle"] = bool(
        result["ssh_active"]
        and result["connections"] == 0
        and not result["target_app_running"]
    )
    return result


def _stop_daemon_if_running(config: dict) -> None:
    distro = str(config.get("distro") or DEFAULT_DISTRO)
    if not distro_running(distro):
        return
    user = _linux_user(config)
    _wsl(
        distro,
        [
            "env",
            f"CODEX_HOME=/home/{user}/.codex-ssh-current",
            "/usr/local/bin/codex",
            "app-server",
            "daemon",
            "stop",
        ],
        user=user,
        timeout=12,
    )


def stop(manager_dir: Path, *, reason: str = "manual") -> dict:
    config = load_config(manager_dir)
    distro = str(config.get("distro") or DEFAULT_DISTRO)
    try:
        _stop_native_bridge(manager_dir)
    except (OSError, subprocess.SubprocessError):
        pass
    running_before = _running_distros()
    if distro.casefold() in {name.casefold() for name in running_before}:
        try:
            _stop_daemon_if_running(config)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            _wsl(distro, ["systemctl", "stop", "ssh.service"], user="root", timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            _wsl(distro, ["systemctl", "stop", KEEPALIVE_UNIT], user="root", timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        _run(["wsl.exe", "--terminate", distro], timeout=15)
        other_running = {name for name in running_before if name.casefold() != distro.casefold()}
        if not other_running:
            # Release the lightweight VM and its file cache immediately when
            # doing so cannot interrupt another running distro.
            _run(["wsl.exe", "--shutdown"], timeout=15)
    return save_state(
        manager_dir,
        {
            "running": False,
            "target_app_pid": None,
            "keeper_pid": None,
            "stopped_at": time.time(),
            "stop_reason": reason,
        },
    )


def _wait_for_port(port: int, timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"WSL SSH port {port} did not open: {last_error}")


def _start_keeper(distro: str, manager_dir: Path) -> int:
    """Keep one Windows-side WSL client handle open for the SSH lifetime."""
    existing = load_state(manager_dir).get("keeper_pid")
    if _pid_alive(existing):
        return int(existing)
    creationflags = 0
    if os.name == "nt":
        creationflags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        ["wsl.exe", "-d", distro, "-u", "root", "--", "/usr/bin/sleep", "infinity"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    save_state(manager_dir, {"keeper_pid": process.pid})
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"WSL keepalive exited with code {process.returncode}")
        if distro_running(distro):
            return process.pid
        time.sleep(0.1)
    raise RuntimeError("WSL keepalive did not start the distribution")


def start_for_account(
    manager_dir: Path,
    *,
    account_name: str,
    account_key: str,
    auth_path: Path,
    app_home: Path,
    native_home: Path | None = None,
    native_codex_exe: Path | None = None,
    app_pid: int | None = None,
    force_restart: bool = False,
) -> dict:
    config = load_config(manager_dir)
    if not config.get("enabled"):
        raise RuntimeError("WSL SSH is not enabled; run cm ssh setup first")
    distro = str(config.get("distro") or DEFAULT_DISTRO)
    user = _linux_user(config)
    port = int(config.get("port") or DEFAULT_PORT)
    execution_mode = str(config.get("execution_mode") or "windows-native")
    if execution_mode != "windows-native":
        raise RuntimeError(f"Unsupported SSH execution mode: {execution_mode}")
    if native_home is None or native_codex_exe is None:
        raise RuntimeError("native Windows account home and codex.exe are required")
    native_home = Path(native_home).resolve()
    native_codex_exe = Path(native_codex_exe).resolve()
    bridge_source = _bridge_source_path()
    dispatch_source = _dispatch_source_path()
    windows_python = Path(sys.executable).resolve()
    for required in (native_home, native_codex_exe, bridge_source, dispatch_source, windows_python):
        if not required.exists():
            raise RuntimeError(f"Native SSH bridge prerequisite is missing: {required}")

    current = status(manager_dir)
    if not current.get("keeper_running"):
        _start_keeper(distro, manager_dir)
        current = status(manager_dir)
    state = load_state(manager_dir)
    native_target_ready = bool(
        state.get("bridge_mode") == "windows-native"
        and os.path.normcase(str(state.get("native_home") or ""))
        == os.path.normcase(str(native_home))
        and os.path.normcase(str(state.get("native_codex_exe") or ""))
        == os.path.normcase(str(native_codex_exe))
    )
    if (
        not force_restart
        and current.get("ssh_active")
        and current.get("target_account") == account_name
        and native_target_ready
    ):
        return save_state(
            manager_dir,
            {
                "running": True,
                "target_app_pid": app_pid,
                "last_used_at": time.time(),
            },
        )

    _stop_native_bridge(manager_dir)
    if current.get("wsl_running"):
        _stop_daemon_if_running(config)

    auth_wsl = windows_to_wsl_path(distro, auth_path)
    app_home_wsl = windows_to_wsl_path(distro, app_home)
    python_wsl = windows_to_wsl_path(distro, windows_python)
    dispatch_wsl = windows_to_wsl_path(distro, dispatch_source)
    real_codex_result = _wsl(
        distro,
        [
            "readlink",
            "-f",
            f"/home/{user}/.codex-ssh-shared/packages/standalone/current/bin/codex",
        ],
        user=user,
        timeout=8,
    )
    real_codex = _clean_wsl_output(real_codex_result.stdout)
    if real_codex_result.returncode != 0 or not real_codex:
        raise RuntimeError("WSL fallback Codex runtime is unavailable")

    save_state(
        manager_dir,
        {
            "running": True,
            "bridge_mode": "windows-native",
            "target_account": account_name,
            "target_key": account_key,
            "target_app_pid": app_pid,
            "native_home": str(native_home),
            "native_codex_exe": str(native_codex_exe),
            "bridge_script": str(bridge_source),
            "windows_python": str(windows_python),
        },
    )

    env_payload = "\n".join(
        [
            f"WINDOWS_PYTHON={shlex.quote(python_wsl)}",
            f"BRIDGE_SCRIPT={shlex.quote(str(bridge_source))}",
            f"MANAGER_DIR={shlex.quote(str(Path(manager_dir).resolve()))}",
            f"REAL_CODEX={shlex.quote(real_codex)}",
            "",
        ]
    )
    env_payload_b64 = base64.b64encode(env_payload.encode("utf-8")).decode("ascii")
    safe_user = shlex.quote(user)
    safe_key = shlex.quote(account_key)
    safe_auth = shlex.quote(auth_wsl)
    safe_app_home = shlex.quote(app_home_wsl)
    script = "; ".join(
        [
            f"install -d -o {safe_user} -g {safe_user} -m 0700 /home/{safe_user}/.codex-ssh/{safe_key}",
            f"install -d -o {safe_user} -g {safe_user} -m 0700 /home/{safe_user}/.codex-ssh-shared",
            f"install -d -o {safe_user} -g {safe_user} -m 0700 /home/{safe_user}/.config/codex-native-ssh",
            f"install -d -o {safe_user} -g {safe_user} -m 0755 /home/{safe_user}/.local/bin",
            f"ln -sfn {safe_auth} /home/{safe_user}/.codex-ssh/{safe_key}/auth.json",
            f"ln -sfn /home/{safe_user}/.codex-ssh-shared/packages /home/{safe_user}/.codex-ssh/{safe_key}/packages",
            f"test ! -e {safe_app_home}/AGENTS.md || ln -sfn {safe_app_home}/AGENTS.md /home/{safe_user}/.codex-ssh/{safe_key}/AGENTS.md",
            f"test ! -e {safe_app_home}/skills || ln -sfn {safe_app_home}/skills /home/{safe_user}/.codex-ssh/{safe_key}/skills",
            f"ln -sfn /home/{safe_user}/.codex-ssh/{safe_key} /home/{safe_user}/.codex-ssh-current",
            f"chown {safe_user}:{safe_user} /home/{safe_user}/.codex-ssh/{safe_key}",
            f"chown -h {safe_user}:{safe_user} /home/{safe_user}/.codex-ssh-current /home/{safe_user}/.codex-ssh/{safe_key}/auth.json /home/{safe_user}/.codex-ssh/{safe_key}/packages",
            f"printf %s {shlex.quote(env_payload_b64)} | base64 -d > /home/{safe_user}/.config/codex-native-ssh/bridge.env",
            f"chown {safe_user}:{safe_user} /home/{safe_user}/.config/codex-native-ssh/bridge.env",
            f"chmod 0600 /home/{safe_user}/.config/codex-native-ssh/bridge.env",
            f"rm -f /home/{safe_user}/.local/bin/codex",
            f"install -o {safe_user} -g {safe_user} -m 0755 {shlex.quote(dispatch_wsl)} /home/{safe_user}/.local/bin/codex",
            f"ln -sfn /home/{safe_user}/.local/bin/codex /usr/local/bin/codex",
            "systemctl start ssh.service",
        ]
    )
    result = _wsl_shell(distro, script, user="root", timeout=25)
    if result.returncode != 0:
        detail = _clean_wsl_output(result.stderr or result.stdout)
        raise RuntimeError(f"WSL SSH start failed: {detail[-300:]}")
    _wait_for_port(port)
    return save_state(
        manager_dir,
        {
            "running": True,
            "target_account": account_name,
            "target_key": account_key,
            "target_app_pid": app_pid,
            "bridge_mode": "windows-native",
            "native_home": str(native_home),
            "native_codex_exe": str(native_codex_exe),
            "started_at": time.time(),
            "last_used_at": time.time(),
            "stop_reason": None,
        },
    )


def stop_if_idle(manager_dir: Path) -> bool:
    config = load_config(manager_dir)
    if not config.get("enabled") or not config.get("auto_stop_idle_on_cm_start"):
        return False
    current = status(manager_dir)
    if not current.get("idle"):
        return False
    stop(manager_dir, reason="idle-on-cm-start")
    return True


def format_bytes(value: object) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        size = 0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return "0B"
