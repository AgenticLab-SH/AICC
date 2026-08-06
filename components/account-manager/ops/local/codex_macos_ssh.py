"""On-demand user-mode SSH transport for ChatGPT Desktop Codex remotes on macOS.

The SSH server listens only on loopback and runs without administrator rights.
Its forced command preserves the POSIX shell handshake expected by the desktop
app while a small ``codex`` dispatcher selects the requested account's native
CODEX_HOME.  The SSH process is started only for an active remote target.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


SCHEMA_VERSION = 1
CONFIG_NAME = "local-ssh.json"
STATE_NAME = "local-ssh-runtime.json"
DEFAULT_PORT = 2222
SSH_DIR_NAME = "ssh"
SSHD = Path("/usr/sbin/sshd")
SSH_KEYGEN = Path("/usr/bin/ssh-keygen")


def _json_path(manager_dir: Path, name: str) -> Path:
    return Path(manager_dir) / name


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _default_config() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": True,
        "port": DEFAULT_PORT,
        "auto_start_secondary_app": True,
        "auto_stop_idle_on_cm_start": True,
    }


def load_config(manager_dir: Path) -> dict:
    result = _default_config()
    result.update(_read_json(_json_path(manager_dir, CONFIG_NAME)))
    return result


def save_config(manager_dir: Path, updates: dict) -> dict:
    result = load_config(manager_dir)
    result.update(updates)
    result["schema_version"] = SCHEMA_VERSION
    _write_json(_json_path(manager_dir, CONFIG_NAME), result)
    return result


def load_state(manager_dir: Path) -> dict:
    return _read_json(_json_path(manager_dir, STATE_NAME))


def save_state(manager_dir: Path, updates: dict) -> dict:
    result = load_state(manager_dir)
    result.update(updates)
    result["schema_version"] = SCHEMA_VERSION
    _write_json(_json_path(manager_dir, STATE_NAME), result)
    return result


def _pid_command(pid: object) -> str | None:
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return None
    if pid_value <= 0:
        return None
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid_value), "-o", "command="],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    command = result.stdout.strip()
    return command or None


def _owned_sshd_alive(manager_dir: Path, pid: object) -> bool:
    command = _pid_command(pid)
    if not command:
        return False
    config_path = _ssh_dir(manager_dir) / "sshd_config"
    return str(SSHD) in command and str(config_path) in command


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.4):
            return True
    except OSError:
        return False


def _connection_count(port: int) -> int:
    lsof = Path("/usr/sbin/lsof")
    if not lsof.is_file():
        return 0
    result = subprocess.run(
        [str(lsof), "-nP", "-a", f"-iTCP:{int(port)}", "-sTCP:ESTABLISHED", "-t"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return len({line.strip() for line in result.stdout.splitlines() if line.strip()})


def _ssh_dir(manager_dir: Path) -> Path:
    return Path(manager_dir) / SSH_DIR_NAME


def connection_details(manager_dir: Path) -> dict:
    config = load_config(manager_dir)
    ssh_dir = _ssh_dir(manager_dir)
    return {
        "display_name": "내 노트북 공통",
        "host": f"{os.environ.get('USER') or Path.home().name}@127.0.0.1",
        "port": int(config.get("port") or DEFAULT_PORT),
        "identity_file": str(ssh_dir / "client_ed25519"),
    }


def status(manager_dir: Path) -> dict:
    config = load_config(manager_dir)
    state = load_state(manager_dir)
    port = int(config.get("port") or DEFAULT_PORT)
    pid = state.get("sshd_pid")
    alive = _owned_sshd_alive(manager_dir, pid)
    listening = alive and _port_open(port)
    connections = _connection_count(port) if listening else 0
    target_pid = state.get("target_app_pid")
    target_app_running = _pid_command(target_pid) is not None if target_pid else False
    return {
        "configured": bool(config.get("enabled")),
        "enabled": bool(config.get("enabled")),
        "port": port,
        "target_account": state.get("target_account"),
        "target_app_pid": target_pid,
        "target_app_running": target_app_running,
        "ssh_active": listening,
        "connections": connections,
        "sshd_pid": int(pid) if alive else None,
        "client_key": str(_ssh_dir(manager_dir) / "client_ed25519"),
        "idle": bool(listening and connections == 0 and not target_app_running),
        "error": None,
    }


def _run(args: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _generate_key(path: Path, comment: str) -> None:
    if path.is_file() and path.with_suffix(path.suffix + ".pub").is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [str(SSH_KEYGEN), "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path)]
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {(result.stderr or result.stdout).strip()}")
    os.chmod(path, 0o600)
    os.chmod(path.with_suffix(path.suffix + ".pub"), 0o644)


def _sync_known_host(manager_dir: Path, port: int) -> None:
    """Trust only this manager's loopback host key for the selected port.

    A Windows-to-macOS move commonly leaves the old machine's loopback key in
    ``known_hosts``.  Preserve the complete file once, remove only the two
    loopback aliases for this high port (including hashed forms via
    ``ssh-keygen -R``), then append the current public host key.
    """
    ssh_dir = _ssh_dir(manager_dir)
    public_key = ssh_dir / "host_ed25519.pub"
    fields = public_key.read_text(encoding="utf-8").strip().split()
    if len(fields) < 2:
        raise RuntimeError("generated local SSH host public key is invalid")

    user_ssh_dir = Path.home() / ".ssh"
    user_ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    known_hosts = user_ssh_dir / "known_hosts"
    backup = ssh_dir / "known_hosts.before-local-ssh"
    if known_hosts.is_file() and not backup.exists():
        shutil.copy2(known_hosts, backup)
        os.chmod(backup, 0o600)

    if known_hosts.is_file():
        for host in (f"[127.0.0.1]:{port}", f"[localhost]:{port}"):
            _run([str(SSH_KEYGEN), "-q", "-R", host, "-f", str(known_hosts)])

    existing = known_hosts.read_text(encoding="utf-8") if known_hosts.exists() else ""
    canonical = f"[127.0.0.1]:{port} {fields[0]} {fields[1]}"
    lines = [line.rstrip() for line in existing.splitlines() if line.strip()]
    if canonical not in lines:
        lines.append(canonical)
    known_hosts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(known_hosts, 0o600)


def _write_runtime_files(manager_dir: Path) -> None:
    ssh_dir = _ssh_dir(manager_dir)
    bin_dir = ssh_dir / "bin"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)
    os.chmod(bin_dir, 0o700)

    host_key = ssh_dir / "host_ed25519"
    client_key = ssh_dir / "client_ed25519"
    _generate_key(host_key, "codex-local-ssh-host")
    _generate_key(client_key, "codex-local-ssh-client")
    authorized = ssh_dir / "authorized_keys"
    authorized.write_text(client_key.with_suffix(".pub").read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(authorized, 0o600)

    module_path = Path(__file__).resolve()
    dispatcher = bin_dir / "codex"
    dispatcher.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(module_path))} "
        f"dispatch --manager-dir {shlex.quote(str(Path(manager_dir).resolve()))} -- \"$@\"\n",
        encoding="utf-8",
    )
    os.chmod(dispatcher, 0o700)

    entry = ssh_dir / "ssh-entry.zsh"
    entry.write_text(
        "#!/bin/zsh\n"
        f"export CODEX_HOME=\"$(/bin/cat {shlex.quote(str(ssh_dir / 'target_home'))})\"\n"
        f"export CODEX_MULTI_REMOTE_TARGET=\"$(/bin/cat {shlex.quote(str(ssh_dir / 'target_account'))})\"\n"
        f"export PATH={shlex.quote(str(bin_dir))}:$PATH\n"
        'exec /bin/zsh -l -c "$SSH_ORIGINAL_COMMAND"\n',
        encoding="utf-8",
    )
    os.chmod(entry, 0o700)

    config = load_config(manager_dir)
    port = int(config.get("port") or DEFAULT_PORT)
    _sync_known_host(manager_dir, port)
    user = os.environ.get("USER") or Path.home().name
    server_config = ssh_dir / "sshd_config"
    lines = [
        f"Port {port}",
        "ListenAddress 127.0.0.1",
        f"HostKey {host_key}",
        f"PidFile {ssh_dir / 'sshd.pid'}",
        f"AuthorizedKeysFile {authorized}",
        "PubkeyAuthentication yes",
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "ChallengeResponseAuthentication no",
        "UsePAM no",
        "PermitRootLogin no",
        f"AllowUsers {user}",
        "AllowAgentForwarding no",
        "AllowTcpForwarding no",
        "X11Forwarding no",
        "PermitTunnel no",
        "GatewayPorts no",
        "PermitUserEnvironment no",
        "StrictModes no",
        "LogLevel ERROR",
        f"ForceCommand {entry}",
        "",
    ]
    server_config.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(server_config, 0o600)


def setup(manager_dir: Path, *, port: int | None = None) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("macOS local SSH setup was requested on another platform")
    if not SSHD.is_file() or not SSH_KEYGEN.is_file():
        raise RuntimeError("macOS OpenSSH server tools are unavailable")
    if port is not None:
        if not 1024 <= int(port) <= 65535:
            raise RuntimeError("user-mode SSH port must be between 1024 and 65535")
        save_config(manager_dir, {"port": int(port), "enabled": True})
    else:
        save_config(manager_dir, {"enabled": True})
    _write_runtime_files(manager_dir)
    return connection_details(manager_dir)


def stop(manager_dir: Path, *, reason: str = "manual") -> dict:
    state = load_state(manager_dir)
    pid = state.get("sshd_pid")
    if _owned_sshd_alive(manager_dir, pid):
        os.kill(int(pid), signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _owned_sshd_alive(manager_dir, pid):
            time.sleep(0.05)
    return save_state(
        manager_dir,
        {
            "running": False,
            "sshd_pid": None,
            "stopped_at": time.time(),
            "stop_reason": reason,
        },
    )


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"user-mode sshd exited with code {process.returncode}")
        if _port_open(port):
            return
        time.sleep(0.1)
    raise RuntimeError(f"user-mode SSH port {port} did not open")


def start_for_account(
    manager_dir: Path,
    *,
    account_name: str,
    account_key: str,
    native_home: Path,
    native_codex_exe: Path,
    app_pid: int | None = None,
    force_restart: bool = False,
) -> dict:
    setup(manager_dir)
    home = Path(native_home).resolve()
    codex = Path(native_codex_exe).resolve()
    if not home.is_dir() or not (home / "auth.json").is_file():
        raise RuntimeError("selected account's native CODEX_HOME is not ready")
    if not codex.is_file():
        raise RuntimeError(f"embedded Codex runtime is unavailable: {codex}")

    current = status(manager_dir)
    same_target = (
        current.get("target_account") == account_name
        and str(load_state(manager_dir).get("native_home") or "") == str(home)
    )
    if current.get("ssh_active") and same_target and not force_restart:
        return save_state(
            manager_dir,
            {"running": True, "target_app_pid": app_pid, "last_used_at": time.time()},
        )
    if current.get("ssh_active"):
        stop(manager_dir, reason="target-change")

    save_state(
        manager_dir,
        {
            "running": True,
            "target_account": account_name,
            "target_key": account_key,
            "target_app_pid": app_pid,
            "native_home": str(home),
            "native_codex_exe": str(codex),
            "started_at": time.time(),
            "last_used_at": time.time(),
            "stop_reason": None,
        },
    )

    ssh_dir = _ssh_dir(manager_dir)
    (ssh_dir / "target_home").write_text(str(home) + "\n", encoding="utf-8")
    (ssh_dir / "target_account").write_text(account_name + "\n", encoding="utf-8")
    os.chmod(ssh_dir / "target_home", 0o600)
    os.chmod(ssh_dir / "target_account", 0o600)
    log_path = ssh_dir / "sshd.log"
    log_handle = log_path.open("ab", buffering=0)
    process = subprocess.Popen(
        [str(SSHD), "-D", "-e", "-f", str(ssh_dir / "sshd_config")],
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
    )
    try:
        _wait_for_port(int(load_config(manager_dir)["port"]), process)
    except Exception:
        log_handle.close()
        if process.poll() is None:
            process.terminate()
        raise
    log_handle.close()
    return save_state(
        manager_dir,
        {"running": True, "sshd_pid": process.pid, "last_used_at": time.time()},
    )


def stop_if_idle(manager_dir: Path) -> bool:
    config = load_config(manager_dir)
    if not config.get("auto_stop_idle_on_cm_start"):
        return False
    current = status(manager_dir)
    if not current.get("idle"):
        return False
    stop(manager_dir, reason="idle-on-cm-start")
    return True


def _dispatch_target(manager_dir: Path) -> tuple[Path, Path]:
    state = load_state(manager_dir)
    if not state.get("running"):
        raise RuntimeError("cm remote target is not active")
    home = Path(str(state.get("native_home") or "")).resolve()
    codex = Path(str(state.get("native_codex_exe") or "")).resolve()
    if not home.is_dir() or not (home / "auth.json").is_file():
        raise RuntimeError("remote target CODEX_HOME is unavailable")
    if not codex.is_file():
        raise RuntimeError("remote target Codex runtime is unavailable")
    return home, codex


def dispatch(manager_dir: Path, argv: list[str]) -> int:
    home, codex = _dispatch_target(manager_dir)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    env["CODEX_MULTI_REMOTE_TARGET"] = str(load_state(manager_dir).get("target_account") or "")
    os.execve(str(codex), [str(codex), *argv], env)
    return 127


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dispatch", "status"))
    parser.add_argument("--manager-dir", required=True, type=Path)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manager_dir = args.manager_dir.resolve()
    if args.command == "status":
        print(json.dumps(status(manager_dir), ensure_ascii=False))
        return 0
    forwarded = list(args.args)
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    try:
        return dispatch(manager_dir, forwarded)
    except Exception as exc:
        print(f"Codex macOS SSH dispatch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
