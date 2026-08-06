"""Standalone, reusable Telegram client for AICC.

This is NOT tied to any single agent/bot. Any consumer — the Codex
multi-account bot, other agents, or Hermes — imports this module (or calls the
`tg` CLI) instead of embedding its own Telegram code. Pure stdlib, no deps.

Config resolution (first existing file wins), then process-env overrides:
  1. explicit env_file argument
  2. $AGENT_TELEGRAM_ENV_FILE
  3. ~/.config/agent-telegram/telegram.env
  4. ~/.codex/telegram.env            (existing creds, reused)

Recognized keys (new + legacy):
  token : TELEGRAM_BOT_TOKEN | CODEX_TELEGRAM_BOT_TOKEN
  chats : TELEGRAM_CHAT_ID | CODEX_TELEGRAM_CHAT_ID | CODEX_TELEGRAM_NOTIFY_CHAT_IDS
          | TELEGRAM_ALLOWED_USERS | CODEX_TELEGRAM_ALLOWED_USERS
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API_BASE = "https://api.telegram.org"

DEFAULT_ENV_CANDIDATES = [
    Path.home() / ".config" / "agent-telegram" / "telegram.env",
    Path.home() / ".codex" / "telegram.env",
]


def clean(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path or not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = clean(value)
    return env


def load_config(env_file: str | os.PathLike | None = None) -> dict[str, str]:
    """Load Telegram config from the first available env file + process env."""
    config: dict[str, str] = {}
    candidates: list[Path] = []
    if env_file:
        candidates.append(Path(env_file))
    if os.environ.get("AGENT_TELEGRAM_ENV_FILE"):
        candidates.append(Path(os.environ["AGENT_TELEGRAM_ENV_FILE"]))
    candidates += DEFAULT_ENV_CANDIDATES
    for p in candidates:
        loaded = _load_dotenv(p)
        if loaded:
            config.update(loaded)
            config["_env_file"] = str(p)
            break
    for key, value in os.environ.items():
        if key.startswith("TELEGRAM_") or key.startswith("CODEX_TELEGRAM_"):
            config[key] = value
    return config


def bot_token(config: dict[str, str]) -> str:
    return clean(config.get("TELEGRAM_BOT_TOKEN") or config.get("CODEX_TELEGRAM_BOT_TOKEN"))


def _csv(value: str | None) -> list[str]:
    return [part.strip() for part in clean(value).split(",") if part.strip()]


def default_chat_ids(config: dict[str, str]) -> list[str]:
    raw = (
        config.get("TELEGRAM_CHAT_ID")
        or config.get("CODEX_TELEGRAM_CHAT_ID")
        or config.get("CODEX_TELEGRAM_NOTIFY_CHAT_IDS")
        or config.get("TELEGRAM_ALLOWED_USERS")
        or config.get("CODEX_TELEGRAM_ALLOWED_USERS")
    )
    return sorted(set(_csv(raw)))


def allowed_users(config: dict[str, str]) -> set[str]:
    raw = (
        config.get("TELEGRAM_ALLOWED_USERS")
        or config.get("CODEX_TELEGRAM_ALLOWED_USERS")
        or config.get("TELEGRAM_CHAT_ID")
        or config.get("CODEX_TELEGRAM_CHAT_ID")
    )
    return set(_csv(raw))


# === Bot API calls ===

def api_request(token: str, method: str, params: dict | None = None, timeout: int = 35) -> dict:
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}/bot{token}/{method}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_me(token: str, timeout: int = 15) -> dict:
    return api_request(token, "getMe", {}, timeout=timeout)


def send_message(token: str, chat_id: str, text: str, *, parse_mode: str | None = None,
                 reply_to: int | None = None, timeout: int = 35) -> dict:
    params: dict[str, str | int] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_to is not None:
        params["reply_to_message_id"] = reply_to
    return api_request(token, "sendMessage", params, timeout=timeout)


def send_photo(token: str, chat_id: str, image_path: str | os.PathLike, caption: str | None = None,
               *, parse_mode: str | None = None, timeout: int = 60) -> dict:
    boundary = uuid.uuid4().hex
    img = Path(image_path).read_bytes()
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        payload = (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{name}"\r\n\r\n{value}\r\n'
        )
        parts.append(payload.encode())

    field("chat_id", str(chat_id))
    if caption:
        field("caption", caption)
    if parse_mode:
        field("parse_mode", parse_mode)
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
        f'filename="{Path(image_path).name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
        + img
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{API_BASE}/bot{token}/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_updates(token: str, offset: int | None = None, timeout_s: int = 0, limit: int = 25,
                http_timeout: int | None = None) -> dict:
    params: dict[str, int] = {"timeout": timeout_s, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    return api_request(token, "getUpdates", params, timeout=http_timeout or (timeout_s + 10))


def send_to_default(text: str, *, parse_mode: str | None = None, env_file: str | None = None,
                    timeout: int = 15) -> tuple[bool, str]:
    """Convenience: send to all configured default chat ids."""
    config = load_config(env_file)
    token = bot_token(config)
    if not token:
        return False, "no bot token (set TELEGRAM_BOT_TOKEN)"
    chat_ids = default_chat_ids(config)
    if not chat_ids:
        return False, "no chat id (set TELEGRAM_CHAT_ID)"
    errors = []
    for chat_id in chat_ids:
        try:
            send_message(token, chat_id, text, parse_mode=parse_mode, timeout=timeout)
        except Exception as exc:
            errors.append(f"{chat_id}:{exc.__class__.__name__}")
    return (not errors), ("sent" if not errors else ", ".join(errors))
