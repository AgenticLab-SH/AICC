"""Windows-native Telegram bot for Codex App account commands.

This intentionally does not depend on Hermes or WSL. It polls Telegram Bot API
directly and dispatches a small command set to codex_telegram_app.py helpers.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

LOCAL_ROOT = Path(__file__).resolve().parent.parent
if str(LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCAL_ROOT))

import codex_multi
from codex_telegram_common import allowed_users, api_request, bot_token, load_config, send_message

HERE = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = Path.home() / ".codex" / "telegram.env"
POLL_TIMEOUT = 25

_STOP = False


# Under pythonw.exe (scheduled task) there is no console: stdout/stderr are None,
# so any print()/traceback would raise AttributeError and kill the poller.
# Redirect to a rotating-ish log file instead.
if sys.stdout is None or sys.stderr is None:
    _logf = open(HERE / "telegram_bot.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _logf
    if sys.stderr is None:
        sys.stderr = _logf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _handle_stop(_signum, _frame) -> None:
    global _STOP
    _STOP = True


# Legacy sub-command words mapped onto unified cm commands.
_SUBMAP = {
    "status": ["status"], "현재": ["status"], "상태": ["status"],
    "list": ["status"], "usage": ["status"], "table": ["status"],
    "목록": ["status"], "사용량": ["status"],
    "help": ["help"], "도움말": ["help"], "h": ["help"], "?": ["help"],
}


def _map_app_sub(sub: list[str]) -> list[str]:
    """Map legacy /codexapp <sub> onto unified cm args."""
    if not sub:
        return ["status"]
    first = sub[0].lower()
    if first in _SUBMAP:
        return _SUBMAP[first]
    if first.isdigit():
        return ["switch", first]
    return ["status"]


def to_cm_args(text: str) -> list[str] | None:
    """Translate an incoming Telegram message into `cm` argument list.

    Recognized forms (all resolve to the same commands the terminal uses):
      cm <args> / /cm <args>      → run that cm command
      <command> [args]            → any registered cm command (e.g. 'status', 'switch 2')
      /ca <번호> / ca <번호>       → cm switch <번호>   (legacy switch alias)
      /codexapp [sub] / codex app → cm status / switch / help (legacy aliases)
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        raw = raw[1:].strip()
    words = raw.split()
    if not words:
        return None
    head = words[0].lower()

    if head == "cm":
        return words[1:] if len(words) > 1 else ["status"]
    if head == "ca":
        return (["switch"] + words[1:]) if len(words) > 1 else ["status"]
    if head == "codexapp":
        return _map_app_sub(words[1:])
    if head in {"codex", "코덱스"} and len(words) >= 2 and words[1].lower() in {"app", "앱"}:
        return _map_app_sub(words[2:])
    if head in {"start", "menu", "메뉴", "도움말", "help", "?", "h"}:
        return ["help"]
    if codex_multi.find_command(head):
        return words
    return None


def dispatch(text: str):
    """Return (reply_text, parse_mode) or None to ignore the message."""
    args = to_cm_args(text)
    if args is None:
        return None
    entry = codex_multi.find_command(args[0])
    is_status = bool(entry) and "status" in entry["names"]
    is_switch = bool(entry) and "switch" in entry["names"]
    if is_status:
        return codex_multi.render_status_telegram(), "HTML"
    if is_switch and len(args) < 2:
        reply = (
            "전환할 번호를 보내세요. 예: cm switch 2\n\n"
            + codex_multi.render_status_telegram()
        )
        return reply, "HTML"
    # help / confirmations / diagnostics → readable wrapped plain text
    return codex_multi.render_command_output(args), None


def process_update(token: str, allow: set[str], update: dict) -> None:
    message = update.get("message") or update.get("edited_message") or {}
    if not message:
        return
    text = str(message.get("text") or "").strip()
    if not text:
        return

    sender = message.get("from") or {}
    user_id = str(sender.get("id") or "")
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if allow and "*" not in allow and user_id not in allow and chat_id not in allow:
        return

    result = dispatch(text)
    if result is None:
        return
    reply, parse_mode = result
    send_message(token, chat_id, reply, reply_to=message.get("message_id"), parse_mode=parse_mode)


def run_once(token: str, allow: set[str], offset: int | None = None) -> int | None:
    params: dict[str, int] = {"timeout": 0, "limit": 25}
    if offset is not None:
        params["offset"] = offset
    data = api_request(token, "getUpdates", params, timeout=15)
    next_offset = offset
    for update in data.get("result", []):
        next_offset = int(update["update_id"]) + 1  # advance first (no poison-block)
        try:
            process_update(token, allow, update)
        except Exception as exc:
            print(f"process_update error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    return next_offset


def run_forever() -> int:
    config = load_config()
    token = bot_token(config)
    if not token:
        print(
            f"CODEX_TELEGRAM_BOT_TOKEN is missing. Configure {DEFAULT_ENV_FILE}.",
            file=sys.stderr,
        )
        return 2
    allow = allowed_users(config)
    try:
        offset = run_once(token, allow)
    except Exception as exc:
        print(f"initial getUpdates failed: {exc.__class__.__name__}", file=sys.stderr)
        offset = None
    print("Codex Telegram bot started.")
    while not _STOP:
        try:
            params: dict[str, int] = {"timeout": POLL_TIMEOUT, "limit": 25}
            if offset is not None:
                params["offset"] = offset
            data = api_request(token, "getUpdates", params, timeout=POLL_TIMEOUT + 10)
        except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Telegram polling error: {exc.__class__.__name__}", file=sys.stderr)
            time.sleep(5)
            continue
        except Exception as exc:  # never let the poller die
            print(f"Telegram poll unexpected: {exc.__class__.__name__}: {exc}", file=sys.stderr)
            time.sleep(5)
            continue
        for update in data.get("result", []):
            offset = int(update["update_id"]) + 1  # advance before processing
            try:
                process_update(token, allow, update)
            except Exception as exc:
                print(f"process_update error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    print("Codex Telegram bot stopped.")
    return 0


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    config = load_config()
    token = bot_token(config)
    allow = allowed_users(config)
    if len(argv) > 1 and argv[1] == "once":
        if not token:
            print(
                f"CODEX_TELEGRAM_BOT_TOKEN is missing. Configure {DEFAULT_ENV_FILE}.",
                file=sys.stderr,
            )
            return 2
        run_once(token, allow)
        return 0
    if len(argv) > 1 and argv[1] == "probe":
        print(
            json.dumps(
                {"has_token": bool(token), "allowed_configured": bool(allow)},
                ensure_ascii=False,
            )
        )
        return 0
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
