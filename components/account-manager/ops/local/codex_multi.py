"""Codex Multi-Account Manager.

Features:
  - switch: replaces ~/.codex/auth.json (App + CLI)
  - launch: isolated CODEX_HOME (concurrent CLI sessions)
  - Color-coded priority display
  - 5h/week reset times shown separately
  - User-defined account order
  - Subscription expiry tracking
  - Token expiry detection
"""

import json
import hashlib
import os
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only app support
    winreg = None

from codex_notify import notify_account_change
import codex_thread_index

# === Paths ===
# cm manages the real Codex App home. It must not inherit an isolated
# CODEX_HOME from a parent CLI session, otherwise auth import and shared links
# can point back into ~/.codex-multi/homes and form a self-referential layout.
APP_CODEX_HOME = Path(
    os.environ.get("CM_APP_CODEX_HOME", str(Path.home() / ".codex"))
).expanduser()
INHERITED_CODEX_HOME = os.environ.get("CODEX_HOME")
CODEX_HOME = APP_CODEX_HOME
MANAGER_DIR = Path(
    os.environ.get("CM_MANAGER_DIR", str(Path.home() / ".codex-multi"))
).expanduser()
ACCOUNTS_DIR = MANAGER_DIR / "accounts"
HOMES_DIR = MANAGER_DIR / "homes"
APP_PROFILES_DIR = MANAGER_DIR / "app-profiles"
DEFAULT_MACOS_APP_PROFILE = Path(
    os.environ.get(
        "CM_APP_ELECTRON_USER_DATA_PATH",
        str(Path.home() / "Library" / "Application Support" / "Codex"),
    )
).expanduser()
TRASH_DIR = MANAGER_DIR / "_trash"
ORDER_FILE = MANAGER_DIR / "order.json"
META_FILE = MANAGER_DIR / "meta.json"
USAGE_API = "https://chatgpt.com/backend-api/wham/usage"
RESET_CREDITS_API = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
USAGE_USER_AGENT = "Codex Multi-Account Manager/1.0"
USAGE_ATTEMPTS = 1
USAGE_TIMEOUT = 8
RESET_CREDITS_TIMEOUT = 12
RESET_CREDITS_ATTEMPTS = 2
RESET_CREDITS_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
CODEX_NPM_PACKAGE = "@openai/codex"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 600
DEFAULT_LOGIN_RETRY_DELAY_SECONDS = 5
SOURCE_DIR = Path(__file__).resolve().parent
OPS_DIR = SOURCE_DIR.parent

ACTIVE_CLI_FILE = MANAGER_DIR / "active_cli.json"
CLI_UPDATE_STATE_FILE = MANAGER_DIR / "cli-update.json"
CLI_UPDATE_CHECK_INTERVAL_SECONDS = 6 * 60 * 60
def record_cli_session(name: str, pid: int):
    """Record an active CLI session."""
    sessions = load_cli_sessions()
    sessions[str(pid)] = name
    ACTIVE_CLI_FILE.write_text(json.dumps(sessions), encoding="utf-8")


def remove_cli_session(pid: int):
    sessions = load_cli_sessions()
    sessions.pop(str(pid), None)
    ACTIVE_CLI_FILE.write_text(json.dumps(sessions), encoding="utf-8")


def load_cli_sessions() -> dict:
    """Load active CLI sessions, pruning dead PIDs."""
    if not ACTIVE_CLI_FILE.exists():
        return {}
    try:
        content = ACTIVE_CLI_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        sessions = json.loads(content)
    except (json.JSONDecodeError, OSError):
        return {}
    # Prune dead processes
    alive = {}
    for pid_str, name in sessions.items():
        try:
            os.kill(int(pid_str), 0)
            alive[pid_str] = name
        except (OSError, ValueError):
            pass
    if alive != sessions:
        ACTIVE_CLI_FILE.write_text(json.dumps(alive), encoding="utf-8")
    return alive


def get_cli_accounts() -> set[str]:
    """Return set of account names with active CLI sessions."""
    sessions = load_cli_sessions()
    return set(sessions.values())


# config.toml is deliberately NOT shared by symlink. The App and third-party
# tools write per-account absolute paths into it, so a shared link let whichever
# account ran last pin the settings of every other account. Each isolated home
# gets a rendered copy instead (see _sync_account_config).
SHARED_ITEMS = [
    "AGENTS.md", "rules",
    "hooks.json", "skills", "custom_skills",
    "plugins", "memories", "history.jsonl",
    "installation_id", "models_cache.json",
    "version.json", "sessions", "archived_sessions", "logs", "log", ".sandbox", ".sandbox-bin",
    ".sandbox-secrets", "browser", "agents", "prompts", "vendor_imports",
]


# === ANSI Colors (dark background optimized) ===
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    # Foreground
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    # Background
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"


_COLOR_ENABLED = True


def set_color_enabled(enabled: bool) -> None:
    """Toggle ANSI coloring. Disabled for headless/Telegram rendering."""
    global _COLOR_ENABLED
    _COLOR_ENABLED = bool(enabled)


def colored(text, *codes):
    if not _COLOR_ENABLED:
        return str(text)
    return "".join(codes) + str(text) + C.RESET


# === Account Storage ===

def ensure_dirs():
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    HOMES_DIR.mkdir(parents=True, exist_ok=True)
    APP_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)


def all_account_files() -> list[str]:
    ensure_dirs()
    return [p.name.removesuffix(".json") for p in ACCOUNTS_DIR.glob("*.json")]


def load_order() -> list[str]:
    if ORDER_FILE.exists():
        return json.loads(ORDER_FILE.read_text(encoding="utf-8"))
    return []


def save_order(order: list[str]):
    ORDER_FILE.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")


def list_accounts() -> list[str]:
    """Return accounts in user-defined order."""
    order = load_order()
    all_names = set(all_account_files())
    # Ordered accounts first, then any new ones appended
    result = [n for n in order if n in all_names]
    for n in sorted(all_names - set(result)):
        result.append(n)
    # Persist updated order
    if result != order:
        save_order(result)
    return result


def get_auth_path(name: str) -> Path:
    return ACCOUNTS_DIR / f"{name}.json"


def read_auth(name: str) -> dict | None:
    path = get_auth_path(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: dict, *, ensure_ascii: bool = True):
    """Write JSON without leaving a partially-written credential file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=ensure_ascii),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def save_auth(name: str, data: dict):
    ensure_dirs()
    _atomic_write_json(get_auth_path(name), data)


def move_to_trash(path: Path):
    if not path.exists() and not path.is_symlink():
        return
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    target = TRASH_DIR / f"{path.name}.{stamp}"
    suffix = 1
    while target.exists():
        target = TRASH_DIR / f"{path.name}.{stamp}.{suffix}"
        suffix += 1
    shutil.move(str(path), str(target))


def delete_account(name: str):
    key = stable_account_key(name)
    for path in (
        get_auth_path(name),
        HOMES_DIR / key,
        HOMES_DIR / name,
        APP_PROFILES_DIR / key,
        APP_PROFILES_DIR / name,
    ):
        move_to_trash(path)
    order = load_order()
    if name in order:
        order.remove(name)
        save_order(order)
    meta = load_meta()
    meta.pop(name, None)
    save_meta(meta)


def _matching_auth_token_fields(first: dict | None, second: dict | None) -> list[str]:
    """Return matching secret-token fields without exposing their values."""
    first_tokens = first.get("tokens", {}) if isinstance(first, dict) else {}
    second_tokens = second.get("tokens", {}) if isinstance(second, dict) else {}
    return [
        field
        for field in ("access_token", "refresh_token", "id_token")
        if first_tokens.get(field) and first_tokens.get(field) == second_tokens.get(field)
    ]


def match_app_auth_account(
    live_auth: dict | None,
    accounts: list[str] | None = None,
    *,
    resolved_email: str | None = None,
) -> str | None:
    """Match App auth by token first, API identity second, account ID last.

    A shared account_id is not a sufficient identity boundary. Some ChatGPT
    accounts can expose the same account_id while using different OAuth token
    sets and server-side email identities.
    """
    account_id = _account_id(live_auth)
    if not account_id:
        return None
    names = accounts if accounts is not None else list_accounts()
    candidates = [name for name in names if _account_id(read_auth(name)) == account_id]

    token_matches = [
        name for name in candidates
        if _matching_auth_token_fields(read_auth(name), live_auth)
    ]
    if len(token_matches) == 1:
        return token_matches[0]

    normalized_email = str(resolved_email or "").strip().lower()
    if normalized_email:
        email_matches = [name for name in candidates if name.strip().lower() == normalized_email]
        if len(email_matches) == 1:
            return email_matches[0]

    if len(candidates) == 1:
        return candidates[0]
    return None


def get_active_account(
    *,
    live_auth: dict | None = None,
    accounts: list[str] | None = None,
    resolved_email: str | None = None,
) -> str | None:
    if live_auth is None:
        live = CODEX_HOME / "auth.json"
        if not live.exists():
            return None
        live_auth = _read_auth_file(live)
    return match_app_auth_account(
        live_auth,
        accounts,
        resolved_email=resolved_email,
    )


def get_live_app_context(accounts: list[str] | None = None) -> dict:
    """Read and query the actual App credential, never a stored substitute."""
    names = accounts if accounts is not None else list_accounts()
    live_path = APP_CODEX_HOME / "auth.json"
    live_auth = _read_auth_file(live_path) if live_path.exists() else None
    active = get_active_account(live_auth=live_auth, accounts=names)
    quota = fetch_quota(live_auth) if _has_usable_chatgpt_auth(live_auth) else {
        "ok": False,
        "error": "no_auth",
    }
    resolved_email = quota.get("email") if quota.get("ok") else None
    active = get_active_account(
        live_auth=live_auth,
        accounts=names,
        resolved_email=resolved_email,
    ) or active
    return {
        "auth": live_auth,
        "quota": quota,
        "active": active,
        "resolved_email": resolved_email,
    }


# === Meta (subscription expiry etc) ===

def load_meta() -> dict:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    return {}


def save_meta(meta: dict):
    META_FILE.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def get_account_phone(name: str) -> str | None:
    phone = load_meta().get(name, {}).get("phone")
    if isinstance(phone, str) and phone.strip():
        return phone.strip()
    return None


def set_account_phone(name: str, phone: str | None):
    meta = load_meta()
    entry = meta.setdefault(name, {})
    if phone and phone.strip():
        entry["phone"] = phone.strip()
    else:
        entry.pop("phone", None)
    save_meta(meta)


def get_account_usage_proxy(name: str) -> str | None:
    proxy = load_meta().get(name, {}).get("usage_proxy")
    if isinstance(proxy, str) and proxy.strip():
        return proxy.strip()
    return None


def set_account_usage_proxy(name: str, proxy: str | None):
    meta = load_meta()
    entry = meta.setdefault(name, {})
    if proxy and proxy.strip():
        entry["usage_proxy"] = proxy.strip()
    else:
        entry.pop("usage_proxy", None)
    save_meta(meta)


def get_account_usage_last_success(name: str) -> str | None:
    value = load_meta().get(name, {}).get("usage_proxy_last_success")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def set_account_usage_last_success(name: str, value: str | None):
    meta = load_meta()
    entry = meta.setdefault(name, {})
    if value and value.strip():
        entry["usage_proxy_last_success"] = value.strip()
    else:
        entry.pop("usage_proxy_last_success", None)
    save_meta(meta)


def account_id_prefix(name: str, length: int = 8) -> str:
    auth = read_auth(name)
    account_id = auth.get("tokens", {}).get("account_id") if auth else None
    if not account_id:
        return "-"
    return str(account_id)[:length]


def stable_account_key(name: str) -> str:
    auth = read_auth(name)
    account_id = auth.get("tokens", {}).get("account_id") if auth else None
    raw = str(account_id)[:16] if account_id else name
    if account_id:
        duplicate_names = [
            candidate
            for candidate in all_account_files()
            if _account_id(read_auth(candidate)) == str(account_id)
        ]
        if len(duplicate_names) > 1:
            name_digest = hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:8]
            raw = f"{raw}-{name_digest}"
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return key or "account"


def account_selector_tokens(name: str) -> list[str]:
    tokens = [name]
    phone = get_account_phone(name)
    if phone:
        tokens.append(phone)
        tokens.append(re.sub(r"\D+", "", phone))
    auth = read_auth(name)
    account_id = auth.get("tokens", {}).get("account_id") if auth else None
    if account_id:
        tokens.append(str(account_id))
        tokens.append(str(account_id)[:8])
    return tokens


def resolve_account_selector(selector: str | None, accounts: list[str] | None = None, quiet: bool = False) -> str | None:
    """Resolve a user-facing account selector.

    Humans normally use table numbers in the TUI. Agents should prefer a
    user-defined account_id prefix (or recorded phone) because email filenames can change.
    """
    if selector is None:
        return None
    if accounts is None:
        accounts = list_accounts()
    raw = selector.strip()
    if not raw:
        return None

    if raw.isdigit() and not raw.startswith("0"):
        index = int(raw) - 1
        if 0 <= index < len(accounts):
            return accounts[index]

    lowered = raw.lower()
    exact_matches = [
        name
        for name in accounts
        if any(token.lower() == lowered for token in account_selector_tokens(name))
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]

    matches = [
        name
        for name in accounts
        if any(lowered in token.lower() for token in account_selector_tokens(name))
    ]
    if len(matches) == 1:
        return matches[0]
    if not quiet:
        if len(matches) > 1:
            print(f"  {colored('여러 계정이 일치합니다:', C.YELLOW)} {', '.join(matches)}")
        else:
            print(f"  {colored('계정을 찾지 못했습니다:', C.RED)} {selector}")
    return None


def get_expiry(name: str) -> str | None:
    return load_meta().get(name, {}).get("expiry")


def set_expiry(name: str, date_str: str):
    meta = load_meta()
    if name not in meta:
        meta[name] = {}
    meta[name]["expiry"] = date_str
    save_meta(meta)


def get_cancel_renew(name: str) -> str:
    return load_meta().get(name, {}).get("cancel_renew", "n")


def set_cancel_renew(name: str, val: str):
    meta = load_meta()
    if name not in meta:
        meta[name] = {}
    meta[name]["cancel_renew"] = "y" if val.lower() == "y" else "n"
    save_meta(meta)


# === Quota ===

def _redact_url(raw: str | None) -> str:
    if not raw:
        return "system"
    if raw.lower() in ("direct", "none", "off", "no"):
        return "direct"
    try:
        parts = urlsplit(raw)
        if "@" not in parts.netloc:
            return raw
        host = parts.netloc.rsplit("@", 1)[1]
        return urlunsplit((parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


def _host_from_url(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw.lower() in ("direct", "none", "off", "no", "system", "default", "auto"):
        return None
    try:
        return urlsplit(raw).hostname
    except Exception:
        return None


def _resolve_host_sample(host: str | None, limit: int = 4) -> list[str]:
    if not host:
        return []
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    addrs: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in addrs:
            addrs.append(addr)
        if len(addrs) >= limit:
            break
    return addrs


def _normalize_proxy_value(value: str | None) -> tuple[str | None, str] | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered in ("system", "default", "auto"):
        return None, "system"
    if lowered in ("direct", "none", "off", "no"):
        return "", "direct"
    return value, "url"


def _append_proxy_candidate(candidates: list[tuple[str | None, str]], seen: set[str], proxy: str | None, source: str):
    key = "system" if proxy is None else ("direct" if proxy == "" else proxy)
    if key in seen:
        return
    seen.add(key)
    candidates.append((proxy, source))


def _usage_proxy(account_name: str | None = None) -> tuple[str | None, str]:
    """Return the first automatic usage proxy candidate for compatibility."""
    candidates = _usage_proxy_candidates(account_name)
    return candidates[0]


def _usage_proxy_candidates(account_name: str | None = None) -> list[tuple[str | None, str]]:
    """Return ordered usage lookup routes. proxy None = system defaults, "" = direct."""
    candidates: list[tuple[str | None, str]] = []
    seen: set[str] = set()

    env_proxy = os.environ.get("CM_USAGE_PROXY")
    if env_proxy is not None and env_proxy.strip():
        normalized = _normalize_proxy_value(env_proxy)
        if normalized:
            proxy, _ = normalized
            _append_proxy_candidate(candidates, seen, proxy, "env")
            return candidates

    if account_name:
        account_proxy = get_account_usage_proxy(account_name)
        if account_proxy:
            normalized = _normalize_proxy_value(account_proxy)
            if normalized:
                proxy, _ = normalized
                _append_proxy_candidate(candidates, seen, proxy, "account")

        last_success = get_account_usage_last_success(account_name)
        if last_success:
            normalized = _normalize_proxy_value(last_success)
            if normalized:
                proxy, _ = normalized
                _append_proxy_candidate(candidates, seen, proxy, "cached")

    _append_proxy_candidate(candidates, seen, None, "system")
    _append_proxy_candidate(candidates, seen, "", "direct")

    pool = os.environ.get("CM_USAGE_PROXY_POOL", "").strip()
    if pool:
        for item in re.split(r"[;\n,]+", pool):
            normalized = _normalize_proxy_value(item)
            if normalized:
                proxy, _ = normalized
                _append_proxy_candidate(candidates, seen, proxy, "pool")

    return candidates


def _proxy_cache_value(proxy: str | None) -> str:
    if proxy is None:
        return "system"
    if proxy == "":
        return "direct"
    return proxy


def _should_cache_usage_proxy(source: str) -> bool:
    return source in ("account", "cached", "system", "direct")


def _open_usage(req: Request, timeout: int, proxy: str | None):
    if proxy is None:
        return urlopen(req, timeout=timeout)
    handler = ProxyHandler({} if proxy == "" else {"http": proxy, "https": proxy})
    return build_opener(handler).open(req, timeout=timeout)


def _usage_error(error: str, debug: dict | None = None) -> dict:
    result = {"ok": False, "error": error}
    if debug is not None:
        result["_debug"] = debug
    return result


def fetch_quota(auth: dict, account_name: str | None = None, *, include_debug: bool = False) -> dict:
    token = auth.get("tokens", {}).get("access_token")
    if not token:
        return _usage_error("no_token", {"attempts": 0} if include_debug else None)

    debug = {
        "api": USAGE_API,
        "attempts": 0,
        "proxy": "system",
        "proxy_source": "system",
        "api_dns": _resolve_host_sample(_host_from_url(USAGE_API)),
        "tried": [],
    } if include_debug else None

    last_error = "unknown"
    total_attempts = 0
    for proxy, proxy_source in _usage_proxy_candidates(account_name):
        for attempt in range(1, USAGE_ATTEMPTS + 1):
            total_attempts += 1
            route_debug = {
                "attempt": attempt,
                "proxy": _redact_url(proxy),
                "proxy_source": proxy_source,
                "proxy_dns": _resolve_host_sample(_host_from_url(proxy)),
            }
            if debug is not None:
                debug["attempts"] = total_attempts
                debug["proxy"] = route_debug["proxy"]
                debug["proxy_source"] = proxy_source
            req = Request(USAGE_API)
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", USAGE_USER_AGENT)

            started = time.monotonic()
            try:
                with _open_usage(req, timeout=USAGE_TIMEOUT, proxy=proxy) as resp:
                    raw = resp.read()
                    route_debug["http_status"] = getattr(resp, "status", 200)
                    route_debug["content_type"] = resp.headers.get("Content-Type", "")
                    route_debug["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                    data = json.loads(raw.decode("utf-8"))
                    if not isinstance(data, dict):
                        last_error = "json_shape"
                        route_debug["error"] = last_error
                        if debug is not None:
                            debug["tried"].append(route_debug)
                        continue
                    data["ok"] = True
                    if account_name and _should_cache_usage_proxy(proxy_source):
                        set_account_usage_last_success(account_name, _proxy_cache_value(proxy))
                    if debug is not None:
                        debug["http_status"] = route_debug["http_status"]
                        debug["content_type"] = route_debug["content_type"]
                        debug["elapsed_ms"] = route_debug["elapsed_ms"]
                        debug.pop("exception", None)
                        debug["tried"].append(route_debug)
                        data["_debug"] = debug
                    return data
            except HTTPError as e:
                last_error = "expired" if e.code == 401 else f"http_{e.code}"
                route_debug["http_status"] = e.code
                route_debug["content_type"] = e.headers.get("Content-Type", "") if e.headers else ""
                route_debug["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                route_debug["error"] = last_error
                if debug is not None:
                    debug["http_status"] = e.code
                    debug["content_type"] = route_debug["content_type"]
                    debug["elapsed_ms"] = route_debug["elapsed_ms"]
                    debug["tried"].append(route_debug)
                if e.code == 401:
                    return _usage_error(last_error, debug)
            except json.JSONDecodeError:
                last_error = "json_error"
                route_debug["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                route_debug["error"] = last_error
                if debug is not None:
                    debug["elapsed_ms"] = route_debug["elapsed_ms"]
                    debug["tried"].append(route_debug)
            except (TimeoutError, URLError, OSError) as e:
                last_error = "network"
                route_debug["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                route_debug["exception"] = type(e).__name__
                route_debug["error"] = last_error
                if debug is not None:
                    debug["elapsed_ms"] = route_debug["elapsed_ms"]
                    debug["exception"] = type(e).__name__
                    debug["tried"].append(route_debug)

            if attempt < USAGE_ATTEMPTS:
                time.sleep(0.4 * attempt)

    return _usage_error(last_error, debug)


def _first_string(data: dict, paths: tuple[tuple[str, ...], ...]) -> str | None:
    for path in paths:
        value = data
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if isinstance(value, str) and value:
            return value
    return None


def _reset_credit_auth(auth: dict) -> tuple[str | None, str | None]:
    token = _first_string(auth, (
        ("tokens", "access_token"),
        ("tokens", "accessToken"),
        ("access_token",),
        ("accessToken",),
    ))
    account_id = _first_string(auth, (
        ("account", "id"),
        ("tokens", "account_id"),
        ("tokens", "accountId"),
        ("account_id",),
        ("accountId",),
        ("profile", "account_id"),
        ("profile", "accountId"),
    ))
    return token, account_id


def fetch_reset_credits(auth: dict, account_name: str | None = None) -> dict:
    token, account_id = _reset_credit_auth(auth)
    if not token:
        return {"ok": False, "error": "no_token"}
    if not account_id:
        return {"ok": False, "error": "no_account_id"}

    req = Request(RESET_CREDITS_API)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("OpenAI-Account", account_id)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USAGE_USER_AGENT)

    last_error = "unknown"
    for proxy, _proxy_source in _usage_proxy_candidates(account_name):
        for attempt in range(1, RESET_CREDITS_ATTEMPTS + 1):
            try:
                with _open_usage(req, timeout=RESET_CREDITS_TIMEOUT, proxy=proxy) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if not isinstance(data, dict):
                        return {"ok": False, "error": "json_shape"}
                    data["ok"] = True
                    return data
            except HTTPError as exc:
                last_error = "expired" if exc.code == 401 else f"http_{exc.code}"
                if exc.code == 401:
                    return {"ok": False, "error": last_error}
                if exc.code not in RESET_CREDITS_RETRYABLE_STATUS:
                    break
            except json.JSONDecodeError:
                last_error = "json_error"
                break
            except (TimeoutError, URLError, OSError):
                last_error = "network"
            if attempt < RESET_CREDITS_ATTEMPTS:
                time.sleep(0.4 * attempt)
    return {"ok": False, "error": last_error}


def _find_first(data: dict, names: tuple[str, ...]):
    for name in names:
        if name in data:
            return data[name]
    return None


def _find_reset_credit_items(data: dict) -> list[dict]:
    for name in ("reset_credits", "resetCredits", "credits", "items"):
        value = data.get(name)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _count_value(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_expiry_value(value) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _local_datetime_text(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    return value.astimezone(local_tz).strftime("%Y-%m-%d %H:%M")


def remaining_duration_text(seconds: int | float | None) -> str:
    """Human-readable time remaining without exposing raw reset-credit data."""
    if seconds is None:
        return "-"
    total_minutes = max(0, int(seconds) // 60)
    if total_minutes <= 0:
        return "만료"
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days}일 {hours:02d}시간 {minutes:02d}분"
    if hours:
        return f"{hours}시간 {minutes:02d}분"
    return f"{minutes}분"


def format_reset_credit_status(data: dict, *, now: datetime | None = None) -> dict:
    """Normalize reset credits to a safe display model.

    Only whitelisted status/time fields are retained. IDs, profile data and the
    raw response never leave this function's input boundary.
    """
    if not data.get("ok"):
        return {
            "available": None,
            "total_earned": None,
            "credits": [],
            "expiries": [],
            "nearest_expiry": None,
            "nearest_expiry_local": None,
            "nearest_remaining_seconds": None,
            "nearest_remaining_text": "-",
            "expired": data.get("error") == "expired",
            "error": data.get("error", "unknown"),
        }

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    normalized = []
    usable = []
    for credit in _find_reset_credit_items(data):
        status = str(_find_first(credit, ("status",)) or "unknown").lower()
        expiry_value = _find_first(
            credit,
            ("expires_at", "expiresAt", "expiration_time", "expirationTime"),
        )
        expiry = _parse_expiry_value(expiry_value)
        remaining_seconds = int((expiry - now_utc).total_seconds()) if expiry else None
        is_available = status == "available" and (expiry is None or remaining_seconds > 0)
        item = {
            "status": status,
            "reset_type": str(_find_first(credit, ("reset_type", "resetType")) or ""),
            "title": str(_find_first(credit, ("title",)) or ""),
            "granted_at": _local_datetime_text(_parse_expiry_value(
                _find_first(credit, ("granted_at", "grantedAt"))
            )),
            "expires_at": _local_datetime_text(expiry),
            "remaining_seconds": remaining_seconds,
            "remaining_text": remaining_duration_text(remaining_seconds),
            "is_available": is_available,
        }
        normalized.append(item)
        if is_available:
            usable.append((expiry or datetime.max.replace(tzinfo=timezone.utc), item))

    usable.sort(key=lambda pair: pair[0])
    usable_items = [item for _expiry, item in usable]
    nearest = usable_items[0] if usable_items else None

    available = _count_value(_find_first(
        data,
        ("available_reset_credits", "availableResetCredits", "available_count", "availableCount", "available"),
    ))
    total_earned = _count_value(_find_first(data, ("total_earned_count", "totalEarnedCount", "total_earned")))
    if available is None:
        available = len(usable_items)

    return {
        "available": available,
        "total_earned": total_earned,
        "credits": normalized,
        "expiries": [item["expires_at"] for item in usable_items if item["expires_at"] != "unknown"],
        "nearest_expiry": nearest["expires_at"] if nearest else None,
        "nearest_expiry_local": nearest["expires_at"] if nearest else None,
        "nearest_remaining_seconds": nearest["remaining_seconds"] if nearest else None,
        "nearest_remaining_text": nearest["remaining_text"] if nearest else "-",
        "expired": False,
        "error": None,
    }


def format_reset(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    total_min = int(seconds) // 60
    d, rem = divmod(total_min, 1440)
    h, m = divmod(rem, 60)
    if d > 0:
        return f"{d}d{h:02d}h{m:02d}m"
    return f"{h}h{m:02d}m"


def _reset_seconds(window: dict | None) -> int | None:
    if not isinstance(window, dict):
        return None
    reset_after = window.get("reset_after_seconds")
    if reset_after is not None:
        try:
            return max(0, int(reset_after))
        except (TypeError, ValueError):
            return None
    reset_at = window.get("reset_at")
    if reset_at is not None:
        try:
            return max(0, int(float(reset_at) - time.time()))
        except (TypeError, ValueError):
            return None
    return None


def _window_seconds(window: dict | None) -> int | None:
    if not isinstance(window, dict):
        return None
    value = window.get("limit_window_seconds")
    if value is None:
        value = window.get("window_seconds")
    if value is None:
        minutes = window.get("window_duration_mins")
        if minutes is not None:
            try:
                return int(float(minutes) * 60)
            except (TypeError, ValueError):
                return None
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _usage_windows(data: dict) -> list[dict]:
    windows = []
    rl = data.get("rate_limit", {})
    if isinstance(rl, dict):
        for key in ("primary_window", "secondary_window"):
            window = rl.get(key)
            if isinstance(window, dict):
                windows.append(window)
    for extra in data.get("additional_rate_limits") or []:
        if not isinstance(extra, dict):
            continue
        extra_rl = extra.get("rate_limit", {})
        if not isinstance(extra_rl, dict):
            continue
        for key in ("primary_window", "secondary_window"):
            window = extra_rl.get(key)
            if isinstance(window, dict):
                windows.append(window)
    return windows


SHORT_WINDOW_LIMIT_SECONDS = 24 * 60 * 60
SHORT_WINDOW_TARGET_SECONDS = 5 * 60 * 60


def _classify_usage_windows(data: dict) -> tuple[dict | None, dict | None]:
    """Split the reported windows into a short burst window and a long window.

    Plus/Pro accounts report a 5h window plus a weekly one. Team/Business
    accounts report a single ~30d window and no secondary window, so slot
    assignment must follow each window's declared duration instead of assuming
    the API's primary window is always the 5h one.
    """
    rl = data.get("rate_limit", {})
    primary = rl.get("primary_window") if isinstance(rl, dict) else None
    secondary = rl.get("secondary_window") if isinstance(rl, dict) else None

    short_candidates: list[tuple[int, dict]] = []
    long_candidates: list[tuple[int, dict]] = []
    undeclared: list[dict] = []
    for window in _usage_windows(data):
        seconds = _window_seconds(window)
        if seconds is None:
            undeclared.append(window)
        elif seconds < SHORT_WINDOW_LIMIT_SECONDS:
            short_candidates.append((seconds, window))
        else:
            long_candidates.append((seconds, window))

    short = None
    if short_candidates:
        short = min(
            short_candidates,
            key=lambda item: abs(item[0] - SHORT_WINDOW_TARGET_SECONDS),
        )[1]
    long_window = max(long_candidates, key=lambda item: item[0])[1] if long_candidates else None

    # Windows without a declared duration keep the roles the API gave them.
    if short is None and any(window is primary for window in undeclared):
        short = primary
    if long_window is None and any(window is secondary for window in undeclared):
        long_window = secondary
    return short, long_window


def _usage_window_label(window: dict | None, reset_seconds: int | None = None) -> str:
    seconds = _window_seconds(window)
    if seconds is None and reset_seconds is not None:
        seconds = reset_seconds
    if seconds is None:
        return "장기"
    day = 24 * 60 * 60
    if abs(seconds - 5 * 60 * 60) <= 15 * 60:
        return "5h"
    if abs(seconds - 7 * day) <= day:
        return "주간"
    if 27 * day <= seconds <= 32 * day:
        return "월간"
    if seconds >= day:
        days = max(1, round(seconds / day))
        return f"{days}일"
    hours = max(1, round(seconds / 3600))
    return f"{hours}h"


def format_quota(data: dict) -> dict:
    if not data.get("ok"):
        error = data.get("error", "unknown")
        expired = error == "expired"
        return {"email": "?", "plan": "?", "5h_remain": "?", "5h_reset": "?",
                "quota1_label": "한도1", "quota2_label": "한도2",
                "long_remain": "?", "long_reset": "?", "long_label": "장기",
                "wk_remain": "?", "wk_reset": "?", "expired": expired, "error": error}

    five_hour, long_window = _classify_usage_windows(data)

    used_5h = five_hour.get("used_percent") if isinstance(five_hour, dict) else None
    used_long = long_window.get("used_percent") if isinstance(long_window, dict) else None
    five_reset_seconds = _reset_seconds(five_hour)
    long_reset_seconds = _reset_seconds(long_window)
    has_short_window = _window_has_data(five_hour, used_5h, five_reset_seconds)
    has_long_window = _window_has_data(long_window, used_long, long_reset_seconds)
    five_reset = format_reset(five_reset_seconds) if has_short_window else "-"
    five_label = _usage_window_label(five_hour, five_reset_seconds) if has_short_window else "-"
    long_reset = format_reset(long_reset_seconds) if has_long_window else "-"
    long_label = _usage_window_label(long_window, long_reset_seconds) if has_long_window else "-"

    return {
        "email": data.get("email", "?"),
        "plan": data.get("plan_type", "?"),
        "5h_remain": (100 - used_5h) if used_5h is not None else None,
        "5h_reset": five_reset,
        "quota1_label": five_label,
        "quota2_label": long_label,
        "long_remain": (100 - used_long) if used_long is not None else None,
        "long_reset": long_reset,
        "long_label": long_label,
        # Backward-compatible keys for Telegram/status callers.
        "wk_remain": (100 - used_long) if used_long is not None else None,
        "wk_reset": long_reset,
        "expired": False,
        "error": None,
    }


def _window_has_data(window: dict | None, used_percent, reset_seconds: int | None) -> bool:
    return (
        isinstance(window, dict)
        and (
            used_percent is not None
            or reset_seconds is not None
            or _window_seconds(window) is not None
        )
    )


def quota_color(remain) -> str:
    """Color based on remaining percentage."""
    if remain is None:
        return C.GRAY
    if remain >= 70:
        return C.GREEN
    if remain >= 40:
        return C.YELLOW
    if remain >= 15:
        return C.RED
    return C.RED + C.BOLD


def expiry_color(expiry_str: str | None) -> tuple[str, str]:
    """Return (display_str, color) for expiry."""
    if not expiry_str:
        return ("-", C.GRAY)
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        days = (exp - today).days
        display = expiry_str
        if days < 0:
            return (f"{display}(!)", C.RED + C.BOLD)
        if days <= 7:
            return (display, C.RED)
        if days <= 30:
            return (display, C.YELLOW)
        return (display, C.GREEN)
    except ValueError:
        return (expiry_str, C.GRAY)


# === Operations ===

def resolve_email(auth_data: dict) -> str | None:
    result = fetch_quota(auth_data)
    if result.get("ok"):
        return result.get("email")
    return None


def _account_id(auth_data: dict | None) -> str | None:
    if not isinstance(auth_data, dict):
        return None
    value = auth_data.get("tokens", {}).get("account_id")
    return str(value).strip() if value else None


def _has_usable_chatgpt_auth(auth_data: dict | None) -> bool:
    if not isinstance(auth_data, dict) or not _account_id(auth_data):
        return False
    token = auth_data.get("tokens", {}).get("access_token")
    return isinstance(token, str) and bool(token.strip())


def _read_auth_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_accounts_by_id(account_id: str | None) -> list[str]:
    if not account_id:
        return []
    return [
        name for name in list_accounts()
        if _account_id(read_auth(name)) == account_id
    ]


def find_account_by_id(account_id: str | None) -> str | None:
    matches = find_accounts_by_id(account_id)
    return matches[0] if matches else None


def _safe_account_name(value: str | None, account_id: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raw = f"account-{account_id[:8]}"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw).strip(" .")
    if not name or name in (".", ".."):
        name = f"account-{account_id[:8]}"
    return name[:120]


def import_app_auth(
    name_hint: str | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> dict:
    """Import the current ~/.codex/auth.json into the account store.

    Existing accounts are matched by full account_id, so refreshed tokens
    update the right record without requiring another cm login. Secret values
    are never printed or returned.
    """
    live_path = APP_CODEX_HOME / "auth.json"
    if not live_path.exists():
        if not quiet:
            print(f"  {colored('✗', C.RED)} Codex App 로그인이 없습니다: {live_path}")
        return {"ok": False, "error": "app_auth_missing"}

    auth_data = _read_auth_file(live_path)
    account_id = _account_id(auth_data)
    if not _has_usable_chatgpt_auth(auth_data) or not account_id:
        if not quiet:
            print(f"  {colored('✗', C.RED)} 현재 App 인증 파일에 사용 가능한 ChatGPT 토큰이 없습니다.")
        return {"ok": False, "error": "app_auth_invalid"}

    matches = find_accounts_by_id(account_id)
    if len(matches) == 1:
        target = matches[0]
    elif len(matches) > 1:
        hinted = next(
            (name for name in matches if name_hint and name.lower() == name_hint.lower()),
            None,
        )
        resolved = resolve_email(auth_data) if not hinted else None
        resolved_match = next(
            (name for name in matches if resolved and name.lower() == str(resolved).lower()),
            None,
        )
        target = hinted or resolved_match
        if not target:
            if not quiet:
                print(f"  {colored('✗', C.RED)} 같은 account_id를 가진 저장 항목이 여러 개입니다: {', '.join(matches)}")
                print("  cm import-app <정확한 계정 이름> 으로 대상을 지정하세요.")
            return {"ok": False, "error": "duplicate_account_id", "matches": matches}
    else:
        resolved = None if name_hint else resolve_email(auth_data)
        target = _safe_account_name(name_hint or resolved, account_id)
        target_auth = read_auth(target)
        if target_auth and _account_id(target_auth) != account_id:
            if not quiet:
                print(f"  {colored('✗', C.RED)} '{target}' 이름이 다른 계정에서 이미 사용 중입니다.")
            return {"ok": False, "error": "name_conflict", "target": target}

    previous = read_auth(target)
    action = "unchanged" if previous == auth_data else ("updated" if previous else "added")
    if not dry_run and action != "unchanged":
        save_auth(target, auth_data)
        list_accounts()  # Persist a new account in display order.

    if not quiet:
        mode = "확인" if dry_run else "가져오기"
        labels = {"added": "새 계정", "updated": "토큰 갱신", "unchanged": "이미 최신"}
        print(f"  {colored('✓', C.GREEN)} App 로그인 {mode}: {target} ({labels[action]})")
        if dry_run:
            print("  실제 인증 파일은 변경하지 않았습니다.")

    return {
        "ok": True,
        "target": target,
        "action": action,
        "dry_run": dry_run,
        "duplicate_match_count": len(matches),
    }


def sync_matching_app_auth() -> dict:
    """Silently refresh a known cm account from the active App credential."""
    live_path = APP_CODEX_HOME / "auth.json"
    auth_data = _read_auth_file(live_path) if live_path.exists() else None
    account_id = _account_id(auth_data)
    matches = find_accounts_by_id(account_id)
    if not _has_usable_chatgpt_auth(auth_data):
        return {"ok": False, "action": "no_match", "matches": matches}
    resolved_email = resolve_email(auth_data) if len(matches) > 1 else None
    target = match_app_auth_account(
        auth_data,
        matches,
        resolved_email=resolved_email,
    )
    if not target:
        action = "duplicate_account_id" if len(matches) > 1 else "no_match"
        return {"ok": False, "action": action, "matches": matches}
    if read_auth(target) == auth_data:
        return {"ok": True, "target": target, "action": "unchanged"}
    save_auth(target, auth_data)
    return {"ok": True, "target": target, "action": "updated"}


_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)(-[0-9A-Za-z.\-]+)?\b")
_CODEX_CLI_CACHE: dict[str, str] = {}


def _version_key(text: str | None) -> tuple | None:
    """Comparable version key. A prerelease ranks below the same release."""
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    release = tuple(int(part) for part in match.group(1).split("."))
    return (release, -1 if match.group(2) else 0)


def _env_flag_disabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "off", "no"}


def _codex_cli_names() -> list[str]:
    return ["codex.cmd", "codex.exe", "codex"] if os.name == "nt" else ["codex"]


def _codex_cli_candidates() -> list[str]:
    """Every codex CLI executable reachable on PATH, plus the App-embedded one.

    ``shutil.which`` alone is not enough: the App bundle's ``Resources``
    directory is on PATH ahead of the npm global bin, so a single lookup hides
    whichever build is newer.
    """
    candidates: list[str] = []
    names = _codex_cli_names()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                candidates.append(str(candidate))
    runtime = find_codex_runtime_exe()
    if runtime is not None:
        candidates.append(str(runtime))

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _codex_cli_version(command: str) -> str | None:
    code, text = _run_text_command([command, "--version"], timeout=20)
    return text if code == 0 else None


def _resolve_codex_cli() -> tuple[str, str | None]:
    """Pick the highest-version codex CLI so an update can never downgrade."""
    best: tuple[tuple, str, str | None] | None = None
    candidates = _codex_cli_candidates()
    for candidate in candidates:
        text = _codex_cli_version(candidate)
        key = _version_key(text)
        if key is None:
            continue
        if best is None or key > best[0]:
            best = (key, candidate, text)
    if best is not None:
        return best[1], best[2]
    return (candidates[0] if candidates else "codex"), None


def _codex_command() -> str:
    override = os.environ.get("CM_CODEX_COMMAND", "").strip()
    if override:
        return override
    if "command" not in _CODEX_CLI_CACHE:
        command, version = _resolve_codex_cli()
        _CODEX_CLI_CACHE["command"] = command
        _CODEX_CLI_CACHE["version"] = version or ""
    return _CODEX_CLI_CACHE["command"]


def _codex_command_version() -> str | None:
    _codex_command()
    return _CODEX_CLI_CACHE.get("version") or None


def find_codex_runtime_exe() -> Path | None:
    """Find the Codex CLI embedded in the installed ChatGPT/Codex desktop app."""
    override = os.environ.get("CODEX_RUNTIME_EXE", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate.resolve()

    if sys.platform == "darwin":
        for candidate in (
            Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
            Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
            Path("/Applications/Codex.app/Contents/Resources/codex"),
            Path.home() / "Applications/Codex.app/Contents/Resources/codex",
        ):
            if candidate.is_file():
                return candidate.resolve()
        return None

    if os.name == "nt":
        candidates: list[Path] = []
        desktop = find_codex_desktop_exe()
        if desktop is not None:
            candidates.extend(
                [
                    desktop.parent / "resources" / "codex.exe",
                    desktop.parent / "Resources" / "codex.exe",
                    desktop.parent / "codex.exe",
                ]
            )
        for package in _registered_codex_packages():
            candidates.extend(
                [
                    package / "resources" / "codex.exe",
                    package / "Resources" / "codex.exe",
                    package / "app" / "resources" / "codex.exe",
                ]
            )
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
    return None


def _login_timeout_seconds(*, use_browser: bool = False) -> int | None:
    raw = os.environ.get("CM_LOGIN_TIMEOUT_SECONDS", "").strip()
    if not raw:
        # Device auth already has an upstream 15-minute lifetime. Do not add a
        # shorter cm watchdog; browser callback mode still needs a local guard.
        return DEFAULT_LOGIN_TIMEOUT_SECONDS if use_browser else None
    if raw.lower() in {"0", "none", "off", "unlimited"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LOGIN_TIMEOUT_SECONDS if use_browser else None
    return max(60, min(value, 3600))


def _login_retry_delay_seconds() -> int:
    raw = os.environ.get("CM_LOGIN_RETRY_DELAY_SECONDS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_LOGIN_RETRY_DELAY_SECONDS
    except ValueError:
        value = DEFAULT_LOGIN_RETRY_DELAY_SECONDS
    return max(1, min(value, 300))


def _login_command(*, use_browser: bool = False) -> list[str]:
    args = [_codex_command(), "login"]
    if not use_browser:
        args.append("--device-auth")
    return args


def _terminate_process_tree(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_codex_login(
    tmp_home: Path,
    *,
    use_browser: bool = False,
    timeout_seconds: float | None = None,
    command: list[str] | None = None,
) -> int:
    """Run one Codex login attempt with an optional local watchdog."""
    env = os.environ.copy()
    env["CODEX_HOME"] = str(tmp_home)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_ACCESS_TOKEN", None)
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else _login_timeout_seconds(use_browser=use_browser)
    )
    args = list(command) if command else _login_command(use_browser=use_browser)

    mode = "브라우저 콜백" if use_browser else "기기 코드"
    timeout_label = f"로컬 제한 {int(timeout)}초" if timeout is not None else "로컬 제한 없음"
    print(f"  로그인 방식: {mode} / {timeout_label} / Ctrl+C로 안전 취소")
    try:
        proc = subprocess.Popen(
            args,
            env=env,
            cwd=str(Path.home()),
            shell=False,
        )
    except OSError as exc:
        print(f"  {colored('✗', C.RED)} Codex 로그인 실행 실패: {exc.__class__.__name__}")
        return 127

    started = time.monotonic()
    try:
        while proc.poll() is None:
            if timeout is not None and time.monotonic() - started >= timeout:
                _terminate_process_tree(proc)
                print(f"\n  {colored('✗', C.RED)} 로그인 시간이 초과되어 자식 프로세스를 종료했습니다.")
                return 124
            time.sleep(0.2)
        return int(proc.returncode or 0)
    except KeyboardInterrupt:
        _terminate_process_tree(proc)
        print(f"\n  {colored('!', C.YELLOW)} 로그인을 취소하고 대기 프로세스를 정리했습니다.")
        return 130


def run_codex_login_persistent(
    tmp_home: Path,
    *,
    use_browser: bool = False,
    persistent: bool = True,
) -> int:
    """Keep issuing fresh device codes until login succeeds or the user cancels.

    OpenAI expires each individual device-code attempt after 15 minutes. This
    loop cannot change that server-side lifetime; it removes the overall cm
    deadline by starting a fresh official attempt after an unsuccessful one.
    """
    attempt = 0
    while True:
        result = run_codex_login(tmp_home, use_browser=use_browser)
        if result == 0 or use_browser or not persistent or result in (127, 130):
            return result

        attempt += 1
        (tmp_home / "auth.json").unlink(missing_ok=True)
        delay = min(_login_retry_delay_seconds() * attempt, 300)
        print(
            f"\n  {colored('!', C.YELLOW)} 기기 코드 요청이 완료되지 않았습니다. "
            f"{delay}초 후 새 코드를 발급합니다. (Ctrl+C로 종료)"
        )
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            print(f"\n  {colored('!', C.YELLOW)} 지속 대기를 취소했습니다.")
            return 130


def add_account(*, use_browser: bool = False, persistent: bool = True):
    ensure_dirs()
    tmp_home = HOMES_DIR / f"_tmp_login_{os.getpid()}_{time.time_ns()}"
    shutil.rmtree(tmp_home, ignore_errors=True)
    tmp_home.mkdir(parents=True, exist_ok=True)

    print()
    print(f"  {colored('◆ 계정 추가', C.CYAN, C.BOLD)}")
    if use_browser:
        print(f"  {colored('브라우저 OAuth를 시작합니다. localhost 콜백이 막히면 취소 후 기본 기기 코드를 사용하세요.', C.WHITE)}")
    else:
        print(f"  {colored('표시되는 URL과 최신 기기 코드를 사용해 로그인하세요.', C.WHITE)}")
        if persistent:
            print(f"  {colored('코드가 만료되면 새 코드를 계속 발급합니다. Ctrl+C로만 종료됩니다.', C.GRAY)}")
    print()

    try:
        result = run_codex_login_persistent(
            tmp_home,
            use_browser=use_browser,
            persistent=persistent,
        )
        auth_file = tmp_home / "auth.json"
        if result != 0 or not auth_file.exists():
            print(f"\n  {colored('✗ 로그인 실패 또는 취소됨.', C.RED)}")
            return

        auth_data = _read_auth_file(auth_file)
        account_id = _account_id(auth_data)
        if not _has_usable_chatgpt_auth(auth_data) or not account_id:
            print(f"  {colored('✗', C.RED)} 로그인 결과에 사용할 수 있는 ChatGPT 토큰이 없습니다.")
            return

        print(f"  {colored('⟳', C.YELLOW)} 계정 정보 확인 중...", end="\r")
        sys.stdout.flush()
        matches = find_accounts_by_id(account_id)
        email = resolve_email(auth_data) if len(matches) != 1 else None
        if len(matches) > 1:
            existing = next(
                (name for name in matches if email and name.lower() == str(email).lower()),
                None,
            )
            if not existing:
                print(f"  {colored('✗', C.RED)} 같은 account_id 저장 항목이 여러 개라 자동 갱신하지 않았습니다.")
                print(f"  대상: {', '.join(matches)}")
                print("  cm refresh <정확한 계정 이름> 또는 cm import-app <정확한 계정 이름>을 사용하세요.")
                return
        else:
            existing = matches[0] if matches else None
        name = existing or _safe_account_name(email, account_id)
        print(" " * 60, end="\r")

        was_existing = get_auth_path(name).exists()
        save_auth(name, auth_data)
        list_accounts()
        label = "토큰 갱신 완료" if was_existing else "추가 완료"
        print(f"  {colored('✓', C.GREEN)} '{colored(name, C.CYAN)}' {label}!")
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def refresh_account(
    name: str,
    *,
    use_browser: bool = False,
    persistent: bool = True,
):
    print(f"\n  {colored(f'{name} 토큰 갱신 중...', C.CYAN)}")
    old_auth = read_auth(name)
    old_id = old_auth.get("tokens", {}).get("account_id") if old_auth else None
    was_active = name == get_active_account()
    tmp_home = HOMES_DIR / f"_tmp_refresh_{os.getpid()}_{int(time.time())}"
    shutil.rmtree(tmp_home, ignore_errors=True)
    tmp_home.mkdir(parents=True, exist_ok=True)

    try:
        result = run_codex_login_persistent(
            tmp_home,
            use_browser=use_browser,
            persistent=persistent,
        )

        auth_file = tmp_home / "auth.json"
        if result != 0 or not auth_file.exists():
            print(f"  {colored('✗', C.RED)} 갱신 실패.")
            return

        auth_data = _read_auth_file(auth_file)
        new_id = _account_id(auth_data)
        if old_id and new_id and old_id != new_id:
            print(f"  {colored('✗', C.RED)} 다른 계정으로 로그인되었습니다.")
            print(f"  선택 계정 ID: {str(old_id)[:8]} / 새 로그인 ID: {str(new_id)[:8]}")
            print("  저장하지 않았습니다. 같은 계정으로 다시 로그인하세요.")
            return

        quota = fetch_quota(auth_data, account_name=name)
        if not quota.get("ok") and quota.get("error") == "expired":
            print(f"  {colored('✗', C.RED)} 새 토큰이 만료 상태로 확인되어 저장하지 않았습니다.")
            return

        save_auth(name, auth_data)
        if was_active:
            shutil.copy2(get_auth_path(name), CODEX_HOME / "auth.json")

        if quota.get("ok"):
            email = quota.get("email") or name
            print(f"  {colored('✓', C.GREEN)} 갱신 완료! ({email})")
        else:
            print(f"  {colored('✓', C.GREEN)} 토큰 저장 완료.")
            print(f"  {colored('!', C.YELLOW)} usage 확인 실패: {quota.get('error', 'unknown')} (cm quota-debug {name})")
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def switch_account(target: str | None = None):
    accounts = list_accounts()
    if not accounts:
        print("  등록된 계정 없음.")
        return
    if target is None:
        show_table(accounts)
        target = resolve_account_selector(input("\n  전환할 계정: ").strip(), accounts)
        if target is None:
            return
    else:
        target = resolve_account_selector(target, accounts)
        if target is None:
            return

    auth_path = get_auth_path(target)
    if not auth_path.exists():
        print(f"  '{target}' 없음.")
        return

    print()
    print(f"  {colored('◆', C.CYAN)} App 계정 전환: {colored(target, C.CYAN, C.BOLD)}")
    print()

    if find_codex_desktop_exe() is None:
        print(f"  {colored('✗', C.RED)} 현재 OS의 Codex Desktop App 실행 파일을 찾지 못했습니다.")
        print("  auth.json은 변경하지 않았습니다.")
        return
    if os.name == "nt" and _windows_powershell_executable() is None:
        print(f"  {colored('✗', C.RED)} PowerShell 7(pwsh) 또는 Windows PowerShell을 찾지 못했습니다.")
        print("  auth.json은 변경하지 않았습니다.")
        return

    isolated_pids = _isolated_app_pids()

    # Step 1: Kill App
    app_was_running = _kill_codex_app()
    if app_was_running:
        _print_step(1, "App 종료 중...")
        _wait_codex_app_exit()
        _print_step_done(1, "App 종료됨")
    else:
        _print_step_done(1, "App 미실행 (건너뜀)")

    synced = sync_thread_index(target, home=APP_CODEX_HOME, active=_default_home_active())
    if synced is None or synced.get("reason") == "home_active":
        print("  계정 전환을 중단했습니다. auth.json은 변경하지 않았습니다.")
        if app_was_running:
            _start_codex_app()
        return

    live_auth_path = CODEX_HOME / "auth.json"
    previous_auth = live_auth_path.read_bytes() if live_auth_path.exists() else None
    previous_mode = (live_auth_path.stat().st_mode & 0o777) if live_auth_path.exists() else None

    try:
        # Step 2: Swap auth
        _print_step(2, "auth.json 교체 중...")
        shutil.copy2(auth_path, live_auth_path)
        _print_step_done(2, f"auth.json → {target}")

        # Step 3: Restart App
        _print_step(3, "App 시작 중...")
        _start_codex_app()
        app_pid = _wait_for_default_app_pid()
        _print_step_done(3, "App 시작됨" if app_pid else "App 시작 확인 실패")
    except Exception as exc:
        if previous_auth is None:
            live_auth_path.unlink(missing_ok=True)
        else:
            live_auth_path.write_bytes(previous_auth)
            if previous_mode is not None:
                live_auth_path.chmod(previous_mode)
        print()
        print(f"  {colored('✗', C.RED)} App 재시작 실패: {exc}")
        print("  기존 auth.json으로 복구했습니다.")
        return

    print()
    if app_pid:
        print(f"  {colored('✓ 완료!', C.GREEN, C.BOLD)} App이 새 계정으로 실행 중입니다. PID={app_pid}")
    else:
        # auth.json is already switched, so the credential change must not be
        # rolled back just because the GUI did not report a new PID in time.
        print(f"  {colored('!', C.YELLOW)} auth.json은 전환했지만 App 시작을 확인하지 못했습니다.")
        print("  App을 직접 실행하면 새 계정으로 열립니다.")
    print(f"  현재 App 계정은 {colored(target, C.CYAN, C.BOLD)} 입니다.")
    if isolated_pids:
        print(
            f"  {colored('!', C.YELLOW)} 별도 실행 중인 계정별 App {len(isolated_pids)}개는 "
            "그대로 유지됩니다(각자 독립 CODEX_HOME)."
        )
    notify_account_change("app", target, read_auth(target))


def _default_home_active() -> bool:
    """Whether anything still uses the shared ~/.codex home."""
    if _is_codex_app_running():
        return True
    try:
        return bool(_database_open_pids(codex_thread_index.database_path(APP_CODEX_HOME)))
    except (OSError, subprocess.SubprocessError):
        return False


def _print_step(num: int, msg: str):
    """Print a step in progress."""
    print(f"  {colored(f'[{num}/3]', C.GRAY)} {colored('⟳', C.YELLOW)} {msg}", end="\r")
    sys.stdout.flush()


def _print_step_done(num: int, msg: str):
    """Print a completed step."""
    print(f"  {colored(f'[{num}/3]', C.GRAY)} {colored('✓', C.GREEN)} {msg}          ")


def _windows_powershell_executable() -> str | None:
    """Prefer PowerShell 7 and retain Windows PowerShell as a local fallback."""
    if os.name != "nt":
        return None
    pwsh = shutil.which("pwsh")
    if pwsh:
        return pwsh
    program_files = os.environ.get("ProgramFiles", "").strip()
    if program_files:
        candidate = Path(program_files) / "PowerShell" / "7" / "pwsh.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("powershell")


def _run_windows_powershell(script: str, **kwargs):
    executable = _windows_powershell_executable()
    if executable is None:
        raise RuntimeError("PowerShell 7(pwsh) or Windows PowerShell is required")
    return subprocess.run([executable, "-NoProfile", "-Command", script], **kwargs)


def _macos_codex_bundle() -> Path | None:
    exe = find_codex_desktop_exe()
    if exe is None:
        return None
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def _is_isolated_app_command(command: str) -> bool:
    """Whether an App command line is bound to a cm per-account user-data dir.

    ``cm app`` launches every account in its own Electron user-data directory
    under ``APP_PROFILES_DIR``. Those instances are independent of the default
    App and of ``~/.codex/auth.json``, so global switch must never quit them.
    """
    return f"--user-data-dir={APP_PROFILES_DIR}" in command


def _macos_app_processes() -> list[tuple[int, str]]:
    """Return (pid, command) for main Codex/ChatGPT App processes on macOS."""
    exe = find_codex_desktop_exe()
    if exe is None:
        return []
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    prefix = f"{exe} "
    processes: list[tuple[int, str]] = []
    for line in stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid_text, command = fields
        if command != str(exe) and not command.startswith(prefix):
            continue
        try:
            processes.append((int(pid_text), command))
        except ValueError:
            pass
    return processes


def _macos_codex_pids() -> list[int]:
    return [pid for pid, _ in _macos_app_processes()]


def _macos_default_app_pids() -> list[int]:
    """PIDs of the shared default App instance (the one bound to ~/.codex)."""
    return [
        pid for pid, command in _macos_app_processes()
        if not _is_isolated_app_command(command)
    ]


def _macos_isolated_app_pids() -> list[int]:
    """PIDs of per-account App instances launched by ``cm app``."""
    return [
        pid for pid, command in _macos_app_processes()
        if _is_isolated_app_command(command)
    ]


def _macos_app_profile_pids(profile: Path, *, exe: Path | None = None) -> list[int]:
    """Return macOS Desktop App PIDs using one exact isolated user-data path."""
    executable = exe or find_codex_desktop_exe()
    if executable is None:
        return []
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    executable_prefix = f"{executable} "
    profile_argument = f"--user-data-dir={profile}"
    pids = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid_text, command = fields
        if not command.startswith(executable_prefix) or profile_argument not in command:
            continue
        try:
            pids.append(int(pid_text))
        except ValueError:
            pass
    return pids


def _activate_macos_app_pid(pid: int) -> bool:
    """Bring one exact App instance forward instead of the shared bundle ID."""
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                "tell application \"System Events\" to set frontmost of "
                f"first application process whose unix id is {int(pid)} to true",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _macos_app_window_count(pid: int) -> int | None:
    """Visible window count of one App instance, or None when unknown.

    An App whose last window was closed keeps running with zero windows.
    Activating it then brings nothing to the screen, so cm must restart that
    exact instance instead of reporting a successful activation.
    """
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                "tell application \"System Events\" to count windows of "
                f"(first application process whose unix id is {int(pid)})",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout or "").strip()
    return int(text) if text.isdigit() else None


def _terminate_pids(pids: list[int], *, timeout: float = 15) -> bool:
    """Ask the given processes to quit and wait for them to disappear."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_pid_alive(pid) for pid in pids):
            return True
        time.sleep(0.25)
    return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_macos_app_profile_pid(
    profile: Path,
    *,
    exe: Path,
    timeout: float = 10,
) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = _macos_app_profile_pids(profile, exe=exe)
        if pids:
            return pids[-1]
        time.sleep(0.1)
    return None


def _windows_app_pids(*, default_only: bool = False) -> list[int]:
    """App PIDs on Windows, optionally excluding cm per-account instances."""
    if os.name != "nt":
        return []
    needle = str(APP_PROFILES_DIR).replace("'", "''")
    clause = "$_.Name -in @('ChatGPT.exe','Codex.exe')"
    if default_only:
        clause += " -and -not ($_.CommandLine -and $_.CommandLine.Contains($needle))"
    script = (
        "$needle = '" + needle + "'; "
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { " + clause + " } | Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = _run_windows_powershell(
            script, capture_output=True, text=True, timeout=8, check=False
        )
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return []
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    return [int(line.strip()) for line in stdout.splitlines() if line.strip().isdigit()]


def _default_app_pids() -> list[int]:
    if sys.platform == "darwin":
        return _macos_default_app_pids()
    if os.name == "nt":
        return _windows_app_pids(default_only=True)
    return []


def _isolated_app_pids() -> list[int]:
    if sys.platform == "darwin":
        return _macos_isolated_app_pids()
    if os.name == "nt":
        all_pids = set(_windows_app_pids())
        return sorted(all_pids - set(_windows_app_pids(default_only=True)))
    return []


def _is_codex_app_running() -> bool:
    """Whether the shared default App instance is running.

    Per-account instances from ``cm app`` are deliberately excluded: they own a
    separate CODEX_HOME, so a global switch neither affects nor waits on them.
    """
    if sys.platform == "darwin" or os.name == "nt":
        return bool(_default_app_pids())
    return False


def _wait_for_default_app_pid(timeout: float = 15) -> int | None:
    """Wait until the default App instance appears and return its PID."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = _default_app_pids()
        if pids:
            return pids[-1]
        time.sleep(0.25)
    return None


def _kill_codex_app() -> bool:
    """Quit the default App instance only. Returns True if it was running."""
    killed = _is_codex_app_running()

    if sys.platform == "darwin":
        if not killed:
            return False
        bundle = _macos_codex_bundle()
        bundle_id = None
        if bundle is not None:
            try:
                with (bundle / "Contents" / "Info.plist").open("rb") as handle:
                    bundle_id = plistlib.load(handle).get("CFBundleIdentifier")
            except (OSError, plistlib.InvalidFileException):
                pass
        result = None
        # A bundle-ID quit targets every instance of the bundle, so it is only
        # safe while no per-account App instance is running.
        if bundle_id and not _macos_isolated_app_pids():
            result = subprocess.run(
                ["osascript", "-e", f'tell application id "{bundle_id}" to quit'],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        if result is None or result.returncode != 0:
            for pid in _macos_default_app_pids():
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        return True

    if os.name != "nt":
        return False

    pids = _windows_app_pids(default_only=True)
    if pids:
        id_list = ",".join(str(pid) for pid in pids)
        _run_windows_powershell(
            f"Stop-Process -Id {id_list} -Force -ErrorAction SilentlyContinue",
            capture_output=True,
            timeout=10,
            check=False,
        )
    # Also kill app-server codex.exe (not npm codex)
    _run_windows_powershell(
        "Get-Process -Name 'codex' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -match 'OpenAI' } | Stop-Process -Force",
        capture_output=True,
        timeout=10,
        check=False,
    )
    return killed


def _wait_codex_app_exit(timeout: int = 10):
    """Wait until the default App and its app-server release the shared home."""
    spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    for i in range(timeout * 4):
        database_users = _database_open_pids(codex_thread_index.database_path(APP_CODEX_HOME))
        if not _is_codex_app_running() and not database_users:
            return
        s = spinner[i % len(spinner)]
        print(f"  {colored(f'[1/3]', C.GRAY)} {colored(s, C.YELLOW)} App 종료 대기 중...", end="\r")
        sys.stdout.flush()
        time.sleep(0.25)
    raise RuntimeError(f"Codex App/app-server가 {timeout}초 안에 종료되지 않았습니다.")


def _start_codex_app():
    """Start the default App instance bound to the shared ~/.codex home."""
    if sys.platform == "darwin":
        bundle = _macos_codex_bundle()
        if bundle is None:
            raise RuntimeError("Codex Desktop App bundle not found")
        # cm is often invoked from an isolated Codex task, whose process
        # environment contains that task's account, Electron profile, SQLite
        # home and thread id.  LaunchServices propagates the caller environment
        # into a new instance, so inheriting those values creates a window that
        # looks like the default App while internally mixing two account homes.
        # A default launch has one authoritative setting: APP_CODEX_HOME.
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("CODEX_") and key != "OPENAI_API_KEY"
        }
        environment["CODEX_HOME"] = str(APP_CODEX_HOME)
        environment["CODEX_ELECTRON_USER_DATA_PATH"] = str(DEFAULT_MACOS_APP_PROFILE)
        # ``-n`` is required: without it LaunchServices only activates an
        # already running per-account instance and the default App never
        # starts, which used to report a successful switch that never happened.
        # ``--env`` pins the default instance to the shared home because
        # LaunchServices does not inherit this process's environment.
        subprocess.Popen(
            [
                "open",
                "-n",
                str(bundle),
                "--env",
                f"CODEX_HOME={APP_CODEX_HOME}",
                "--env",
                f"CODEX_ELECTRON_USER_DATA_PATH={DEFAULT_MACOS_APP_PROFILE}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=environment,
        )
        return
    if os.name == "nt":
        executable = find_codex_desktop_exe()
        if executable is None:
            raise RuntimeError("Codex Desktop App executable not found")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [str(executable)],
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return
    raise RuntimeError(f"Codex Desktop App switch is unsupported on {sys.platform}")


def _parse_appx_version(path: Path) -> tuple[int, ...]:
    name = path.name
    prefix = "OpenAI.Codex_"
    if not name.startswith(prefix):
        return ()
    version = name[len(prefix):].split("_", 1)[0]
    result = []
    for part in version.split("."):
        try:
            result.append(int(part))
        except ValueError:
            result.append(0)
    return tuple(result)


def _appx_desktop_executable(package: Path) -> Path | None:
    """Resolve the full-trust executable declared by an Appx package."""
    manifest = package / "AppxManifest.xml"
    try:
        root = ET.parse(manifest).getroot()
    except (OSError, ET.ParseError):
        return None

    package_root = package.resolve()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Application":
            continue
        executable = element.attrib.get("Executable", "").strip()
        if not executable:
            continue
        candidate = package / Path(executable.replace("/", os.sep))
        try:
            candidate.resolve().relative_to(package_root)
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            return candidate
    return None


def _registered_codex_packages() -> list[Path]:
    """Read installed Codex package roots without relying on AppX cmdlets."""
    if winreg is None:
        return []
    repository = (
        r"Software\Classes\Local Settings\Software\Microsoft\Windows"
        r"\CurrentVersion\AppModel\Repository\Packages"
    )
    packages = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, repository) as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if not name.startswith("OpenAI.Codex_"):
                    continue
                try:
                    with winreg.OpenKey(root, name) as package_key:
                        location, _ = winreg.QueryValueEx(package_key, "PackageRootFolder")
                except OSError:
                    continue
                if location:
                    packages.append(Path(location))
    except OSError:
        pass
    return packages


def find_codex_desktop_exe() -> Path | None:
    """Find the native Codex desktop executable for the current platform."""
    override = os.environ.get("CODEX_DESKTOP_EXE", "").strip()
    if override:
        exe = Path(override)
        if exe.exists():
            return exe

    if sys.platform == "darwin":
        for exe in (
            Path("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"),
            Path.home() / "Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
            Path("/Applications/Codex.app/Contents/MacOS/Codex"),
            Path.home() / "Applications/Codex.app/Contents/MacOS/Codex",
        ):
            if exe.exists():
                return exe
        return None

    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"
    candidates = []

    for package in _registered_codex_packages():
        exe = _appx_desktop_executable(package)
        if exe is not None:
            candidates.append((_parse_appx_version(package), exe))

    if os.name == "nt" and not candidates:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue).InstallLocation"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            for line in result.stdout.splitlines():
                package = Path(line.strip())
                exe = _appx_desktop_executable(package)
                if exe is not None:
                    candidates.append((_parse_appx_version(package), exe))
        except Exception:
            pass

    if not candidates:
        try:
            for package in root.glob("OpenAI.Codex_*_x64__2p2nqsd0c76g0"):
                exe = _appx_desktop_executable(package)
                if exe is not None:
                    candidates.append((_parse_appx_version(package), exe))
        except OSError:
            pass

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def app_profile_dir(name: str) -> Path:
    return APP_PROFILES_DIR / stable_account_key(name)


def _windows_app_profile_pids(profile: Path) -> list[int]:
    if os.name != "nt":
        return []
    needle = str(profile.resolve()).replace("'", "''")
    script = (
        f"$needle = '{needle}'; "
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -in @('ChatGPT.exe','Codex.exe') -and "
        "$_.CommandLine -and $_.CommandLine.Contains($needle) } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = _run_windows_powershell(
            script, capture_output=True, text=True, timeout=8, check=False
        )
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return []
    return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _app_profile_pids(profile: Path, *, exe: Path | None = None) -> list[int]:
    if sys.platform == "darwin":
        return _macos_app_profile_pids(profile, exe=exe)
    if os.name == "nt":
        return _windows_app_profile_pids(profile)
    return []


def _database_open_pids(path: Path) -> list[int]:
    if os.name == "nt" or not path.exists():
        return []
    lsof = Path("/usr/sbin/lsof")
    if not lsof.is_file():
        return []
    result = subprocess.run(
        [str(lsof), "-t", "--", str(path)],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    return sorted({int(line) for line in result.stdout.splitlines() if line.strip().isdigit()})


def thread_home_activity(name: str, home: Path) -> dict:
    profile_pids = _app_profile_pids(app_profile_dir(name))
    cli_pids = [int(pid) for pid, account in load_cli_sessions().items() if account == name]
    db_pids = _database_open_pids(codex_thread_index.database_path(home))
    remote = False
    try:
        remote_state = _remote_status()
        remote = bool(
            remote_state.get("ssh_active") and remote_state.get("target_account") == name
        )
    except (ImportError, OSError, RuntimeError):
        pass
    return {
        "active": bool(profile_pids or cli_pids or db_pids or remote),
        "app_pids": profile_pids,
        "cli_pids": cli_pids,
        "database_pids": db_pids,
        "remote": remote,
    }


def sync_thread_index(
    name: str,
    *,
    home: Path | None = None,
    force: bool = False,
    active: bool | None = None,
    quiet: bool = False,
) -> dict | None:
    target_home = home or setup_isolated_home(name)
    runtime = find_codex_runtime_exe()
    if runtime is None:
        if not quiet:
            print(f"  {colored('✗', C.RED)} ChatGPT/Codex App 내장 runtime을 찾지 못했습니다.")
        return None
    activity = thread_home_activity(name, target_home)
    is_active = activity["active"] if active is None else active
    try:
        result = codex_thread_index.synchronize(
            MANAGER_DIR,
            account_key="app-default" if target_home.resolve() == APP_CODEX_HOME.resolve() else stable_account_key(name),
            account_name=name,
            home=target_home,
            codex_exe=runtime,
            active=is_active,
            force=force,
        )
    except Exception as exc:
        if not quiet:
            print(f"  {colored('✗', C.RED)} 로컬 스레드 색인 동기화 실패: {exc}")
        return None
    if quiet:
        return result
    if result.get("reason") == "home_active":
        print(f"  {colored('!', C.YELLOW)} {name}: 실행 중인 App/CLI/app-server가 있어 건너뜁니다.")
    elif result.get("reason") == "up_to_date":
        restored = result.get("project_assignments", {}).get("added", 0)
        suffix = f" · 프로젝트 배정 {restored}개 복구" if restored else ""
        print(f"  {colored('✓', C.GREEN)} {name}: 스레드 색인이 최신입니다.{suffix}")
    else:
        print(
            f"  {colored('✓', C.GREEN)} {name}: 스레드 색인 {result['before']} → "
            f"{result['after']} (모델 호출 0회)"
        )
    return result


def build_app_account_env(name: str, *, prepare: bool = True) -> tuple[dict, Path, Path]:
    home = setup_isolated_home(name) if prepare else HOMES_DIR / stable_account_key(name)
    profile = app_profile_dir(name)
    if prepare:
        profile.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    # Verified in the desktop bootstrap: this is read before requestSingleInstanceLock().
    env["CODEX_ELECTRON_USER_DATA_PATH"] = str(profile)
    env["CODEX_MULTI_ACCOUNT_NAME"] = name
    env.pop("OPENAI_API_KEY", None)
    return env, home, profile


def launch_app_account(
    target: str | None = None,
    app_args: list[str] | None = None,
    dry_run: bool = False,
    *,
    activate_existing: bool = True,
    restart: bool = False,
):
    accounts = list_accounts()
    if not accounts:
        print("  등록된 계정 없음.")
        return None
    if target is None:
        show_table(accounts)
        target = resolve_account_selector(input("\n  App으로 실행할 계정: ").strip(), accounts)
        if target is None:
            return None
    else:
        target = resolve_account_selector(target, accounts)
        if target is None:
            return None

    if not read_auth(target):
        print(f"  '{target}' 인증 정보 없음.")
        return None

    exe = find_codex_desktop_exe()
    if exe is None:
        print("  Codex Desktop App 실행 파일을 찾지 못했습니다.")
        return None

    env, home, profile = build_app_account_env(target, prepare=not dry_run)
    args = [str(exe), f"--user-data-dir={profile}"] + list(app_args or [])
    if sys.platform == "darwin":
        bundle = _macos_codex_bundle()
        if bundle is None:
            print("  Codex Desktop App bundle을 찾지 못했습니다.")
            return None
        args = [
            "open",
            "-n",
            "-a",
            str(bundle),
            "--env",
            f"CODEX_HOME={home}",
            "--env",
            f"CODEX_ELECTRON_USER_DATA_PATH={profile}",
            "--env",
            f"CODEX_MULTI_ACCOUNT_NAME={target}",
            "--args",
            f"--user-data-dir={profile}",
        ] + list(app_args or [])

    print()
    print(f"  {colored('◆', C.CYAN)} App 별도 실행: {colored(target, C.CYAN, C.BOLD)}")
    print(f"  CODEX_HOME: {home}")
    print(f"  USER_DATA : {profile}")
    if not dry_run:
        warn_shared_config_conflicts(target)

    if dry_run:
        print(f"  EXE       : {args[0]}")
        print(f"  ARGS      : {' '.join(args[1:]) if len(args) > 1 else '(none)'}")
        return {"target": target, "home": home, "profile": profile, "exe": exe, "args": args}

    if sys.platform == "darwin":
        existing_pids = _macos_app_profile_pids(profile, exe=exe)
        if existing_pids:
            app_pid = existing_pids[-1]
            if not activate_existing and not restart:
                print(f"  {colored('✓', C.GREEN)} 실행 중인 App 재사용. PID={app_pid}")
                return app_pid
            activated = False if restart else _activate_macos_app_pid(app_pid)
            windows = _macos_app_window_count(app_pid) if activated else None
            if activated and windows != 0:
                notify_account_change("app", target, read_auth(target), pid=app_pid)
                print(f"  {colored('✓', C.GREEN)} 실행 중인 App 창 활성화. PID={app_pid}")
                return app_pid
            if restart:
                reason = "요청에 따라"
            elif windows == 0:
                reason = "창이 없어서"
            else:
                reason = "활성화가 안 되어서"
            print(
                f"  {colored('!', C.YELLOW)} 이 계정 App({', '.join(str(p) for p in existing_pids)})은 "
                f"{reason} 재시작합니다. 다른 계정 App은 건드리지 않습니다."
            )
            if not _terminate_pids(existing_pids):
                print(f"  {colored('✗', C.RED)} 해당 계정 App이 종료되지 않았습니다. 수동으로 종료 후 다시 실행하세요.")
                return None

        # Reconcile source changes and project assignments while the account
        # home is inactive. Normal launches do not force a destructive rebuild.
        synced = sync_thread_index(target, home=home)
        if synced is None or synced.get("reason") == "home_active":
            print("  App 실행을 중단했습니다. 스레드 색인을 먼저 안전하게 복구하세요.")
            return None

        subprocess.Popen(
            args,
            env=env,
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        app_pid = _wait_for_macos_app_profile_pid(profile, exe=exe)
        if app_pid is None:
            print(f"  {colored('!', C.YELLOW)} App 실행을 요청했지만 계정별 PID를 확인하지 못했습니다.")
            return None
        activated = _activate_macos_app_pid(app_pid)
        notify_account_change("app", target, read_auth(target), pid=app_pid)
        if activated:
            print(f"  {colored('✓', C.GREEN)} App 실행 및 창 활성화 완료. PID={app_pid}")
        else:
            print(
                f"  {colored('!', C.YELLOW)} App은 실행됐지만 창 활성화에 실패했습니다. "
                f"PID={app_pid}"
            )
        return app_pid

    existing_pids = _app_profile_pids(profile, exe=exe)
    if existing_pids:
        app_pid = existing_pids[-1]
        if not restart:
            print(f"  {colored('✓', C.GREEN)} 실행 중인 App 재사용. PID={app_pid}")
            return app_pid
        print(
            f"  {colored('!', C.YELLOW)} 이 계정 App({', '.join(str(p) for p in existing_pids)})만 "
            "재시작합니다."
        )
        if not _terminate_pids(existing_pids):
            print(f"  {colored('✗', C.RED)} 해당 계정 App이 종료되지 않았습니다.")
            return None

    # Reconcile source changes and project assignments while the account home
    # is inactive. Normal launches do not force a destructive rebuild.
    synced = sync_thread_index(target, home=home)
    if synced is None or synced.get("reason") == "home_active":
        print("  App 실행을 중단했습니다. 스레드 색인을 먼저 안전하게 복구하세요.")
        return None

    popen_options = {}
    if os.name == "nt":
        popen_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        # A macOS Electron app launched from the interactive TUI must not stay
        # in cm's terminal process group. Otherwise its activation can leave
        # cm in the background and the following TUI read is stopped by SIGTTIN.
        popen_options["start_new_session"] = True
    proc = subprocess.Popen(
        args,
        env=env,
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_options,
    )
    notify_account_change("app", target, read_auth(target), pid=proc.pid)
    print(f"  {colored('✓', C.GREEN)} App 실행 요청 완료. PID={proc.pid}")
    return proc


def _is_expected_symlink(link: Path, target: Path) -> bool:
    if not link.is_symlink():
        return False
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


def _backup_existing_shared_item(path: Path):
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.local-backup-{stamp}")
    suffix = 1
    while backup.exists() or backup.is_symlink():
        backup = path.with_name(f"{path.name}.local-backup-{stamp}-{suffix}")
        suffix += 1
    path.rename(backup)


def _ensure_shared_link(home: Path, item: str):
    target = CODEX_HOME / item
    if not target.exists():
        return

    link = home / item
    if _is_expected_symlink(link, target):
        return

    if link.is_symlink():
        link.unlink()
    elif link.exists():
        try:
            _backup_existing_shared_item(link)
        except OSError:
            return

    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError:
        return


def _auth_refresh_time(auth_data: dict | None) -> float:
    if not isinstance(auth_data, dict):
        return 0.0
    value = auth_data.get("last_refresh")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return 0.0


def sync_isolated_home_auth(name: str) -> bool:
    """Promote a newer refresh-token set from an isolated home to the store."""
    stored = read_auth(name)
    home_path = HOMES_DIR / stable_account_key(name) / "auth.json"
    home_auth = _read_auth_file(home_path) if home_path.exists() else None
    if not _has_usable_chatgpt_auth(stored) or not _has_usable_chatgpt_auth(home_auth):
        return False
    if _account_id(stored) != _account_id(home_auth):
        return False
    duplicate_names = find_accounts_by_id(_account_id(home_auth))
    if len(duplicate_names) > 1:
        resolved_email = resolve_email(home_auth)
        if not resolved_email or resolved_email.strip().lower() != name.strip().lower():
            return False
    if _auth_refresh_time(home_auth) <= _auth_refresh_time(stored):
        return False
    save_auth(name, home_auth)
    return True


def _retarget_isolated_home_paths(text: str, home: Path) -> str:
    """Point any isolated-home absolute path in a config at this account's home."""
    pattern = re.compile(re.escape(str(HOMES_DIR)) + r"[\\/][A-Za-z0-9_.\-]+")
    return pattern.sub(lambda _match: str(home), text)


def sync_account_config(home: Path) -> bool:
    """Render a real per-account config.toml from the shared ~/.codex master.

    Returns True when the account config was written or rewritten. The master
    keeps being the single place to change settings, but each account gets its
    own file so one account's absolute paths never leak into another's session.
    """
    master = APP_CODEX_HOME / "config.toml"
    target = home / "config.toml"
    if not master.exists():
        return False
    try:
        rendered = _retarget_isolated_home_paths(
            master.read_text(encoding="utf-8"), home
        )
    except OSError:
        return False

    if target.is_symlink():
        # Migration from the old shared-symlink layout.
        target.unlink()
    try:
        if target.exists() and target.read_text(encoding="utf-8") == rendered:
            return False
        target.write_text(rendered, encoding="utf-8")
        shutil.copymode(master, target)
    except OSError:
        return False
    return True


def sync_account_global_state(home: Path) -> bool:
    """Give each Electron instance a private, atomically writable state file.

    Electron replaces this JSON file during ordinary saves.  A shared symlink
    therefore silently becomes a private file after the first write and leaves
    different accounts with unpredictable project/thread metadata.  Seed a
    missing or legacy-linked account state from the App home, then let the
    account own its copy.
    """
    master = APP_CODEX_HOME / ".codex-global-state.json"
    target = home / ".codex-global-state.json"
    if not master.is_file():
        return False
    if target.exists() and not target.is_symlink():
        return False
    try:
        data = json.loads(master.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
    except (OSError, json.JSONDecodeError):
        return False
    _atomic_write_json(target, data, ensure_ascii=False)
    return True


def setup_isolated_home(name: str) -> Path:
    home = HOMES_DIR / stable_account_key(name)
    home.mkdir(parents=True, exist_ok=True)
    sync_isolated_home_auth(name)
    auth_src = get_auth_path(name)
    if auth_src.exists():
        shutil.copy2(auth_src, home / "auth.json")
    sync_account_config(home)
    sync_account_global_state(home)
    for item in SHARED_ITEMS:
        _ensure_shared_link(home, item)
    return home


def launch_account(target: str | None = None, codex_args: list[str] | None = None):
    accounts = list_accounts()
    if not accounts:
        print("  등록된 계정 없음.")
        return
    if target is None:
        show_table(accounts)
        target = resolve_account_selector(input("\n  CLI로 실행할 계정: ").strip(), accounts)
        if target is None:
            return
    else:
        target = resolve_account_selector(target, accounts)
        if target is None:
            return

    home = setup_isolated_home(target)
    print(f"\n  {colored('Codex 실행', C.CYAN)} (계정: {target}, 독립 세션)")
    codex_command = ensure_codex_cli_current()
    warn_shared_config_conflicts(target)
    print()
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    env.pop("OPENAI_API_KEY", None)
    proc = subprocess.Popen(
        [codex_command] + list(codex_args or []),
        env=env,
        cwd=os.getcwd(),
        shell=False,
    )
    record_cli_session(target, proc.pid)
    notify_account_change("cli", target, read_auth(target), pid=proc.pid)
    try:
        proc.wait()
    finally:
        sync_isolated_home_auth(target)
        remove_cli_session(proc.pid)


def move_account(accounts: list[str]):
    """Move account position."""
    choice = input("  이동할 번호: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(accounts)):
        return
    idx = int(choice) - 1
    name = accounts[idx]
    new_pos = input(f"  '{name}' → 새 위치 (1-{len(accounts)}): ").strip()
    if not new_pos.isdigit() or not (1 <= int(new_pos) <= len(accounts)):
        return
    new_idx = int(new_pos) - 1
    accounts.pop(idx)
    accounts.insert(new_idx, name)
    save_order(accounts)
    print(f"  {colored('✓', C.GREEN)} 순서 변경됨.")


def set_account_expiry(accounts: list[str]):
    choice = input("  번호: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(accounts)):
        return
    name = accounts[int(choice) - 1]
    date_str = input(f"  '{name}' 구독 만료일 (YYYY-MM-DD, 빈칸=삭제): ").strip()
    if date_str:
        set_expiry(name, date_str)
        print(f"  {colored('✓', C.GREEN)} 만료일 설정: {date_str}")
    else:
        meta = load_meta()
        if name in meta:
            meta[name].pop("expiry", None)
            save_meta(meta)
        print(f"  {colored('✓', C.GREEN)} 만료일 삭제됨.")


def edit_account_phone(name: str):
    current = get_account_phone(name)
    if current:
        print(f"  현재 인증 전화번호: {colored(current, C.CYAN)}")
    phone = input("  인증에 사용한 전화번호 (빈칸=삭제): ").strip()
    set_account_phone(name, phone or None)
    if phone:
        print(f"  {colored('✓', C.GREEN)} 전화번호 기록: {phone}")
    else:
        print(f"  {colored('✓', C.GREEN)} 전화번호 삭제됨.")


# === Display ===

def terminal_width(default: int = 100) -> int:
    try:
        return max(50, shutil.get_terminal_size((default, 24)).columns)
    except OSError:
        return default


def display_width(text: str) -> int:
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return width


def clip(text: str, width: int) -> tuple[str, int]:
    text = str(text)
    if width <= 0:
        return "", 0

    chars = []
    used = 0
    truncated = False
    for ch in text:
        ch_width = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if used + ch_width > width:
            truncated = True
            break
        chars.append(ch)
        used += ch_width

    if truncated and width > 1:
        while chars and used + 1 > width:
            removed = chars.pop()
            used -= 2 if unicodedata.east_asian_width(removed) in ("F", "W") else 1
        chars.append("…")
        used += 1

    return "".join(chars), used


def format_cell(value: str, width: int, align: str) -> str:
    text, used = clip(str(value), width)
    pad = " " * max(0, width - used)
    if align == "right":
        return pad + text
    return text + pad


def pct_text(value, expired: bool = False) -> str:
    if expired:
        return "EXP"
    if value is None or value == "?":
        return "?"
    if isinstance(value, (int, float)):
        clamped = max(0, min(100, value))
        if abs(clamped - round(clamped)) < 0.01:
            return f"{round(clamped)}%"
        return f"{clamped:.1f}%"
    return str(value)


def reset_text(value, expired: bool = False) -> str:
    if expired:
        return "EXP"
    return value or "?"


def status_text(q: dict) -> str:
    if q["expired"]:
        return "EXP"
    if q.get("error"):
        return "ERR"
    return "OK"


def quota_slot_text(label, remain, reset, expired: bool) -> tuple[str, str]:
    """Render one quota column. A plan without that window shows '-', not '?'."""
    if label == "-" and not expired:
        return "-", "-"
    return pct_text(remain, expired), f"{label} {reset_text(reset, expired)}"


def primary_quota_display(q: dict) -> tuple[str, str]:
    """Label and percentage of the window a plan actually reports.

    Team/Business accounts have no 5h window, so the summary line must fall
    back to their monthly window instead of printing '?'.
    """
    expired = q.get("expired", False)
    if q.get("quota1_label") not in (None, "-", "한도1"):
        return str(q.get("quota1_label")), pct_text(q.get("5h_remain"), expired)
    if q.get("quota2_label") not in (None, "-", "한도2"):
        return str(q.get("quota2_label")), pct_text(q.get("long_remain"), expired)
    return "한도1", pct_text(q.get("5h_remain"), expired)


def compact_datetime(text: str | None) -> str:
    if not text or text == "unknown":
        return "-"
    try:
        value = datetime.strptime(text, "%Y-%m-%d %H:%M")
        return value.strftime("%m-%d %H:%M")
    except ValueError:
        return str(text)


def reset_credit_text(status: dict | None) -> tuple[str, str]:
    if not status:
        return ("?", C.GRAY)
    if status.get("expired"):
        return ("AUTH EXP", C.RED)
    if status.get("error"):
        return ("ERR", C.YELLOW)
    available = status.get("available")
    if isinstance(available, int) and available > 0:
        remaining = status.get("nearest_remaining_text") or "-"
        compact = remaining.replace("시간", "h").replace("분", "m").replace("일 ", "d")
        return (f"{available}권 {compact}", C.GREEN)
    expiries = status.get("expiries") or []
    if expiries:
        return (f"?권 {compact_datetime(expiries[0])}", C.YELLOW)
    return ("-", C.GRAY)


def duplicate_account_id_prefixes(accounts: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for name in accounts:
        prefix = account_id_prefix(name)
        if prefix and prefix != "-":
            groups.setdefault(prefix, []).append(name)
    return {prefix: names for prefix, names in groups.items() if len(names) > 1}


def render_row(columns: list[tuple[str, int, str]]) -> str:
    cells = []
    for value, width, align in columns:
        cells.append(format_cell(str(value), width, align))
    return "  " + " ".join(cells).rstrip()


def render_colored_row(columns: list[tuple[str, int, str, str | None]]) -> str:
    cells = []
    for value, width, align, color in columns:
        cell = format_cell(str(value), width, align)
        cells.append(colored(cell, color) if color else cell)
    return "  " + " ".join(cells).rstrip()


def render_rule(width: int) -> str:
    return colored("  " + "-" * max(10, width - 4), C.GRAY)


def render_banner():
    width = terminal_width()
    inner = max(24, min(width - 4, 96))
    title = "Codex Multi-Account Manager"
    print(colored("  " + "=" * inner, C.CYAN))
    print(colored("  " + title.center(inner), C.CYAN, C.BOLD))
    print(colored("  " + "=" * inner, C.CYAN))


def read_tui_input(prompt: str, default: str = "") -> str:
    try:
        return input(prompt)
    except EOFError:
        print()
        return default


def fetch_quota_rows(accounts: list[str]) -> dict[str, dict | None]:
    def load_one(account_name: str) -> tuple[str, dict | None]:
        auth = read_auth(account_name)
        if not auth:
            return account_name, None
        return account_name, fetch_quota(auth, account_name=account_name)

    rows: dict[str, dict | None] = {}
    workers = max(1, min(4, len(accounts)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(load_one, name): name for name in accounts}
        for future in as_completed(futures):
            name = futures[future]
            try:
                account_name, data = future.result()
                rows[account_name] = data
            except Exception as exc:
                rows[name] = {"ok": False, "error": type(exc).__name__}
    return rows


def fetch_reset_credit_rows(accounts: list[str]) -> dict[str, dict | None]:
    def load_one(account_name: str) -> tuple[str, dict | None]:
        auth = read_auth(account_name)
        if not auth:
            return account_name, None
        return account_name, fetch_reset_credits(auth, account_name=account_name)

    rows: dict[str, dict | None] = {}
    workers = max(1, min(4, len(accounts)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(load_one, name): name for name in accounts}
        for future in as_completed(futures):
            name = futures[future]
            try:
                account_name, data = future.result()
                rows[account_name] = data
            except Exception as exc:
                rows[name] = {"ok": False, "error": type(exc).__name__}
    return rows


def fetch_account_remote_rows(
    accounts: list[str],
    *,
    auth_overrides: dict[str, dict] | None = None,
    quota_overrides: dict[str, dict] | None = None,
) -> tuple[dict[str, dict | None], dict[str, dict | None]]:
    """Fetch quota and reset-credit data together so status does not wait twice."""
    quotas: dict[str, dict | None] = {}
    reset_credits: dict[str, dict | None] = {}
    auth_overrides = auth_overrides or {}
    quota_overrides = quota_overrides or {}

    def load_one(kind: str, account_name: str):
        auth = auth_overrides.get(account_name) or read_auth(account_name)
        if not auth:
            return kind, account_name, None
        if kind == "quota":
            if account_name in quota_overrides:
                return kind, account_name, quota_overrides[account_name]
            return kind, account_name, fetch_quota(auth, account_name=account_name)
        return kind, account_name, fetch_reset_credits(auth, account_name=account_name)

    workers = max(1, min(8, len(accounts) * 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(load_one, kind, name): (kind, name)
            for name in accounts
            for kind in ("quota", "reset")
        }
        for future in as_completed(futures):
            kind, name = futures[future]
            target = quotas if kind == "quota" else reset_credits
            try:
                _kind, account_name, data = future.result()
                target[account_name] = data
            except Exception as exc:
                target[name] = {"ok": False, "error": type(exc).__name__}
    return quotas, reset_credits


def show_reset_credit_expiries(accounts: list[str] | None = None, *, show_all: bool = True):
    if accounts is None:
        accounts = list_accounts()
    if not accounts:
        print(f"  {colored('등록된 계정 없음.', C.GRAY)}")
        return

    print(f"  {colored('초기화권 만료일 조회 중...', C.GRAY)}", end="\r")
    sys.stdout.flush()
    rows = fetch_reset_credit_rows(accounts)
    width = terminal_width()
    print(" " * min(40, width - 1), end="\r")

    acc_w = max(18, min(width - 57, 38))
    header = [("#", 3, "right"), ("계정", acc_w, "left"), ("ID", 8, "left"),
              ("보유", 4, "right"), ("사용기한(로컬)", 16, "left"),
              ("남은 시간", 18, "left"), ("상태", 10, "left")]
    print(render_rule(width))
    print(colored(render_row(header), C.BOLD))
    print(render_rule(width))

    shown = 0
    credit_count = 0
    expired_count = 0
    errors = 0
    for i, name in enumerate(accounts, 1):
        data = rows.get(name)
        status = format_reset_credit_status(data) if data else {
            "available": None, "total_earned": None, "expiries": [], "expired": False, "error": "no_auth"
        }
        available = status.get("available")
        usable_credits = [item for item in status.get("credits", []) if item.get("is_available")]
        has_credit = (isinstance(available, int) and available > 0) or bool(usable_credits)
        if has_credit:
            credit_count += 1
        if status.get("expired"):
            expired_count += 1
        elif status.get("error"):
            errors += 1
        if not show_all and not has_credit:
            continue

        shown += 1
        expiry_text = status.get("nearest_expiry_local") or "-"
        remaining_text = status.get("nearest_remaining_text") or "-"
        state_text = "사용 가능" if has_credit else ("인증 만료" if status.get("expired") else (status.get("error") or "없음"))
        count_text = str(available) if isinstance(available, int) else ("?" if has_credit else "0")
        count_color = C.GREEN if has_credit else C.GRAY
        row = [
            (str(i), 3, "right"),
            (name, acc_w, "left"),
            (account_id_prefix(name), 8, "left"),
            (count_text, 4, "right"),
            (expiry_text, 16, "left"),
            (remaining_text, 18, "left"),
            (state_text, 10, "left"),
        ]
        line = render_row(row)
        if has_credit:
            line = colored(line, count_color)
        else:
            line = colored(line, C.GRAY)
        print(line)
        for credit_index, credit in enumerate(usable_credits[1:], 2):
            print(colored(render_row([
                ("", 3, "right"), (f"└ 초기화권 {credit_index}", acc_w, "left"),
                ("", 8, "left"), ("", 4, "right"),
                (credit.get("expires_at") or "-", 16, "left"),
                (credit.get("remaining_text") or "-", 18, "left"),
                ("사용 가능", 10, "left"),
            ]), C.GREEN))

    if shown == 0:
        print(f"  {colored('초기화권 보유 계정 없음.', C.GRAY)}")
    print(render_rule(width))
    if show_all:
        suffix = f"  표시: 전체 {shown}개 · 초기화권 보유 {credit_count}개"
    else:
        suffix = f"  표시: 초기화권 보유 계정 {credit_count}개"
    if expired_count:
        suffix += f" · 토큰 만료 {expired_count}개"
    if errors:
        suffix += f" · 조회 실패 {errors}개"
    print(colored(suffix, C.GRAY))


def show_table(accounts: list[str] | None = None):
    if accounts is None:
        accounts = list_accounts()
    if not accounts:
        print(f"  {colored('등록된 계정 없음.', C.GRAY)}")
        return

    app_context = get_live_app_context(accounts)
    active = app_context["active"]
    cli_active = get_cli_accounts()

    print(f"  {colored('계정/초기화권 정보 조회 중...', C.GRAY)}", end="\r")
    sys.stdout.flush()

    auth_overrides = {}
    quota_overrides = {}
    if active and app_context["auth"]:
        auth_overrides[active] = app_context["auth"]
        quota_overrides[active] = app_context["quota"]
    quotas, reset_credits = fetch_account_remote_rows(
        accounts,
        auth_overrides=auth_overrides,
        quota_overrides=quota_overrides,
    )

    width = terminal_width()

    # Clear loading message
    print(" " * min(40, width - 1), end="\r")

    # Each account is rendered on two aligned rows:
    #   line 1: decision data (identity, health, quota, reset credit, subscription)
    #   line 2: metadata and reset timers using the same account-width spacer.
    acc_w = max(18, min(36, width - 76))

    header = [("#", 3, "right"), ("AC", 2, "left"), ("계정", acc_w, "left"),
              ("ID", 8, "left"), ("플랜", 6, "left"), ("상태", 4, "left"),
              ("한도1", 5, "right"), ("한도2", 5, "right"), ("초기화권", 14, "left"),
              ("구독", 10, "left")]
    print(render_rule(width))
    print(colored(render_row(header), C.BOLD))
    print(render_rule(width))

    for i, name in enumerate(accounts, 1):
        auth = read_auth(name)
        data = quotas.get(name) if auth else None
        q = format_quota(data) if data else format_quota({"ok": False, "error": "no_auth"})
        reset_status = format_reset_credit_status(reset_credits.get(name)) if auth else {
            "available": None, "total_earned": None, "expiries": [], "expired": False, "error": "no_auth"
        }

        markers = ""
        if name == active:
            markers += "A"
        if name in cli_active:
            markers += "C"
        markers = markers or "-"

        account_id = account_id_prefix(name)
        phone = get_account_phone(name) or "-"
        expired = q["expired"]
        plan = (q.get("plan") or "?")[:6]
        status = status_text(q)
        quota1_label = q.get("quota1_label") or "한도1"
        quota2_label = q.get("quota2_label") or q.get("long_label") or "한도2"
        long_remain = q.get("long_remain", q.get("wk_remain"))
        five_text, five_reset_text = quota_slot_text(
            quota1_label, q["5h_remain"], q["5h_reset"], expired
        )
        long_text, long_reset_text = quota_slot_text(
            quota2_label, long_remain, q.get("long_reset") or q.get("wk_reset"), expired
        )
        expiry_disp, exp_col = expiry_color(get_expiry(name))
        cancel = get_cancel_renew(name)
        credit_disp, credit_col = reset_credit_text(reset_status)

        status_col = C.GREEN if status == "OK" else (C.RED if status in ("ERR", "EXP") else C.GRAY)
        five_col = quota_color(q["5h_remain"]) if isinstance(q["5h_remain"], (int, float)) else C.GRAY
        long_col = quota_color(long_remain) if isinstance(long_remain, (int, float)) else C.GRAY
        marker_col = (C.GREEN + C.BOLD) if "A" in markers else (C.CYAN if "C" in markers else None)
        name_col = (C.CYAN + C.BOLD) if name == active else None

        print(render_colored_row([
            (str(i), 3, "right", None),
            (markers, 2, "left", marker_col),
            (name, acc_w, "left", name_col),
            (account_id, 8, "left", C.GRAY),
            (plan, 6, "left", None),
            (status, 4, "left", status_col),
            (five_text, 5, "right", five_col),
            (long_text, 5, "right", long_col),
            (credit_disp, 14, "left", credit_col),
            (expiry_disp, 10, "left", exp_col),
        ]))

        print(render_colored_row([
            ("", 3, "right", None),
            ("", 2, "left", None),
            (f"전화 {phone}", acc_w, "left", C.GRAY),
            ("", 8, "left", None),
            ("리셋", 6, "left", C.GRAY),
            ("", 4, "left", None),
            (five_reset_text, 14, "left", C.GRAY),
            (long_reset_text, 15, "left", C.GRAY),
            (f"해지 {cancel}", 7, "left", C.GRAY),
            ("", 10, "left", None),
        ]))

    print(render_rule(width))
    print(f"  {colored('A', C.GREEN, C.BOLD)} App active   {colored('C', C.CYAN)} CLI running   width={width}")
    app_quota = format_quota(app_context["quota"])
    if active:
        app_index = accounts.index(active) + 1
        app_label, usage = primary_quota_display(app_quota)
        print(
            f"  {colored('APP 실제 토큰', C.GREEN, C.BOLD)}: "
            f"{app_index}번 {active} · {app_label} {usage}"
        )
    elif app_context["auth"]:
        print(
            f"  {colored('!', C.YELLOW)} APP 실제 토큰: 저장 계정과 정확히 연결되지 않음 "
            f"({status_text(app_quota)})"
        )
    duplicate_ids = duplicate_account_id_prefixes(accounts)
    if duplicate_ids:
        brief = "; ".join(f"{prefix}: {len(names)}개" for prefix, names in duplicate_ids.items())
        print(f"  {colored('!', C.YELLOW)} 같은 ID prefix 계정: {brief}  (같은 OpenAI account일 수 있음)")


# === TUI ===

def tui():
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print()
        render_banner()
        print()

        accounts = list_accounts()
        show_table(accounts)

        print()
        # Action menu - always visible, no memorization needed
        print(colored("  무엇을 할까요?", C.WHITE, C.BOLD))
        print()
        if accounts:
            if terminal_width() < 60:
                print(f"    {colored('1-' + str(len(accounts)), C.CYAN)}  계정 선택")
            else:
                print(f"    {colored('1-' + str(len(accounts)), C.CYAN)}  계정 번호를 입력하면 아래 동작을 선택합니다")
            print()
        print(f"    {colored('i', C.GREEN)}    현재 Codex App 로그인 가져오기/갱신")
        print(f"    {colored('a', C.GREEN)}    다른 계정 추가 (기기 코드 로그인)")
        print(f"    {colored('r', C.YELLOW)}    새로고침")
        print(f"    {colored('c', C.CYAN)}    초기화권 상세 조회")
        print(f"    {colored('u', C.YELLOW)}    Codex CLI 업데이트")
        print(f"    {colored('q', C.RED)}    종료")
        print()

        choice = read_tui_input("  > ", "q").strip().lower()

        if choice == "q":
            break
        elif choice == "r":
            continue
        elif choice == "a":
            add_account()
            input("\n  Enter...")
        elif choice == "i":
            import_app_auth()
            input("\n  Enter...")
        elif choice in ("c", "z"):
            show_reset_credit_expiries(accounts)
            input("\n  Enter...")
        elif choice == "u":
            update_codex_cli()
            input("\n  Enter...")
        elif choice.isdigit() and accounts:
            idx = int(choice) - 1
            if 0 <= idx < len(accounts):
                account_action_menu(accounts, idx)
            else:
                print(f"  {colored('잘못된 번호.', C.RED)}")
                time.sleep(1)


def account_action_menu(accounts: list[str], idx: int):
    """Sub-menu after selecting an account number."""
    name = accounts[idx]
    auth = read_auth(name)
    expired = False
    if auth:
        data = fetch_quota(auth, account_name=name)
        expired = not data.get("ok") and data.get("error") == "expired"

    os.system("cls" if os.name == "nt" else "clear")
    print()
    print(f"  선택: {colored(name, C.CYAN, C.BOLD)}")
    phone = get_account_phone(name)
    if phone:
        print(f"  전화: {colored(phone, C.GREEN, C.BOLD)}")
    print(f"  ID:   {colored(account_id_prefix(name), C.GRAY)}")
    if expired:
        print(f"         {colored('⚠ 토큰 만료됨', C.RED, C.BOLD)}")
    print()
    print(colored("  ─────────────────────────────────────────────", C.GRAY))
    print(f"    {colored('c', C.CYAN)}  {colored('CLI', C.CYAN)}    — CLI 실행 (계정별 CODEX_HOME)")
    print(f"    {colored('o', C.GREEN)}  {colored('Open', C.GREEN)}   — 별도 App 실행 (계정별 CODEX_HOME)")
    print(f"    {colored('r', C.GREEN)}  {colored('Restart', C.GREEN)}— 이 계정 App만 종료 후 다시 실행")
    print(f"    {colored('s', C.YELLOW)}  {colored('Switch', C.YELLOW)} — 전역 App 계정 전환 (auth.json 교체)")
    print(f"    {colored('l', C.BLUE)}  {colored('Phone', C.BLUE)}  — 인증 전화번호 기록/삭제")
    print(f"    {colored('u', C.YELLOW)}  {colored('Update', C.YELLOW)} — 토큰 갱신 (재로그인)")
    print(f"    {colored('p', C.MAGENTA)}  {colored('Proxy', C.MAGENTA)} — usage 조회 프록시 설정")
    print(f"    {colored('k', C.CYAN)}  {colored('Credit', C.CYAN)} — 초기화권 만료일 조회")
    print(f"    {colored('e', C.BLUE)}  {colored('Expiry', C.BLUE)} — 구독 만료일 설정")
    print(f"    {colored('x', C.BLUE)}  {colored('Cancel', C.BLUE)} — 구독 연장 해지 여부 설정 (y/n)")
    print(f"    {colored('m', C.MAGENTA)}  {colored('Move', C.MAGENTA)}   — 표시 순서 변경")
    print(f"    {colored('d', C.RED)}  {colored('Delete', C.RED)} — 계정 삭제")
    print()
    print(f"    {colored('b', C.GRAY)}  돌아가기")
    print(colored("  ─────────────────────────────────────────────", C.GRAY))
    print()

    action = read_tui_input("  > ", "b").strip().lower()

    if action == "c":
        launch_account(name)
        input("\n  Enter...")
    elif action == "o":
        launch_app_account(name)
        input("\n  Enter...")
    elif action == "r":
        launch_app_account(name, restart=True)
        input("\n  Enter...")
    elif action in ("s", "a"):
        switch_account(name)
        input("\n  Enter...")
    elif action == "l":
        edit_account_phone(name)
        input("\n  Enter...")
    elif action == "u":
        refresh_account(name)
        input("\n  Enter...")
    elif action == "p":
        usage_proxy_command([name])
        input("\n  Enter...")
    elif action == "k":
        show_reset_credit_expiries([name], show_all=True)
        input("\n  Enter...")
    elif action == "e":
        expiry = get_expiry(name)
        if expiry:
            print(f"  현재: {expiry}")
        date_str = input("  구독 만료일 (YYYY-MM-DD, 빈칸=삭제): ").strip()
        if date_str:
            set_expiry(name, date_str)
            print(f"  {colored('✓', C.GREEN)} 설정됨: {date_str}")
        else:
            meta = load_meta()
            if name in meta:
                meta[name].pop("expiry", None)
                save_meta(meta)
            print(f"  {colored('✓', C.GREEN)} 삭제됨.")
        input("\n  Enter...")
    elif action == "x":
        current_val = get_cancel_renew(name)
        print(f"  현재: {current_val}")
        val = input("  구독 연장 해지 여부 (y/n): ").strip().lower()
        if val in ("y", "n"):
            set_cancel_renew(name, val)
            print(f"  {colored('✓', C.GREEN)} 설정됨: {val}")
        else:
            print(f"  {colored('✗', C.RED)} y 또는 n을 입력하세요.")
        input("\n  Enter...")
    elif action == "m":
        new_pos = input(f"  새 위치 (1-{len(accounts)}): ").strip()
        if new_pos.isdigit() and 1 <= int(new_pos) <= len(accounts):
            new_idx = int(new_pos) - 1
            accounts.pop(idx)
            accounts.insert(new_idx, name)
            save_order(accounts)
            print(f"  {colored('✓', C.GREEN)} 이동됨.")
        input("\n  Enter...")
    elif action == "d":
        confirm = input(f"  {colored('정말 삭제?', C.RED)} (y/n): ").strip().lower()
        if confirm == "y":
            delete_account(name)
            print(f"  {colored('✓', C.GREEN)} 삭제됨.")
        input("\n  Enter...")


# === Codex CLI update ===

def _run_text_command(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"명령을 찾을 수 없음: {args[0]}"
    except subprocess.TimeoutExpired as exc:
        parts = []
        if exc.stdout:
            parts.append(str(exc.stdout).strip())
        if exc.stderr:
            parts.append(str(exc.stderr).strip())
        text = "\n".join(part for part in parts if part)
        suffix = f"\n{text}" if text else ""
        return 124, f"시간 초과: {' '.join(args)}{suffix}"

    parts = []
    if result.stdout:
        parts.append(result.stdout.strip())
    if result.stderr:
        parts.append(result.stderr.strip())
    return result.returncode, "\n".join(part for part in parts if part)


def _npm_executable() -> str | None:
    return shutil.which("npm.cmd") or shutil.which("npm")


def _version_from_text(text: str) -> str | None:
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", text or "")
    return match.group(1) if match else None


def _load_cli_update_state() -> dict:
    try:
        data = json.loads(CLI_UPDATE_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cli_update_state(latest: str) -> None:
    try:
        CLI_UPDATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CLI_UPDATE_STATE_FILE.write_text(
            json.dumps({"checked_at": time.time(), "latest": latest}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def latest_codex_npm_version(*, force: bool = False) -> str | None:
    """Latest published CLI version, cached so launches stay fast."""
    state = _load_cli_update_state()
    cached = state.get("latest") if isinstance(state.get("latest"), str) else None
    checked_at = state.get("checked_at")
    if (
        not force
        and cached
        and isinstance(checked_at, (int, float))
        and 0 <= time.time() - checked_at < CLI_UPDATE_CHECK_INTERVAL_SECONDS
    ):
        return cached
    npm = _npm_executable()
    if not npm:
        return cached
    code, text = _run_text_command([npm, "view", CODEX_NPM_PACKAGE, "version"], timeout=120)
    latest = _version_from_text(text) if code == 0 else None
    if not latest:
        return cached
    _save_cli_update_state(latest)
    return latest


def _install_latest_codex_cli() -> tuple[int, str]:
    npm = _npm_executable()
    if not npm:
        return 127, "npm을 찾을 수 없습니다. Node.js/npm 설치를 확인하세요."
    code, text = _run_text_command(
        [npm, "install", "-g", f"{CODEX_NPM_PACKAGE}@latest"],
        timeout=900,
    )
    _CODEX_CLI_CACHE.clear()
    return code, text


def ensure_codex_cli_current(*, quiet: bool = False) -> str:
    """Return the codex CLI to run, upgrading it first when it is outdated."""
    command = _codex_command()
    if os.environ.get("CM_CODEX_COMMAND", "").strip():
        return command
    if _env_flag_disabled("CM_CLI_AUTO_UPDATE"):
        return command

    current_text = _codex_command_version()
    current_key = _version_key(current_text)
    latest = latest_codex_npm_version()
    latest_key = _version_key(latest)
    if latest_key is None or (current_key is not None and current_key >= latest_key):
        return command

    current_label = _version_from_text(current_text or "") or "확인 실패"
    if not quiet:
        print(f"  {colored('◆', C.CYAN)} Codex CLI 업데이트: {current_label} → {latest}")
    code, text = _install_latest_codex_cli()
    if code != 0 and not quiet:
        print(f"  {colored('!', C.YELLOW)} 업데이트 실패(exit={code}). 현재 버전으로 실행합니다.")
        for line in (text or "").splitlines()[-3:]:
            print(f"    {line}")
    command = _codex_command()
    if not quiet:
        updated = _version_from_text(_codex_command_version() or "") or "확인 실패"
        print(f"  {colored('✓', C.GREEN)} 사용 버전: {updated} ({command})")
    return command


def update_codex_cli(force: bool = False):
    """Install the latest global Codex CLI package and verify the result."""
    print()
    print(f"  {colored('◆ Codex CLI 업데이트', C.CYAN, C.BOLD)}")

    _CODEX_CLI_CACHE.clear()
    before_command = _codex_command()
    before_text = _codex_command_version()
    before_key = _version_key(before_text)
    if before_text:
        print(f"  현재: {before_text}  ({before_command})")
    else:
        print(f"  {colored('!', C.YELLOW)} 현재 버전 확인 실패: {before_command}")

    latest = latest_codex_npm_version(force=True)
    if latest:
        print(f"  npm 최신: {latest}")
    else:
        print(f"  {colored('!', C.YELLOW)} npm 최신 버전 확인 실패")

    latest_key = _version_key(latest)
    if not force and latest_key is not None and before_key is not None and before_key >= latest_key:
        print(f"  {colored('✓', C.GREEN)} 이미 최신입니다: {_version_from_text(before_text or '')}")
        return

    print(f"  실행: npm install -g {CODEX_NPM_PACKAGE}@latest")
    install_code, install_text = _install_latest_codex_cli()
    if install_text:
        for line in install_text.splitlines():
            print(f"  {line}")
    if install_code != 0:
        print(f"  {colored('✗', C.RED)} 업데이트 실패(exit={install_code})")
        if "EBUSY" in install_text or "EPERM" in install_text:
            print("  실행 중인 Codex/Codex App을 닫은 뒤 다시 실행하세요. 재설치가 필요하면 cm update --force를 사용할 수 있습니다.")
        return

    after_command = _codex_command()
    after_text = _codex_command_version()
    if after_text:
        print(f"  {colored('✓', C.GREEN)} 업데이트 완료: {after_text}")
        print(f"  cm cli가 사용할 실행 파일: {after_command}")
    else:
        print(f"  {colored('!', C.YELLOW)} 설치 후 버전 확인 실패: {after_command}")


# Legacy read-only OCX status helpers. Provider lifecycle remains owned by OCX.

OPENCODEX_NPM_PACKAGE = "@bitkyc08/opencodex"
OPENCODEX_HEALTH_URL = "http://127.0.0.1:10100/healthz"


def _npm_latest_version(package: str) -> str | None:
    npm = _npm_executable()
    if not npm:
        return None
    code, text = _run_text_command([npm, "view", package, "version"], timeout=120)
    return _version_from_text(text) if code == 0 else None


def _git_text(repo: Path, args: list[str]) -> str | None:
    git = shutil.which("git")
    if not git or not repo.is_dir():
        return None
    code, text = _run_text_command([git, "-C", str(repo)] + args, timeout=60)
    return text if code == 0 else None


def _behind(installed: str | None, latest: str | None) -> bool:
    """Whether latest is strictly newer, so an update can never downgrade."""
    latest_key = _version_key(latest)
    if latest_key is None:
        return False
    installed_key = _version_key(installed)
    return installed_key is None or latest_key > installed_key


def stack_status() -> dict:
    codex_installed = _version_from_text(_codex_command_version() or "")
    codex_latest = latest_codex_npm_version(force=True)
    ocx = shutil.which("ocx")
    ocx_installed = None
    if ocx:
        code, text = _run_text_command([ocx, "--version"], timeout=30)
        ocx_installed = _version_from_text(text) if code == 0 else None
    ocx_latest = _npm_latest_version(OPENCODEX_NPM_PACKAGE)

    proxy = None
    try:
        with urlopen(OPENCODEX_HEALTH_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        proxy = payload.get("version") if isinstance(payload, dict) else None
    except (URLError, HTTPError, OSError, ValueError, json.JSONDecodeError):
        proxy = None

    return {
        "codex": {"installed": codex_installed, "latest": codex_latest,
                  "behind": _behind(codex_installed, codex_latest),
                  "path": _codex_command()},
        "opencodex": {"installed": ocx_installed, "latest": ocx_latest,
                      "behind": _behind(ocx_installed, ocx_latest),
                      "proxy_version": proxy,
                      "default_provider": proxy_default_provider(),
                      "account_mode": proxy_codex_account_mode()},
    }


KIRO_DESKTOP_CREDS_FILE = Path.home() / ".aws" / "sso" / "cache" / "kiro-auth-token.json"
KIRO_CLI_DB_FILE = (
    Path.home() / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3"
)


def _token_fingerprint(token: str | None) -> str | None:
    if not isinstance(token, str) or not token.strip():
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _kiro_desktop_token() -> str | None:
    try:
        data = json.loads(KIRO_DESKTOP_CREDS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("accessToken") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _kiro_cli_token() -> str | None:
    if not KIRO_CLI_DB_FILE.is_file():
        return None
    try:
        import sqlite3

        with sqlite3.connect(f"file:{KIRO_CLI_DB_FILE}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT value FROM auth_kv WHERE key LIKE '%:token'").fetchall()
    except Exception:
        return None
    for (raw,) in rows:
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        value = data.get("access_token") or data.get("accessToken") if isinstance(data, dict) else None
        if isinstance(value, str):
            return value
    return None


def kiro_credential_source() -> str:
    """Which Kiro login the proxy is actually using.

    Two Kiro logins can coexist under different accounts: the Desktop app and
    kiro-cli. Only tokens are compared (by digest, never printed), because the
    entitlement difference between them is what decides whether Opus and
    1M-context Sonnet are available at all.
    """
    try:
        store = json.loads((OPENCODEX_CONFIG_FILE.parent / "auth.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    kiro = store.get("kiro") if isinstance(store, dict) else None
    active = _token_fingerprint(_find_first_kiro_access_token(kiro))
    if active is None:
        return "none"
    if active == _token_fingerprint(_kiro_desktop_token()):
        return "desktop"
    if active == _token_fingerprint(_kiro_cli_token()):
        return "kiro-cli"
    return "detached"


def _find_first_kiro_access_token(store) -> str | None:
    """Locate the kiro provider access token in opencodex's auth store."""
    if isinstance(store, dict):
        for key, value in store.items():
            if key in {"access_token", "accessToken", "access"} and isinstance(value, str):
                return value
            found = _find_first_kiro_access_token(value)
            if found:
                return found
    elif isinstance(store, list):
        for item in store:
            found = _find_first_kiro_access_token(item)
            if found:
                return found
    return None


def _port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) == 0


def _stack_line(label: str, installed, latest, behind: bool) -> str:
    mark = colored("!", C.YELLOW) if behind else colored("✓", C.GREEN)
    # The arrow only appears for a real upgrade; a local build ahead of npm is
    # normal for the App-embedded CLI and must not read as "update pending".
    if behind:
        return f"  {mark} {label:<13} {installed or '?'} → {latest}  업데이트 있음"
    published = f" (npm {latest})" if latest and latest != installed else ""
    return f"  {mark} {label:<13} {installed or '?'}{published}  최신"


def show_stack_status():
    print()
    print(f"  {colored('◆ Codex/Kiro 스택 상태', C.CYAN, C.BOLD)}")
    status = stack_status()
    codex = status["codex"]
    ocx = status["opencodex"]

    print(_stack_line("codex CLI", codex["installed"], codex["latest"], codex["behind"]))
    print(f"      실행 파일 : {codex['path']}")
    print(_stack_line("opencodex", ocx["installed"], ocx["latest"], ocx["behind"]))
    proxy_state = f"v{ocx['proxy_version']}" if ocx["proxy_version"] else colored("응답 없음", C.RED)
    print(f"      프록시    : {proxy_state}  ·  대시보드 http://127.0.0.1:10100/ (ocx gui)")
    mode = ocx["account_mode"]
    mode_mark = colored("✓", C.GREEN) if mode in {"direct", "pool"} else colored("!", C.YELLOW)
    print(
        f"      라우팅    : provider {ocx['default_provider'] or '?'} · "
        f"codex account-mode {mode or '?'} {mode_mark}"
    )

    source = kiro_credential_source()
    source_label = {
        "desktop": (colored("✓", C.GREEN), "Kiro Desktop 로그인 (전체 모델)"),
        "kiro-cli": (colored("!", C.YELLOW), "kiro-cli 로그인 — Opus/1M Sonnet 없음. "
                                            "KIRO_CREDS_FILE 설정 후 ocx login kiro"),
        "detached": (colored("!", C.YELLOW), "어느 로컬 로그인과도 일치하지 않음(자체 갱신됨)"),
        "none": (colored("!", C.YELLOW), "kiro 로그인 없음 — ocx login kiro"),
    }.get(source, (colored("?", C.GRAY), "확인 불가"))
    print(f"  {source_label[0]} {'kiro 자격':<13} {source_label[1]}")

    if codex["behind"] or ocx["behind"]:
        print()
        print("  업데이트는 각 공식 CLI에서 수행하세요: cm update / ocx update")
    return status


def apply_stack_update():
    print("  cm은 더 이상 provider 스택을 관리하지 않습니다. cm update 또는 ocx update를 사용하세요.")


def stack_command(args: list[str]):
    action = (args[0].lower() if args else "status")
    if action in {"status", "check", ""}:
        show_stack_status()
        return
    if action in {"apply", "update"}:
        apply_stack_update()
        return
    print("  사용법: cm stack [status|apply]")


# === CLI Entry ===

# === Unified command registry (single source of truth) ===
# Each entry drives the `cm` CLI dispatch, the generated help text, AND the
# Telegram remote shell. Change a command here and it propagates everywhere.
#   remote: "ok"    runnable remotely as-is (e.g. status, help)
#           "arg"   runnable remotely but requires argument(s) (remote_min)
#           "local" PC-only (interactive prompt or launches a local GUI)

def _cmd_status(rest):
    if any(arg in ("--json", "-j") for arg in rest):
        print(json.dumps(status_payload(), ensure_ascii=False, indent=2))
        return
    show_table()


def status_payload() -> dict:
    """Return the same account state as the table without secrets or ANSI text."""
    ensure_dirs()
    accounts = list_accounts()
    app_context = get_live_app_context(accounts)
    active = app_context["active"]
    cli_active = get_cli_accounts()
    auth_overrides = {active: app_context["auth"]} if active and app_context["auth"] else {}
    quota_overrides = {active: app_context["quota"]} if active else {}
    quotas, reset_credits = fetch_account_remote_rows(
        accounts,
        auth_overrides=auth_overrides,
        quota_overrides=quota_overrides,
    )

    rows = []
    for index, name in enumerate(accounts, 1):
        raw = quotas.get(name)
        quota = format_quota(raw) if raw else format_quota({"ok": False, "error": "no_auth"})
        credit = format_reset_credit_status(reset_credits.get(name) or {"ok": False, "error": "no_auth"})
        rows.append({
            "index": index,
            "account": name,
            "id_prefix": (read_auth(name) or {}).get("tokens", {}).get("account_id", "")[:8] or None,
            "is_app_active": name == active,
            "is_cli_active": name in cli_active,
            "plan": quota.get("plan"),
            "expired": quota.get("expired", False),
            "error": quota.get("error"),
            "quota": {
                "short_remaining_percent": quota.get("5h_remain"),
                "short_reset": quota.get("5h_reset"),
                "short_label": quota.get("quota1_label"),
                "long_remaining_percent": quota.get("long_remain"),
                "long_reset": quota.get("long_reset"),
                "long_label": quota.get("long_label"),
            },
            "reset_credits": {
                "available": credit.get("available"),
                "total_earned": credit.get("total_earned"),
                "nearest_expiry_local": credit.get("nearest_expiry_local"),
                "nearest_remaining_text": credit.get("nearest_remaining_text"),
            },
            "subscription_expiry": get_expiry(name),
        })

    return {
        "ok": True,
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "active_account": active,
        "account_count": len(accounts),
        "accounts": rows,
    }


def _cmd_switch(rest):
    switch_account(rest[0] if rest else None)


def _cmd_phone(rest):
    phone_command(rest)


def _cmd_proxy(rest):
    usage_proxy_command(rest)


def _cmd_quota_debug(rest):
    quota_debug_command(rest)


def _cmd_cli(rest):
    target, codex_args = split_selector_args(rest)
    launch_account(target, codex_args)


APP_RESTART_FLAGS = {"--restart", "-r"}


def _cmd_app(rest):
    target, app_args = split_selector_args(rest)
    restart = any(arg in APP_RESTART_FLAGS for arg in app_args)
    app_args = [arg for arg in app_args if arg not in APP_RESTART_FLAGS]
    launch_app_account(target, app_args, restart=restart)


def _cmd_app_dry(rest):
    target, app_args = split_selector_args(rest)
    launch_app_account(target, app_args, dry_run=True)


def current_calling_app_account(accounts: list[str] | None = None) -> str | None:
    """Resolve the account of the App/session that invoked cm.

    An isolated App exports its own CODEX_HOME. The default App uses
    ``~/.codex``. Token matching is preferred so duplicate account IDs do not
    make a fixed "main" account necessary.
    """
    names = accounts if accounts is not None else list_accounts()
    inherited = Path(INHERITED_CODEX_HOME).expanduser() if INHERITED_CODEX_HOME else APP_CODEX_HOME
    auth_path = inherited / "auth.json"
    auth = _read_auth_file(auth_path) if auth_path.exists() else None
    if not _has_usable_chatgpt_auth(auth):
        auth_path = APP_CODEX_HOME / "auth.json"
        auth = _read_auth_file(auth_path) if auth_path.exists() else None
    return get_active_account(live_auth=auth, accounts=names)


def _remote_backend():
    if sys.platform == "darwin":
        import codex_macos_ssh

        return codex_macos_ssh
    if os.name == "nt":
        import codex_wsl_ssh

        return codex_wsl_ssh
    raise RuntimeError(f"GPT App SSH remote is unsupported on {sys.platform}")


def _remote_status():
    return _remote_backend().status(MANAGER_DIR)


def show_remote_status() -> dict:
    backend = _remote_backend()
    current = backend.status(MANAGER_DIR)
    details = (
        backend.connection_details(MANAGER_DIR)
        if hasattr(backend, "connection_details")
        else {
            "display_name": "내 노트북 공통",
            "host": f"{os.environ.get('USERNAME') or Path.home().name}@127.0.0.1",
            "port": int(current.get("port") or 2222),
            "identity_file": str(Path.home() / ".ssh" / "id_ed25519_codex_local"),
        }
    )
    state = "ON" if current.get("ssh_active") else "OFF"
    target = current.get("target_account") or "-"
    print(f"\n  {colored('◆ GPT 계정 원격', C.CYAN, C.BOLD)}")
    print(f"  SSH       : {state}")
    print(f"  대상      : {target}")
    print(f"  원격 서버 : {'실행 중' if current.get('ssh_active') else '미실행'}")
    print(f"  대상 App  : {'별도 실행 중' if current.get('target_app_running') else '실행 안 함(정상)'}")
    print(f"  연결 이름 : {details['display_name']}")
    print(f"  호스트    : {details['host']}")
    print(f"  포트      : {details['port']}")
    print(f"  인증 키   : {details['identity_file']}")
    return current


def start_account_remote(selector: str | None = None, *, force_restart: bool = False):
    accounts = list_accounts()
    if not accounts:
        print("  등록된 계정 없음.")
        return None
    current_account = current_calling_app_account(accounts)
    if selector is None:
        show_table(accounts)
        selector = input("\n  원격으로 연결할 계정: ").strip()
    target = resolve_account_selector(selector, accounts)
    if target is None:
        return None
    if current_account and target == current_account:
        print(f"  {colored('!', C.YELLOW)} 현재 App과 같은 계정입니다: {target}")
        print("  다른 계정을 선택하세요.")
        return None

    runtime = find_codex_runtime_exe()
    if runtime is None:
        print(f"  {colored('✗', C.RED)} ChatGPT/Codex App의 내장 Codex 실행 파일을 찾지 못했습니다.")
        return None
    try:
        home = setup_isolated_home(target)
    except Exception as exc:
        print(f"  {colored('✗', C.RED)} 대상 계정 홈 준비 실패: {exc}")
        return None

    backend = _remote_backend()
    current_remote = backend.status(MANAGER_DIR)
    if current_remote.get("ssh_active") and current_remote.get("target_account") == target:
        if not force_restart:
            print(f"  {colored('✓', C.GREEN)} 이미 이 계정의 원격 서버가 실행 중입니다: {target}")
            return show_remote_status()
        backend.stop(MANAGER_DIR, reason="restart-before-thread-sync")

    activity = thread_home_activity(target, home)
    if activity["active"]:
        print(f"  {colored('!', C.YELLOW)} 대상 계정 홈이 다른 App/CLI/app-server에서 사용 중입니다.")
        print("  실행 중인 세션은 종료하지 않았습니다. 해당 작업을 마친 뒤 다시 원격 연결하세요.")
        return None

    synced = sync_thread_index(target, home=home, active=False)
    if synced is None:
        return None

    try:
        if sys.platform == "darwin":
            result = backend.start_for_account(
                MANAGER_DIR,
                account_name=target,
                account_key=stable_account_key(target),
                native_home=home,
                native_codex_exe=runtime,
                app_pid=None,
                force_restart=force_restart,
            )
        else:
            current_main = current_account or get_active_account()
            backend.save_config(
                MANAGER_DIR,
                {
                    "enabled": True,
                    "main_account": current_main,
                    "execution_mode": "windows-native",
                },
            )
            result = backend.start_for_account(
                MANAGER_DIR,
                account_name=target,
                account_key=stable_account_key(target),
                auth_path=get_auth_path(target),
                app_home=APP_CODEX_HOME,
                native_home=home,
                native_codex_exe=runtime,
                app_pid=None,
                force_restart=force_restart,
            )
    except Exception as exc:
        print(f"  {colored('✗', C.RED)} SSH 원격 시작 실패: {exc}")
        return None

    print()
    print(f"  {colored('✓', C.GREEN, C.BOLD)} 원격 대상 준비 완료")
    print(f"  현재 App : {current_account or '자동 판별 불가'}")
    print(f"  원격 계정 : {target}")
    print("  대상 네이티브 App은 중복 app-server 방지를 위해 별도로 열지 않았습니다.")
    show_remote_status()
    print("  현재 App의 '내 노트북 공통' SSH 스위치를 켜면 이 계정으로 연결됩니다.")
    return result


def remote_command(args: list[str]):
    action = args[0].lower() if args else "status"
    if action in {"status", "show"}:
        return show_remote_status()
    if action in {"stop", "off", "shutdown"}:
        result = _remote_backend().stop(MANAGER_DIR, reason="manual")
        print(f"  {colored('✓', C.GREEN)} GPT 계정 원격 SSH를 종료했습니다.")
        return result
    if action in {"restart", "retry"}:
        selector = args[1] if len(args) > 1 else _remote_status().get("target_account")
        return start_account_remote(selector, force_restart=True)
    if action in {"start", "on", "connect"}:
        selector = args[1] if len(args) > 1 else None
        return start_account_remote(selector)
    return start_account_remote(args[0])


def _cmd_remote(rest):
    remote_command(rest)


def threads_command(args: list[str]):
    action = args[0].lower() if args else "status"
    force = "--force" in args
    values = [value for value in args[1:] if not value.startswith("--")]
    accounts = list_accounts()
    if action in {"status", "show"}:
        print(f"\n  {colored('◆ 로컬 스레드 색인', C.CYAN, C.BOLD)}")
        for name in accounts:
            home = setup_isolated_home(name)
            info = codex_thread_index.status(
                MANAGER_DIR, account_key=stable_account_key(name), home=home
            )
            activity = thread_home_activity(name, home)
            state = "실행 중" if activity["active"] else ("최신" if info["up_to_date"] else "동기화 필요")
            print(
                f"  {name:<28} {info['thread_count']:>4}개  {state:<10} "
                f"원본 {info['source']['files']}개"
            )
        print("  이 명령과 색인 동기화는 모델/API 토큰을 사용하지 않습니다.")
        return None
    if action not in {"sync", "repair", "refresh"}:
        print("  사용법: cm threads status | sync <계정|all> [--force]")
        return None
    selector = values[0] if values else "all"
    targets = accounts if selector.lower() == "all" else []
    if not targets:
        resolved = resolve_account_selector(selector, accounts)
        if resolved is None:
            return None
        targets = [resolved]
    results = []
    for name in targets:
        result = sync_thread_index(name, force=force)
        if result is not None:
            results.append(result)
    return results


def _cmd_threads(rest):
    threads_command(rest)


def _cmd_add(rest):
    use_browser = "--browser" in rest
    add_account(
        use_browser=use_browser,
        persistent=not use_browser and "--once" not in rest,
    )


def _cmd_import_app(rest):
    dry_run = "--dry-run" in rest
    values = [arg for arg in rest if not arg.startswith("--")]
    import_app_auth(values[0] if values else None, dry_run=dry_run)


def _cmd_refresh(rest):
    use_browser = "--browser" in rest
    values = [arg for arg in rest if not arg.startswith("--")]
    accounts = list_accounts()
    if not values:
        show_table(accounts)
        selector = input("\n  갱신할 계정: ").strip()
    else:
        selector = values[0]
    target = resolve_account_selector(selector, accounts)
    if target:
        refresh_account(
            target,
            use_browser=use_browser,
            persistent=not use_browser and "--once" not in rest,
        )


_BASE_URL_RE = re.compile(r'^\s*(?:openai_base_url|base_url)\s*=\s*"([^"]+)"', re.MULTILINE)
OFFICIAL_API_HOSTS = ("openai.com", "chatgpt.com")


def is_ocx_routing_url(value: str) -> bool:
    """Return whether a configured model URL is the actual local OCX route."""
    try:
        candidate = urlsplit(value)
        expected = urlsplit(OPENCODEX_HEALTH_URL)
    except ValueError:
        return False
    return (
        candidate.scheme == expected.scheme
        and candidate.hostname == expected.hostname
        and candidate.port == expected.port
        and candidate.path.rstrip("/") == "/v1"
    )


def shared_config_conflicts(target: str | None = None) -> dict:
    """Find config.toml settings that defeat per-account isolation.

    An external ``openai_base_url`` sends every account's model traffic through
    one proxy. Whether that proxy forwards the caller's token or substitutes an
    account of its own is outside cm's control, so the limits a CLI displays on
    that path cannot be trusted as this account's limits.
    """
    config_path = APP_CODEX_HOME / "config.toml"
    if target:
        account_config = HOMES_DIR / stable_account_key(target) / "config.toml"
        if account_config.exists():
            config_path = account_config
    result: dict = {
        "path": config_path,
        "external_base_urls": [],
        "pinned_accounts": [],
        "pinned_keys": [],
    }
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return result

    for value in _BASE_URL_RE.findall(text):
        if not any(host in value for host in OFFICIAL_API_HOSTS):
            if value not in result["external_base_urls"]:
                result["external_base_urls"].append(value)

    pattern = re.escape(str(HOMES_DIR)) + r"[\\/]([A-Za-z0-9_.\-]+)"
    keys = {match.group(1) for match in re.finditer(pattern, text)}
    target_key = stable_account_key(target) if target else None
    foreign_keys = sorted(key for key in keys if key != target_key)
    result["pinned_keys"] = foreign_keys
    key_to_name = {stable_account_key(name): name for name in list_accounts()}
    result["pinned_accounts"] = [key_to_name.get(key, key) for key in foreign_keys]
    return result


def warn_shared_config_conflicts(target: str) -> None:
    """Print isolation warnings so a launch never looks cleaner than it is."""
    info = shared_config_conflicts(target)
    if not info["external_base_urls"]:
        return
    for value in info["external_base_urls"]:
        if not is_ocx_routing_url(value):
            print(
                f"  {colored('!', C.YELLOW)} 모델 트래픽 경유: {value} "
                "(OCX가 아닌 외부 로컬 게이트웨이)"
            )
            print("    어떤 계정으로 업스트림에 연결하는지 cm이 보장하지 않습니다.")
            continue
        mode = proxy_codex_account_mode()
        if mode == "direct":
            print(
                f"  {colored('✓', C.GREEN)} 모델 트래픽 경유: {value} "
                "(direct — 이 계정 자격 그대로 사용)"
            )
            continue
        if mode == "pool":
            print(
                f"  {colored('✓', C.GREEN)} 모델 트래픽 경유: {value} "
                "(OCX pool — 새 작업은 OCX 선택 계정 사용)"
            )
            print(
                "    실행 중인 작업은 시작할 때의 계정을 유지합니다. "
                f"확인/전환: {colored('ocx account current openai', C.CYAN)} · "
                f"{colored('ocx account use openai <id>', C.CYAN)}"
            )
            continue
        print(
            f"  {colored('!', C.YELLOW)} config.toml이 모델 트래픽을 외부 엔드포인트로 "
            f"보냅니다: {value}"
        )
        print("    그 프록시가 어떤 계정으로 업스트림에 연결하는지는 cm이 보장하지 않습니다.")
        print(
            f"    계정별 정확한 한도는 {colored('cm status', C.CYAN)}"
            "(usage API 직접 조회)를 기준으로 보세요."
        )
    if info["pinned_accounts"]:
        print(
            f"  {colored('!', C.YELLOW)} config.toml이 다른 계정 홈 경로를 포함합니다: "
            f"{', '.join(info['pinned_accounts'])}"
        )
        print(f"    확인: {info['path']}")


def auth_doctor():
    live_path = APP_CODEX_HOME / "auth.json"
    live_auth = _read_auth_file(live_path) if live_path.exists() else None
    account_id = _account_id(live_auth)
    matched = find_accounts_by_id(account_id)
    duplicate_groups = {}
    for name in list_accounts():
        stored_id = _account_id(read_auth(name))
        if stored_id:
            duplicate_groups.setdefault(stored_id, []).append(name)
    duplicate_groups = [names for names in duplicate_groups.values() if len(names) > 1]
    temp_homes = [
        path for path in HOMES_DIR.glob("_tmp_*")
        if path.is_dir()
    ] if HOMES_DIR.exists() else []
    temp_homes_with_auth = [path for path in temp_homes if (path / "auth.json").exists()]
    inherited = Path(INHERITED_CODEX_HOME).expanduser() if INHERITED_CODEX_HOME else None
    inherited_isolated = bool(
        inherited and inherited != APP_CODEX_HOME and MANAGER_DIR in inherited.parents
    )

    print(f"\n  {colored('◆ cm 인증 진단', C.CYAN, C.BOLD)}")
    print(f"  App home        : {APP_CODEX_HOME}")
    print(f"  Account store   : {ACCOUNTS_DIR}")
    print(f"  Codex command   : {_codex_command()}")
    device_timeout = _login_timeout_seconds()
    timeout_label = f"{device_timeout}s" if device_timeout is not None else "none"
    print(f"  Login default   : device-auth / local timeout {timeout_label} / auto-reissue on")
    print("  Upstream expiry : each OpenAI device code expires after 15 minutes")
    print(f"  App auth        : {'OK' if _has_usable_chatgpt_auth(live_auth) else 'MISSING/INVALID'}")
    print(f"  Stored accounts : {len(list_accounts())}")
    print(f"  App auth match  : {', '.join(matched) if matched else '-'}")
    print(f"  Duplicate IDs   : {len(duplicate_groups)} group(s)")
    for names in duplicate_groups:
        print(f"    - {', '.join(names)}")
    print(f"  Stale temp homes: {len(temp_homes)} (auth 포함 {len(temp_homes_with_auth)})")
    if temp_homes:
        print("  정리 확인      : cm cleanup-temp  (삭제 실행은 --yes 필요)")
    if inherited_isolated:
        print(f"  {colored('✓', C.GREEN)} 부모 isolated CODEX_HOME은 무시하고 App home을 사용합니다.")

    config_info = shared_config_conflicts(get_active_account(live_auth=live_auth))
    print(f"  Shared config   : {config_info['path']}")
    if config_info["external_base_urls"]:
        for value in config_info["external_base_urls"]:
            print(f"    외부 엔드포인트 경유: {value}")
        ocx_routes = [
            value for value in config_info["external_base_urls"]
            if is_ocx_routing_url(value)
        ]
        mode = proxy_codex_account_mode() if ocx_routes else None
        if mode == "direct":
            print(f"    {colored('✓', C.GREEN)} 프록시 account-mode: direct (호출 계정 자격 사용)")
        elif mode == "pool":
            print(f"    {colored('✓', C.GREEN)} 프록시 account-mode: pool (OCX가 새 작업 계정을 선택)")
            print("      전환: ocx account current openai · ocx account use openai <id>")
        elif not ocx_routes:
            print(f"    {colored('!', C.YELLOW)} OCX 경로가 아님 — OCX 계정 모드를 적용하지 않음")
        else:
            print(f"    {colored('!', C.YELLOW)} 프록시 account-mode 확인 불가")
    if config_info["pinned_accounts"]:
        print(
            f"    {colored('!', C.YELLOW)} 다른 계정 홈 경로 고정: "
            f"{', '.join(config_info['pinned_accounts'])}"
        )
    if not config_info["external_base_urls"] and not config_info["pinned_accounts"]:
        print(f"    {colored('✓', C.GREEN)} 계정 격리를 깨는 공유 설정 없음")

    print_proxy_account_pool()


PROXY_ACCOUNT_POOL_URL = "http://127.0.0.1:10100/api/codex-auth/accounts"
PROXY_MAIN_ACCOUNT_ID = "__main__"
OPENCODEX_CONFIG_FILE = Path(
    os.environ.get("OPENCODEX_HOME", str(Path.home() / ".opencodex"))
).expanduser() / "config.json"


def _opencodex_config() -> dict | None:
    try:
        config = json.loads(OPENCODEX_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return config if isinstance(config, dict) else None


def proxy_default_provider() -> str | None:
    config = _opencodex_config()
    provider = config.get("defaultProvider") if config else None
    return provider if isinstance(provider, str) else None


def proxy_codex_account_mode() -> str | None:
    """How the local proxy authenticates Codex traffic.

    ``direct`` uses the caller's own ChatGPT credential, so cm's per-account
    isolation holds end to end. ``pool`` lets OCX select the account for each
    new task; running tasks keep the account they started with.
    """
    config = _opencodex_config()
    providers = config.get("providers") if config else None
    openai = providers.get("openai") if isinstance(providers, dict) else None
    mode = openai.get("codexAccountMode") if isinstance(openai, dict) else None
    return mode if isinstance(mode, str) else None


def proxy_account_pool() -> list[dict] | None:
    """Accounts the local proxy keeps for itself, or None when unreachable."""
    try:
        with urlopen(PROXY_ACCOUNT_POOL_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, OSError, ValueError, json.JSONDecodeError):
        return None
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    return accounts if isinstance(accounts, list) else None


def print_proxy_account_pool():
    """Report the OCX-owned pool without treating it as cm-owned state."""
    accounts = proxy_account_pool()
    if accounts is None:
        return
    extra_count = sum(
        1 for entry in accounts
        if isinstance(entry, dict) and entry.get("id") != PROXY_MAIN_ACCOUNT_ID
    )
    if not extra_count:
        print(
            f"  Proxy 계정 풀  : main 1개 (cm의 ~/.codex/auth.json을 따라감) "
            f"{colored('✓', C.GREEN)}"
        )
        return
    print(f"  Proxy 계정 풀  : OCX 관리 계정 {extra_count}개 + main {colored('✓', C.GREEN)}")
    print("    cm 저장소와 동기화하지 않습니다. 전환은 ocx account current/use로만 수행합니다.")


def _cmd_doctor(rest):
    auth_doctor()


def _cmd_auth_sync(rest):
    if rest:
        print("사용법: cm auth-sync")
        return
    script = OPS_DIR / "auth-portal" / "mac_sync.py"
    result = subprocess.run([sys.executable, str(script)], check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def cleanup_temp_homes(*, execute: bool = False):
    ensure_dirs()
    candidates = [
        path for path in HOMES_DIR.glob("_tmp_*")
        if path.is_dir() and path.parent == HOMES_DIR
    ]
    sensitive = [path for path in candidates if (path / "auth.json").exists()]
    print(f"  임시 로그인 홈: {len(candidates)}개 (auth 포함 {len(sensitive)}개)")
    if not execute:
        print("  읽기 전용 확인입니다. 영구 정리는 cm cleanup-temp --yes")
        return {"ok": True, "count": len(candidates), "sensitive": len(sensitive), "removed": 0}
    for path in candidates:
        shutil.rmtree(path)
    print(f"  {colored('✓', C.GREEN)} 임시 로그인 홈 {len(candidates)}개를 정리했습니다.")
    return {"ok": True, "count": len(candidates), "sensitive": len(sensitive), "removed": len(candidates)}


def _cmd_cleanup_temp(rest):
    cleanup_temp_homes(execute="--yes" in rest)


def _cmd_remove(rest):
    accounts = list_accounts()
    show_table(accounts)
    choice = input("\n  삭제할 번호: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(accounts):
        delete_account(accounts[int(choice) - 1])
        print(f"  {colored('✓', C.GREEN)} 삭제됨.")


def _cmd_update(rest):
    update_codex_cli(force=any(arg in ("--force", "-f") for arg in rest))


def _cmd_reset_credits(rest):
    # --all/-a remain accepted as backward-compatible no-ops because all
    # accounts are now the default.
    available_only = any(arg in ("--available-only", "--available") for arg in rest)
    show_reset_credit_expiries(show_all=not available_only)


def _cmd_help(rest):
    print_help()


COMMANDS = [
    {"names": ["status", "list"], "usage": "cm status [--json]",
     "desc": "계정/잔여량 표 출력", "remote": "ok", "mono": True, "handler": _cmd_status},
    {"names": ["switch", "app-switch", "s"], "usage": "cm switch <번호>",
     "desc": "전역 App 계정 전환(auth.json 교체)", "remote": "arg", "remote_min": 1, "mono": True, "handler": _cmd_switch},
    {"names": ["phone", "tel"], "usage": "cm phone <번호> <전화번호>",
     "desc": "계정 인증 전화번호 기록/삭제", "remote": "arg", "remote_min": 2, "handler": _cmd_phone},
    {"names": ["usage-proxy", "proxy"], "usage": "cm usage-proxy <번호> <값>",
     "desc": "usage 조회 프록시(URL|direct|system)", "remote": "arg", "remote_min": 2, "handler": _cmd_proxy},
    {"names": ["quota-debug", "debug-quota"], "usage": "cm quota-debug <번호>",
     "desc": "usage 조회 네트워크/HTTP 진단", "remote": "arg", "remote_min": 1, "handler": _cmd_quota_debug},
    {"names": ["reset-credits", "reset-credit", "credits", "resets"], "usage": "cm reset-credits [--available-only]",
     "desc": "모든 계정의 초기화권 수·사용기한·남은 시간 조회", "remote": "ok", "mono": True, "handler": _cmd_reset_credits},
    {"names": ["app-dry-run"], "usage": "cm app-dry-run <번호>",
     "desc": "App 실행 경로만 확인", "remote": "arg", "remote_min": 1, "handler": _cmd_app_dry},
    {"names": ["remote", "ssh", "account-remote"], "usage": "cm remote <번호>|status|stop",
     "desc": "현재 App을 다른 계정의 단일 SSH app-server에 연결", "remote": "local", "handler": _cmd_remote},
    {"names": ["threads", "thread-index"], "usage": "cm threads status|sync <계정|all>",
     "desc": "모델 호출 없는 계정별 로컬 스레드 색인 동기화", "remote": "local", "handler": _cmd_threads},
    {"names": ["cli", "launch", "run", "c"], "usage": "cm cli <번호>",
     "desc": "계정별 isolated CLI 실행", "remote": "local", "handler": _cmd_cli},
    {"names": ["app", "app-launch", "open-app", "open", "ca", "o"], "usage": "cm app <번호> [--restart]",
     "desc": "계정별 Desktop App 별도 실행(--restart는 해당 계정 App만 재시작)", "remote": "local", "handler": _cmd_app},
    {"names": ["import-app", "sync-app", "import"], "usage": "cm import-app [이름] [--dry-run]",
     "desc": "현재 ~/.codex 로그인 가져오기/갱신", "remote": "local", "handler": _cmd_import_app},
    {"names": ["refresh", "reauth"], "usage": "cm refresh <번호> [--once|--browser]",
     "desc": "선택 계정 토큰 갱신(기기 코드 지속 대기 기본)", "remote": "local", "handler": _cmd_refresh},
    {"names": ["add"], "usage": "cm add [--once|--browser]",
     "desc": "새 계정 추가(기기 코드 지속 대기 기본)", "remote": "local", "handler": _cmd_add},
    {"names": ["doctor", "auth-doctor"], "usage": "cm doctor",
     "desc": "인증 경로/로그인 대기/임시 홈 진단", "remote": "local", "handler": _cmd_doctor},
    {"names": ["auth-sync", "portal-sync"], "usage": "cm auth-sync",
     "desc": "서버에 대기 중인 구성된 대상 인증 가져오기", "remote": "local", "handler": _cmd_auth_sync},
    {"names": ["cleanup-temp"], "usage": "cm cleanup-temp [--yes]",
     "desc": "중단된 로그인 임시 홈 확인/명시적 정리", "remote": "local", "handler": _cmd_cleanup_temp},
    {"names": ["remove"], "usage": "cm remove",
     "desc": "계정 삭제", "remote": "local", "handler": _cmd_remove},
    {"names": ["update", "upgrade", "codex-update", "self-update"], "usage": "cm update",
     "desc": "Codex CLI 최신 버전 설치/검증", "remote": "local", "handler": _cmd_update},
    {"names": ["help", "-h", "--help"], "usage": "cm help",
     "desc": "도움말", "remote": "ok", "handler": _cmd_help},
]


def find_command(name: str):
    name = (name or "").lower()
    for entry in COMMANDS:
        if name in entry["names"]:
            return entry
    return None


# Commands that must see current credentials, keyed by canonical command name so
# adding an alias can never silently drop the pre-sync step.
SYNC_BEFORE_COMMANDS = {
    "status", "switch", "cli", "app", "reset-credits", "remote", "threads",
}


def sync_command_names() -> set[str]:
    names = {""}
    for entry in COMMANDS:
        if entry["names"][0] in SYNC_BEFORE_COMMANDS:
            names.update(entry["names"])
    return names


def command_is_mono(args: list[str]) -> bool:
    """Whether the command's output should be a monospace code block (tables)."""
    if not args:
        return True  # default -> status table
    entry = find_command(args[0])
    if entry is None:
        return False  # falls through to help text
    return bool(entry.get("mono", False))


def dispatch_command(args: list[str]):
    """Shared dispatch used by the CLI main()."""
    if not args:
        tui()
        return
    entry = find_command(args[0])
    if entry is None:
        # Silently printing help made typos look like a no-op switch/launch.
        print()
        print(f"  {colored('✗', C.RED)} 알 수 없는 명령: {args[0]}")
        print_help()
        raise SystemExit(2)
    entry["handler"](args[1:])


def _capture_text(fn, width: int = 72) -> str:
    """Run fn() with color off, fixed width, captured stdout; return plain text."""
    import io
    from contextlib import redirect_stdout

    prev_cols = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(width)
    set_color_enabled(False)
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO("")  # any stray input() -> EOFError instead of hang
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            fn()
    except Exception as exc:
        buf.write(f"\n오류: {exc.__class__.__name__}")
    finally:
        sys.stdin = saved_stdin
        set_color_enabled(True)
        if prev_cols is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = prev_cols

    # Collapse carriage-return progress lines (e.g. loading / step spinners)
    out_lines = []
    for line in buf.getvalue().split("\n"):
        if "\r" in line:
            line = line.split("\r")[-1]
        out_lines.append(line.rstrip())
    return "\n".join(out_lines).strip("\n") or "(출력 없음)"


def render_command_output(args: list[str], width: int = 72) -> str:
    """Headless runner for the Telegram bridge: run the SAME cm command the
    terminal uses and return its text so remote output matches the terminal."""
    ensure_dirs()
    if not args:
        args = ["status"]
    entry = find_command(args[0])
    rest = args[1:]
    if entry is None:
        return _capture_text(print_help, width)
    if entry["remote"] == "local":
        avail = "\n".join(f"  {e['usage']}" for e in COMMANDS if e["remote"] != "local")
        return (f"'{args[0]}' 명령은 PC 터미널에서만 사용할 수 있습니다.\n"
                f"원격 사용 가능 명령:\n{avail}")
    if entry["remote"] == "arg" and len(rest) < entry.get("remote_min", 1):
        hint = f"사용법: {entry['usage']}"
        if "switch" in entry["names"]:
            return f"{hint}\n예: cm switch 2\n\n{_capture_text(show_table, width)}"
        return hint
    return _capture_text(lambda: entry["handler"](rest), width)


def _tg_bar(remain, slots: int = 5) -> str:
    """Colored emoji bar — length encodes magnitude, color encodes level.
    No empty track (cleaner on dark theme)."""
    if not isinstance(remain, (int, float)):
        return "▫️"
    sq = "🟩" if remain >= 70 else "🟨" if remain >= 40 else "🟧" if remain >= 15 else "🟥"
    filled = max(1, int(round(max(0, min(100, remain)) / 100 * slots)))
    return sq * filled


def _tg_dot(values, expired: bool, error: bool) -> str:
    """Emoji health dot from the most constrained remaining-% value."""
    if expired:
        return "⚫"
    if error:
        return "⚠️"
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return "⚪"
    low = min(nums)
    if low >= 70:
        return "🟢"
    if low >= 40:
        return "🟡"
    if low >= 15:
        return "🟠"
    return "🔴"


def render_status_telegram() -> str:
    """Phone-optimized account view (HTML): emoji health dots + colored bars.

    Uses proportional text (auto-wraps to phone width) with colored emoji
    progress bars, so it reads cleanly on a Galaxy S25+ without horizontal
    scrolling. Consumes the same data layer as the terminal table.
    """
    import html

    ensure_dirs()
    accounts = list_accounts()
    if not accounts:
        return "등록된 계정이 없습니다. PC에서 <code>cm add</code>로 추가하세요."

    app_context = get_live_app_context(accounts)
    active = app_context["active"]
    cli_active = get_cli_accounts()
    auth_overrides = {active: app_context["auth"]} if active and app_context["auth"] else {}
    quota_overrides = {active: app_context["quota"]} if active else {}
    quotas, reset_credits = fetch_account_remote_rows(
        accounts,
        auth_overrides=auth_overrides,
        quota_overrides=quota_overrides,
    )

    lines = [f"📋 <b>Codex 계정 · {len(accounts)}개</b>",
             f"현재 App · <b>{html.escape(active) if active else '-'}</b>", ""]

    for i, name in enumerate(accounts, 1):
        data = quotas.get(name)
        q = format_quota(data) if data else format_quota({"ok": False, "error": "no_auth"})
        credit = format_reset_credit_status(reset_credits.get(name) or {"ok": False, "error": "no_auth"})
        expired = q["expired"]
        error = bool(q.get("error")) and not expired
        phone = get_account_phone(name)
        expiry = get_expiry(name)
        label = html.escape(name)

        if expired or error:
            tail = "만료" if expired else "조회실패"
            extra = f" · 📞{html.escape(phone)}" if phone else ""
            mark = "⚫" if expired else "⚠️"
            lines.append(f"<blockquote>{mark} <b>{i}</b> {label} · {tail}{extra}</blockquote>")
            continue

        marks = (" ✅App" if name == active else "") + (" 💻CLI" if name in cli_active else "")
        dot = _tg_dot([q["5h_remain"], q["wk_remain"]], False, False)
        quota1_label = q.get("quota1_label") or "한도1"
        quota2_label = q.get("quota2_label") or q.get("long_label") or "한도2"
        rows = [f"{dot} <b>{i}</b> {label}{marks}"]
        for slot_label, remain, reset in (
            (quota1_label, q["5h_remain"], q["5h_reset"]),
            (quota2_label, q["wk_remain"], q["wk_reset"]),
        ):
            if slot_label == "-":
                continue
            rows.append(
                f"{html.escape(str(slot_label))} {_tg_bar(remain)} "
                f"<b>{pct_text(remain, False)}</b> · ↻{reset or '-'}"
            )
        meta = []
        plan = q.get("plan")
        if plan and plan != "?":
            meta.append(html.escape(str(plan)))
        if expiry:
            meta.append(f"만료 {html.escape(expiry)}")
        if phone:
            meta.append(f"📞{html.escape(phone)}")
        if isinstance(credit.get("available"), int):
            credit_meta = f"🎟 {credit['available']}권"
            if credit.get("nearest_expiry_local"):
                credit_meta += f" · 사용기한 {html.escape(credit['nearest_expiry_local'])}"
            if credit.get("nearest_remaining_text") not in (None, "-"):
                credit_meta += f" · 남음 {html.escape(credit['nearest_remaining_text'])}"
            meta.append(credit_meta)
        if meta:
            rows.append(" · ".join(meta))
        lines.append("<blockquote>" + "\n".join(rows) + "</blockquote>")

    lines.append("")
    lines.append("전환 <code>cm switch 2</code> · 도움말 <code>cm help</code>")
    return "\n".join(lines)


def print_help():
    print()
    print(colored("  Codex 멀티계정 매니저 (cm)", C.CYAN, C.BOLD))
    print("  터미널과 텔레그램에서 똑같은 명령을 씁니다.")
    print()
    print(colored("  [공통 — 터미널/텔레그램]", C.BOLD))
    for entry in COMMANDS:
        if entry["remote"] != "local":
            print(f"    {entry['usage']}")
            print(f"        {entry['desc']}")
    print()
    print(colored("  [PC 전용 — 터미널에서만]", C.BOLD))
    for entry in COMMANDS:
        if entry["remote"] == "local":
            print(f"    {entry['usage']}  —  {entry['desc']}")
    print()
    print(colored("  예시", C.BOLD))
    print("    cm status                 계정 표 보기")
    print("    cm switch 2               2번 계정으로 App 전환")
    print("    cm phone 2 010-1234-5678  2번 인증 전화번호 기록")
    print("    cm reset-credits          모든 계정 초기화권/사용기한/남은 시간 보기")
    print("    cm update                 Codex CLI 최신 업데이트")
    print()
    print("  · 번호는 표의 No. 선택자는 번호/이메일 일부/전화번호 모두 가능")
    print("  · 텔레그램: 'cm' 없이 'status', 'switch 2'만 보내도 됩니다")
    print("  · 레거시 별칭: /ca <번호>, /codexapp, /help, /start")
    print()


def split_selector_args(args: list[str]) -> tuple[str | None, list[str]]:
    if not args:
        return None, []
    if args[0].startswith("-"):
        return None, args
    return args[0], args[1:]


def phone_command(args: list[str]):
    accounts = list_accounts()
    selector, rest = split_selector_args(args)
    if selector is None:
        show_table(accounts)
        selector = input("\n  전화번호를 기록할 계정: ").strip()
    name = resolve_account_selector(selector, accounts)
    if name is None:
        return
    if rest:
        phone = " ".join(rest).strip()
        if phone in ("-", "none", "delete", "remove"):
            phone = ""
    else:
        phone = input("  인증에 사용한 전화번호 (빈칸=삭제): ").strip()
    set_account_phone(name, phone or None)
    if phone:
        print(f"  {colored('✓', C.GREEN)} {name} 전화번호: {phone}")
    else:
        print(f"  {colored('✓', C.GREEN)} {name} 전화번호 삭제됨.")


def usage_proxy_command(args: list[str]):
    accounts = list_accounts()
    selector, rest = split_selector_args(args)
    if selector is None:
        show_table(accounts)
        selector = input("\n  usage proxy를 설정할 계정: ").strip()
    name = resolve_account_selector(selector, accounts)
    if name is None:
        return

    if rest:
        proxy = " ".join(rest).strip()
    else:
        current = get_account_usage_proxy(name)
        print(f"  현재: {_redact_url(current) if current else 'system'}")
        proxy = input("  새 usage proxy (URL/direct/system, 빈칸=삭제): ").strip()

    lowered = proxy.lower()
    if not proxy or lowered in ("-", "delete", "remove", "clear", "system", "default", "auto"):
        set_account_usage_proxy(name, None)
        set_account_usage_last_success(name, None)
        print(f"  {colored('✓', C.GREEN)} {name} usage proxy: system")
    elif lowered in ("direct", "none", "off", "no"):
        set_account_usage_proxy(name, "direct")
        set_account_usage_last_success(name, "direct")
        print(f"  {colored('✓', C.GREEN)} {name} usage proxy: direct")
    else:
        set_account_usage_proxy(name, proxy)
        print(f"  {colored('✓', C.GREEN)} {name} usage proxy: {_redact_url(proxy)}")


def quota_debug_command(args: list[str]):
    accounts = list_accounts()
    selector, _ = split_selector_args(args)
    if selector is None:
        show_table(accounts)
        selector = input("\n  진단할 계정: ").strip()
    name = resolve_account_selector(selector, accounts)
    if name is None:
        return

    auth = read_auth(name)
    if not auth:
        print(f"  {colored('✗', C.RED)} 인증 정보 없음: {name}")
        return

    data = fetch_quota(auth, account_name=name, include_debug=True)
    debug = data.get("_debug", {})
    q = format_quota(data)

    print()
    print(f"  {colored('◆ usage 조회 진단', C.CYAN, C.BOLD)}")
    print(f"  계정       : {name}")
    print(f"  ID         : {account_id_prefix(name)}")
    print(f"  API        : {debug.get('api', USAGE_API)}")
    api_dns = debug.get("api_dns") or []
    if api_dns:
        print(f"  API DNS    : {', '.join(api_dns)}")
    print(f"  Proxy      : {debug.get('proxy', 'system')} ({debug.get('proxy_source', 'system')})")
    print(f"  Attempts   : {debug.get('attempts', '-')}")
    print(f"  HTTP       : {debug.get('http_status', '-')}")
    print(f"  Type       : {debug.get('content_type', '-')}")
    print(f"  Elapsed    : {debug.get('elapsed_ms', '-')} ms")
    if debug.get("exception"):
        print(f"  Exception  : {debug.get('exception')}")
    tried = debug.get("tried") or []
    if tried:
        print("  Routes     :")
        for item in tried:
            status = item.get("http_status", "-")
            error = item.get("error", "ok")
            elapsed = item.get("elapsed_ms", "-")
            print(
                f"    - {item.get('proxy', 'system')} "
                f"({item.get('proxy_source', 'system')}): {error}, http={status}, {elapsed}ms"
            )
            proxy_dns = item.get("proxy_dns") or []
            if proxy_dns:
                print(f"      dns: {', '.join(proxy_dns)}")
    if data.get("ok"):
        print(f"  Result     : {colored('OK', C.GREEN)}")
        print(f"  Email      : {q.get('email', '?')}")
        print(f"  Plan       : {q.get('plan', '?')}")
        print(f"  5h/Wk      : {pct_text(q.get('5h_remain'))} / {pct_text(q.get('wk_remain'))}")
    else:
        print(f"  Result     : {colored('ERR', C.RED)} ({data.get('error', 'unknown')})")
        print("  Token/body : hidden")


def main():
    ensure_dirs()
    args = sys.argv[1:]
    command_name = args[0].lower() if args else ""
    try:
        backend = _remote_backend()
        if hasattr(backend, "stop_if_idle"):
            backend.stop_if_idle(MANAGER_DIR)
    except (ImportError, OSError, RuntimeError):
        # A normal cm command must remain usable when SSH/WSL is absent.
        pass
    sync_commands = sync_command_names()

    # Keep a known account current whenever cm is opened or used to launch.
    # Help/doctor/dry-run remain read-only.
    if command_name in sync_commands:
        for account_name in list_accounts():
            sync_isolated_home_auth(account_name)
        sync_matching_app_auth()

    # Preserve the original first-run convenience without making help/doctor
    # unexpectedly write credentials.
    if not all_account_files() and command_name not in {
        "help", "-h", "--help", "doctor", "auth-doctor",
    }:
        import_app_auth(quiet=True)

    dispatch_command(args)


if __name__ == "__main__":
    main()
