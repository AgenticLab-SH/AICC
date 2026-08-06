"""Interactive setup for the Windows-native Codex Telegram bot."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

from codex_telegram_common import DEFAULT_ENV_FILE, api_request, clean

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _read_token(arg_value: str | None) -> str:
    token = clean(arg_value or os.environ.get("CODEX_TELEGRAM_BOT_TOKEN"))
    if token:
        return token
    return clean(getpass.getpass("BotFather가 발급한 Codex bot token 입력: "))


def _latest_offset(token: str) -> int | None:
    data = api_request(token, "getUpdates", {"timeout": 0, "limit": 100}, timeout=15)
    updates = data.get("result") or []
    if not updates:
        return None
    return max(int(update["update_id"]) for update in updates) + 1


def _wait_for_owner(token: str, offset: int | None, timeout_sec: int) -> tuple[str, str]:
    print("새 Codex bot에게 Telegram에서 /start 를 보내세요. 사용자 id를 자동 감지합니다.")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        params: dict[str, int] = {"timeout": 10, "limit": 25}
        if offset is not None:
            params["offset"] = offset
        data = api_request(token, "getUpdates", params, timeout=15)
        for update in data.get("result") or []:
            offset = int(update["update_id"]) + 1
            message = update.get("message") or update.get("edited_message") or {}
            sender = message.get("from") or {}
            if sender.get("is_bot"):
                continue
            user_id = str(sender.get("id") or "")
            chat_id = str((message.get("chat") or {}).get("id") or "")
            if user_id and chat_id:
                return user_id, chat_id
    raise TimeoutError("지정 시간 안에 /start 메시지를 감지하지 못했습니다.")


def _write_env(path: Path, token: str, user_id: str, chat_id: str, bot_username: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        [
            "# Codex 전용 Telegram bot 설정",
            "# Hermes/WSL과 분리해서 사용합니다.",
            f"CODEX_TELEGRAM_BOT_TOKEN={token}",
            f"CODEX_TELEGRAM_ALLOWED_USERS={user_id}",
            f"CODEX_TELEGRAM_CHAT_ID={chat_id}",
            f"CODEX_TELEGRAM_BOT_USERNAME={bot_username}",
            "",
        ]
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex Telegram bot setup")
    parser.add_argument("--token", help="BotFather token. Prefer interactive input for secrecy.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    token = _read_token(args.token)
    if not token:
        print("토큰이 비어 있습니다.", file=sys.stderr)
        return 2

    try:
        info = api_request(token, "getMe", timeout=15)
        result = info.get("result") or {}
        bot_username = str(result.get("username") or "")
        if not info.get("ok") or not bot_username:
            print("Bot token 검증에 실패했습니다.", file=sys.stderr)
            return 2
        print(f"Bot 확인: @{bot_username}")
        offset = _latest_offset(token)
        user_id, chat_id = _wait_for_owner(token, offset, args.timeout)
        _write_env(Path(args.env_file), token, user_id, chat_id, bot_username)
        print(f"설정 완료: {args.env_file}")
        print(
            json.dumps(
                {
                    "has_token": True,
                    "allowed_configured": True,
                    "bot": f"@{bot_username}",
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"설정 실패: {exc.__class__.__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
