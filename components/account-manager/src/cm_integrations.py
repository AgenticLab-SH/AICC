"""Optional, host-independent integration points for Codex Account Manager.

The core account manager works with nothing configured. Everything here is an
opt-in extra that must resolve from the user's own environment, so a clone on a
different Mac, Windows box or WSL distro never inherits another machine's
layout.

Resolution order for every setting:

1. an explicit environment variable, then
2. ``$CM_CONFIG_DIR/config.toml`` (default ``~/.codex-multi/config.toml``).

No path, repository, account or hostname is baked into this file.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
import tomllib
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("CM_CONFIG_DIR", str(Path.home() / ".codex-multi"))
).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"

_CACHE: dict | None = None


def config() -> dict:
    """User config, or an empty mapping when absent/unreadable.

    A malformed file must not break account switching, so parse errors degrade
    to "no integrations configured" instead of raising.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with CONFIG_FILE.open("rb") as handle:
            loaded = tomllib.load(handle)
        _CACHE = loaded if isinstance(loaded, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):
        _CACHE = {}
    return _CACHE


def _section(name: str) -> dict:
    value = config().get(name)
    return value if isinstance(value, dict) else {}


def _resolved_path(env_var: str, section: str, key: str) -> Path | None:
    raw = os.environ.get(env_var, "").strip() or str(_section(section).get(key, "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _split_command(raw: str) -> list[str] | None:
    # Windows paths carry backslashes that POSIX splitting would eat.
    parts = shlex.split(raw, posix=os.name != "nt")
    return parts or None


def stack_update_command() -> list[str] | None:
    """Command ``cm stack apply`` delegates to, when the user configured one.

    Deliberately opt-in: a safe update path (backup, rollback, validation) is
    environment-specific, so this tool reports versions but never invents an
    upgrade procedure for someone else's machine.
    """
    raw = os.environ.get("CM_STACK_UPDATE_COMMAND", "").strip()
    if raw:
        return _split_command(raw)
    configured = _section("stack").get("update_command")
    if isinstance(configured, list):
        parts = [str(item) for item in configured if str(item).strip()]
        return parts or None
    if isinstance(configured, str) and configured.strip():
        return _split_command(configured.strip())
    return None


def gateway_repo() -> Path | None:
    """Optional local git checkout whose freshness ``cm stack`` reports."""
    return _resolved_path("CM_GATEWAY_REPO", "stack", "gateway_repo")


def gateway_port() -> int:
    value = os.environ.get("CM_GATEWAY_PORT", "").strip() or _section("stack").get("gateway_port")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def gateway_label() -> str:
    label = str(_section("stack").get("gateway_label", "")).strip()
    return label or "gateway"


def proxy_base_url() -> str:
    """Base URL of the local opencodex proxy (``ocx``)."""
    raw = os.environ.get("CM_PROXY_BASE_URL", "").strip() or str(
        _section("proxy").get("base_url", "")
    ).strip()
    return (raw or "http://127.0.0.1:10100").rstrip("/")


def real_codex_command() -> str | None:
    """Underlying ``codex`` executable the shell wrappers should call.

    An explicit setting wins; PATH lookup is the fallback and skips anything
    living next to this file so a wrapper can never recurse into itself.
    """
    raw = os.environ.get("CM_REAL_CODEX", "").strip() or str(
        _section("codex").get("executable", "")
    ).strip()
    if raw:
        expanded = Path(raw).expanduser()
        return str(expanded) if expanded.exists() else raw
    wrapper_dir = Path(__file__).resolve().parent
    names = ("codex.cmd", "codex.exe", "codex") if os.name == "nt" else ("codex",)
    for name in names:
        found = shutil.which(name)
        if not found:
            continue
        try:
            if Path(found).resolve().parent == wrapper_dir:
                continue
        except OSError:
            pass
        return found
    return None


def main() -> int:
    """Print resolved integration settings. Never prints secrets or tokens."""
    stack_cmd = stack_update_command()
    repo = gateway_repo()
    codex_exe = real_codex_command()
    rows = [
        ("config file", str(CONFIG_FILE), CONFIG_FILE.is_file()),
        ("proxy base url", proxy_base_url(), True),
        ("gateway repo", str(repo or "-"), bool(repo)),
        ("stack update command", " ".join(stack_cmd) if stack_cmd else "-", bool(stack_cmd)),
        ("real codex", codex_exe or "-", bool(codex_exe)),
    ]
    for label, value, present in rows:
        print(f"{'ok' if present else '--':<3} {label:<24} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
