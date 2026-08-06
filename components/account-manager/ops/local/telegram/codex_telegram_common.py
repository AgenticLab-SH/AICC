"""Codex-specific Telegram config shim over the bundled stdlib client.

The project-local client keeps the optional notifier and Windows bot independent
from AICC. This module pins the Codex env file (~/.codex/telegram.env) and
keeps the function names used by the existing integrations.
"""
from __future__ import annotations

from pathlib import Path

from telegram_client import (  # noqa: E402
    API_BASE as API_BASE,
)
from telegram_client import (
    _csv,
    bot_token,
    send_message,
)
from telegram_client import (
    api_request as api_request,
)
from telegram_client import (
    clean as clean,
)
from telegram_client import (
    get_updates as get_updates,
)
from telegram_client import (
    load_config as _shared_load_config,
)
from telegram_client import (
    send_photo as send_photo,
)

DEFAULT_ENV_FILE = Path.home() / ".codex" / "telegram.env"


def load_config() -> dict[str, str]:
    """Codex bot config: pin to ~/.codex/telegram.env (+ process env overrides)."""
    return _shared_load_config(DEFAULT_ENV_FILE)


def csv_set(value: str | None) -> set[str]:
    return set(_csv(value))


def allowed_users(config: dict[str, str]) -> set[str]:
    return csv_set(
        config.get("CODEX_TELEGRAM_ALLOWED_USERS")
        or config.get("TELEGRAM_ALLOWED_USERS")
        or config.get("CODEX_TELEGRAM_CHAT_ID")
        or config.get("TELEGRAM_CHAT_ID")
        or config.get("TELEGRAM_HOME_CHANNEL")
    )


def notify_chat_ids(config: dict[str, str]) -> list[str]:
    raw = (
        config.get("CODEX_TELEGRAM_NOTIFY_CHAT_IDS")
        or config.get("CODEX_TELEGRAM_CHAT_ID")
        or config.get("TELEGRAM_CHAT_ID")
        or config.get("TELEGRAM_HOME_CHANNEL")
        or config.get("CODEX_TELEGRAM_ALLOWED_USERS")
        or config.get("TELEGRAM_ALLOWED_USERS")
    )
    return sorted(csv_set(raw))


def send_configured_message(text: str, timeout: int = 15) -> tuple[bool, str]:
    config = load_config()
    token = bot_token(config)
    if not token:
        return False, f"CODEX_TELEGRAM_BOT_TOKEN 누락: {DEFAULT_ENV_FILE}"
    chat_ids = notify_chat_ids(config)
    if not chat_ids:
        message = (
            "CODEX_TELEGRAM_ALLOWED_USERS 또는 CODEX_TELEGRAM_CHAT_ID 누락: "
            f"{DEFAULT_ENV_FILE}"
        )
        return False, message
    errors: list[str] = []
    for chat_id in chat_ids:
        try:
            send_message(token, chat_id, text, timeout=timeout)
        except Exception as exc:
            errors.append(f"{chat_id}:{exc.__class__.__name__}")
    if errors:
        return False, ", ".join(errors)
    return True, "sent"
