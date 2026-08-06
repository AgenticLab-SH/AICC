"""Small stdlib Telegram client for the AICC notification skill."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


def _clean(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text.strip()


def load_config(env_file: str | os.PathLike | None = None) -> dict[str, str]:
    path = Path(
        env_file
        or os.environ.get("AICC_TELEGRAM_ENV_FILE", "")
        or Path(os.environ.get("AICC_STATE_ROOT", Path.home() / ".ai-control-center"))
        / "telegram"
        / "agent-bridge.env"
    ).expanduser()
    config: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text("utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = _clean(value)
    for key, value in os.environ.items():
        if key.startswith(("TELEGRAM_", "CODEX_TELEGRAM_")):
            config[key] = value
    return config


def bot_token(config: dict[str, str]) -> str:
    return _clean(
        config.get("TELEGRAM_BOT_TOKEN")
        or config.get("CODEX_TELEGRAM_BOT_TOKEN")
        or config.get("GEMINI_CONNECT_TELEGRAM_BOT_TOKEN")
    )


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in _clean(value).split(",") if item.strip()]


def default_chat_ids(config: dict[str, str]) -> list[str]:
    value = (
        config.get("TELEGRAM_CHAT_ID")
        or config.get("CODEX_TELEGRAM_CHAT_ID")
        or config.get("TELEGRAM_ALLOWED_USERS")
        or config.get("CODEX_TELEGRAM_ALLOWED_USERS")
    )
    return sorted(set(_csv(value)))


def allowed_users(config: dict[str, str]) -> set[str]:
    value = (
        config.get("TELEGRAM_ALLOWED_USERS")
        or config.get("CODEX_TELEGRAM_ALLOWED_USERS")
        or config.get("TELEGRAM_CHAT_ID")
        or config.get("CODEX_TELEGRAM_CHAT_ID")
    )
    return set(_csv(value))


def api_request(token: str, method: str, params: dict | None = None, timeout: int = 35) -> dict:
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
