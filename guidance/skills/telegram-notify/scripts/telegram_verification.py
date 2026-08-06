#!/usr/bin/env python3
"""Correlation-bound Telegram readiness and OTP transport.

Credential values and OTPs are never persisted or logged. The helper allows a
single active request and stores only non-secret correlation state in a 0700
temporary directory. JSON output is intentionally compact and redacted except
that poll-code returns the ephemeral code required by the active task.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
import urllib.error
from pathlib import Path


AICC_STATE_ROOT = Path(
    os.environ.get("AICC_STATE_ROOT", Path.home() / ".ai-control-center")
).expanduser()
ENV_FILE = Path(
    os.environ.get(
        "AICC_TELEGRAM_ENV_FILE", AICC_STATE_ROOT / "telegram" / "agent-bridge.env"
    )
).expanduser()
STATE_ROOT = AICC_STATE_ROOT / "telegram" / "verification-state"
MAX_WAIT_SECONDS = 45
MAX_STATE_AGE_SECONDS = 2 * 60 * 60
ORPHAN_MARKER_GRACE_SECONDS = 30
CODE_RE = re.compile(r"^\s*([0-9]{4,8})\s*$")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram_client as telegram  # noqa: E402


class SafeError(RuntimeError):
    pass


def emit(**values: object) -> None:
    print(json.dumps(values, ensure_ascii=False, separators=(",", ":")))


def fail(status: str, message: str, *, exit_code: int = 2) -> int:
    emit(ok=False, status=status, message=message)
    return exit_code


def ensure_state_root() -> None:
    STATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_ROOT, 0o700)


def state_path(request_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{24}", request_id):
        raise SafeError("invalid request id")
    return STATE_ROOT / f"{request_id}.json"


def active_marker_path() -> Path:
    return STATE_ROOT / "active.json"


def release_request(request_id: str) -> None:
    marker = active_marker_path()
    try:
        active = json.loads(marker.read_text(encoding="utf-8"))
        if active.get("request_id") == request_id:
            marker.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass


def reserve_request(request_id: str) -> None:
    ensure_state_root()
    marker = active_marker_path()
    for attempt in range(2):
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            try:
                active = json.loads(marker.read_text(encoding="utf-8"))
                active_id = str(active.get("request_id") or "")
                age = time.time() - float(active.get("created_at") or 0)
                has_state = bool(re.fullmatch(r"[a-f0-9]{24}", active_id)) and state_path(active_id).is_file()
            except (OSError, json.JSONDecodeError, ValueError):
                active_id, age, has_state = "", MAX_STATE_AGE_SECONDS + 1, False
            stale = age > MAX_STATE_AGE_SECONDS or (not has_state and age > ORPHAN_MARKER_GRACE_SECONDS)
            if attempt == 0 and stale:
                marker.unlink(missing_ok=True)
                if active_id and re.fullmatch(r"[a-f0-9]{24}", active_id):
                    state_path(active_id).unlink(missing_ok=True)
                continue
            raise SafeError("another verification request is active") from exc
        try:
            payload = json.dumps({"request_id": request_id, "created_at": time.time()}).encode("utf-8")
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
        return
    raise SafeError("could not reserve verification request")


def read_state(request_id: str) -> dict:
    path = state_path(request_id)
    if not path.is_file():
        raise SafeError("request not found")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeError("request state is unreadable") from exc
    if time.time() - float(state.get("created_at", 0)) > MAX_STATE_AGE_SECONDS:
        path.unlink(missing_ok=True)
        release_request(request_id)
        raise SafeError("request expired locally")
    return state


def write_state(state: dict) -> None:
    ensure_state_root()
    path = state_path(str(state["request_id"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def drain_pending_updates(token: str, state: dict) -> None:
    """Advance past messages that existed before the code prompt was sent."""
    offset = state.get("next_offset")
    for _ in range(10):
        params: dict[str, int] = {"timeout": 0, "limit": 100}
        if offset is not None:
            params["offset"] = int(offset)
        updates = list(api(token, "getUpdates", params).get("result", []))
        if not updates:
            state["next_offset"] = offset
            return
        offset = max(int(item["update_id"]) for item in updates) + 1
        if len(updates) < 100:
            state["next_offset"] = offset
            return
    raise SafeError("too many pending Telegram updates to establish a fresh code boundary")


def config() -> tuple[str, str, set[str]]:
    cfg = telegram.load_config(ENV_FILE)
    token = telegram.bot_token(cfg) or cfg.get("GEMINI_CONNECT_TELEGRAM_BOT_TOKEN", "")
    chats = telegram.default_chat_ids(cfg)
    allowed = telegram.allowed_users(cfg)
    if not token or not chats or not allowed:
        raise SafeError("registered Telegram route is incomplete")
    return token, chats[0], allowed


def api(token: str, method: str, params: dict | None = None, timeout: int = 15) -> dict:
    try:
        return telegram.api_request(token, method, params or {}, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise SafeError("competing Telegram poller detected") from exc
        raise SafeError(f"Telegram API HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SafeError(f"Telegram transport unavailable: {exc.__class__.__name__}") from exc


def assert_polling_available(token: str) -> int | None:
    webhook = api(token, "getWebhookInfo").get("result", {})
    if webhook.get("url"):
        raise SafeError("active Telegram webhook detected")
    updates = api(token, "getUpdates", {"timeout": 0, "limit": 25}).get("result", [])
    return (max(int(item["update_id"]) for item in updates) + 1) if updates else None


def send_button(token: str, chat_id: str, text: str, callback_data: str) -> dict:
    markup = {"inline_keyboard": [[{"text": "지금 가능", "callback_data": callback_data}]]}
    return api(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
            "reply_markup": json.dumps(markup, ensure_ascii=False, separators=(",", ":")),
        },
    ).get("result", {})


def allowed_update(update: dict, allowed: set[str], chat_id: str) -> bool:
    payload = update.get("callback_query") or update.get("message") or {}
    sender = str((payload.get("from") or {}).get("id") or "")
    message = payload.get("message") or payload
    update_chat = str((message.get("chat") or {}).get("id") or "")
    return update_chat == chat_id and ("*" in allowed or sender in allowed or update_chat in allowed)


def poll_updates(token: str, state: dict, wait_seconds: int) -> list[dict]:
    params: dict[str, int] = {"timeout": wait_seconds, "limit": 25}
    if state.get("next_offset") is not None:
        params["offset"] = int(state["next_offset"])
    result = api(token, "getUpdates", params, timeout=wait_seconds + 10)
    updates = list(result.get("result", []))
    if updates:
        state["next_offset"] = max(int(item["update_id"]) for item in updates) + 1
        write_state(state)
    return updates


def command_start(args: argparse.Namespace) -> int:
    token, chat_id, allowed = config()
    offset = assert_polling_available(token)
    request_id = secrets.token_hex(12)
    reserve_request(request_id)
    try:
        nonce = secrets.token_urlsafe(8)
        callback = f"auth_ready:{request_id}:{nonce}"
        message = send_button(
            token,
            chat_id,
            f"{args.site} 로그인 문자 인증이 필요합니다. 인증번호는 보통 {args.expiry_minutes}분 안에 만료됩니다. 지금 바로 문자를 확인할 수 있으면 아래 버튼을 눌러주세요. 버튼 확인 전에는 문자를 발송하지 않습니다.",
            callback,
        )
        state = {
            "request_id": request_id,
            "site": args.site,
            "stage": "waiting_ready",
            "nonce": nonce,
            "next_offset": offset,
            "created_at": time.time(),
            "ready_message_id": message.get("message_id"),
        }
        write_state(state)
    except Exception:
        release_request(request_id)
        raise
    emit(ok=True, status="pending", request_id=request_id, stage=state["stage"])
    return 0


def command_poll_ready(args: argparse.Namespace) -> int:
    token, chat_id, allowed = config()
    state = read_state(args.request_id)
    if state.get("stage") == "ready":
        emit(ok=True, status="ready", request_id=args.request_id)
        return 0
    if state.get("stage") != "waiting_ready":
        return fail("invalid_stage", f"request is in {state.get('stage')}")
    expected = f"auth_ready:{args.request_id}:{state['nonce']}"
    for update in poll_updates(token, state, args.wait_seconds):
        if not allowed_update(update, allowed, chat_id):
            continue
        callback = update.get("callback_query") or {}
        if callback.get("data") != expected:
            continue
        api(token, "answerCallbackQuery", {"callback_query_id": callback["id"], "text": "준비 확인됨"})
        state["stage"] = "ready"
        state["ready_at"] = time.time()
        write_state(state)
        emit(ok=True, status="ready", request_id=args.request_id)
        return 0
    emit(ok=True, status="pending", request_id=args.request_id, stage="waiting_ready")
    return 0


def command_ask_code(args: argparse.Namespace) -> int:
    token, chat_id, _ = config()
    state = read_state(args.request_id)
    if state.get("stage") != "ready":
        return fail("invalid_stage", "matching readiness is required before asking for a code")
    drain_pending_updates(token, state)
    force_reply = {
        "force_reply": True,
        "selective": True,
        "input_field_placeholder": "숫자 인증번호",
    }
    sent = api(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": f"{state['site']} 인증 문자를 발송했습니다. 수신한 숫자 인증번호만 이 메시지에 답장해주세요. 다른 곳에 전달하지 마세요.",
            "disable_web_page_preview": "true",
            "reply_markup": json.dumps(force_reply, ensure_ascii=False, separators=(",", ":")),
        },
    ).get("result", {})
    state["stage"] = "waiting_code"
    state["code_prompt_message_id"] = sent.get("message_id")
    state["code_prompt_at"] = time.time()
    write_state(state)
    emit(ok=True, status="pending", request_id=args.request_id, stage="waiting_code")
    return 0


def command_poll_code(args: argparse.Namespace) -> int:
    token, chat_id, allowed = config()
    state = read_state(args.request_id)
    if state.get("stage") != "waiting_code":
        return fail("invalid_stage", f"request is in {state.get('stage')}")
    prompt_message_id = int(state.get("code_prompt_message_id") or 0)
    if prompt_message_id <= 0:
        return fail("invalid_state", "code prompt correlation is missing")
    for update in poll_updates(token, state, args.wait_seconds):
        if not allowed_update(update, allowed, chat_id):
            continue
        message = update.get("message") or {}
        replied_to = message.get("reply_to_message") or {}
        if int(replied_to.get("message_id") or 0) != prompt_message_id:
            continue
        match = CODE_RE.fullmatch(str(message.get("text") or ""))
        if not match:
            continue
        state["stage"] = "code_delivered"
        state["code_delivered_at"] = time.time()
        write_state(state)
        emit(ok=True, status="code_received", request_id=args.request_id, code=match.group(1))
        return 0
    emit(ok=True, status="pending", request_id=args.request_id, stage="waiting_code")
    return 0


def command_expire(args: argparse.Namespace) -> int:
    token, chat_id, _ = config()
    state = read_state(args.request_id)
    if state.get("stage") not in {"waiting_code", "code_delivered"}:
        return fail("invalid_stage", f"request is in {state.get('stage')}")
    nonce = secrets.token_urlsafe(8)
    callback = f"auth_ready:{args.request_id}:{nonce}"
    message = send_button(
        token,
        chat_id,
        f"{state['site']} 인증번호가 만료되어 다시 진행해야 합니다. 지금 바로 새 문자를 확인할 수 있으면 아래 버튼을 눌러주세요. 준비 확인 후 빠르게 재발송하겠습니다.",
        callback,
    )
    state.pop("code_prompt_message_id", None)
    state.pop("code_prompt_at", None)
    state.pop("code_delivered_at", None)
    state["stage"] = "waiting_ready"
    state["nonce"] = nonce
    state["ready_message_id"] = message.get("message_id")
    state["retry_at"] = time.time()
    write_state(state)
    emit(ok=True, status="pending", request_id=args.request_id, stage="waiting_ready")
    return 0


def command_close(args: argparse.Namespace, stage: str) -> int:
    state = read_state(args.request_id)
    state["stage"] = stage
    state["closed_at"] = time.time()
    state_path(args.request_id).unlink(missing_ok=True)
    release_request(args.request_id)
    emit(ok=True, status=stage, request_id=args.request_id)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Telegram verification response transport")
    commands = result.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--site", required=True)
    start.add_argument("--expiry-minutes", type=int, choices=range(1, 31), default=5)
    for name in ("poll-ready", "poll-code"):
        item = commands.add_parser(name)
        item.add_argument("--request-id", required=True)
        item.add_argument("--wait-seconds", type=int, choices=range(0, MAX_WAIT_SECONDS + 1), default=45)
    for name in ("ask-code", "expire", "finish", "cancel"):
        item = commands.add_parser(name)
        item.add_argument("--request-id", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    handlers = {
        "start": command_start,
        "poll-ready": command_poll_ready,
        "ask-code": command_ask_code,
        "poll-code": command_poll_code,
        "expire": command_expire,
        "finish": lambda value: command_close(value, "finished"),
        "cancel": lambda value: command_close(value, "cancelled"),
    }
    try:
        return handlers[args.command](args)
    except SafeError as exc:
        return fail("blocked", str(exc))
    except Exception as exc:  # redact unexpected transport/config details
        return fail("error", exc.__class__.__name__, exit_code=1)


if __name__ == "__main__":
    raise SystemExit(main())
