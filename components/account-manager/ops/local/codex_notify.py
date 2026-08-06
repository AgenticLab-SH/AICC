"""Notification helpers for Codex multi-account switches.

Uses Codex's Windows-native Telegram configuration without exposing bot
secrets to logs. Failures are non-fatal so account switching still works.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

_TELEGRAM_ROOT = Path(__file__).resolve().parent / "telegram"
sys.path.insert(0, str(_TELEGRAM_ROOT))
from codex_telegram_common import send_configured_message


KST = timezone(timedelta(hours=9))
USAGE_API = "https://chatgpt.com/backend-api/wham/usage"
USAGE_USER_AGENT = "Codex Multi-Account Manager/1.0"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def token_email(auth_data: dict | None) -> str | None:
    """Resolve the email for the actual auth token, matching cm TUI usage lookup."""
    if not auth_data:
        return None

    token = auth_data.get("tokens", {}).get("access_token")
    if not token:
        return None

    req = Request(USAGE_API)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USAGE_USER_AGENT)
    try:
        proxy = os.environ.get("CM_USAGE_PROXY", "").strip()
        if proxy.lower() in ("direct", "none", "off", "no"):
            opener = build_opener(ProxyHandler({}))
            response_ctx = opener.open(req, timeout=10)
        elif proxy and proxy.lower() not in ("system", "default", "auto"):
            opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
            response_ctx = opener.open(req, timeout=10)
        else:
            response_ctx = urlopen(req, timeout=10)
        with response_ctx as resp:
            data = json.loads(resp.read().decode())
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return None

    email = data.get("email")
    return email if isinstance(email, str) and "@" in email else None


def account_email(account: str | None, auth_data: dict | None = None) -> str:
    """Return the token email first, then local metadata/account label fallback."""
    if auth_data:
        email = token_email(auth_data)
        if email:
            return email
        for key in ("email", "account_email", "user_email"):
            value = auth_data.get(key)
            if isinstance(value, str) and "@" in value:
                return value
        user = auth_data.get("user")
        if isinstance(user, dict):
            value = user.get("email")
            if isinstance(value, str) and "@" in value:
                return value
    if account and "@" in account:
        return account
    return account or "unknown"


def build_account_message(
    surface: str,
    account: str,
    auth_data: dict | None = None,
    pid: int | None = None,
) -> str:
    email = account_email(account, auth_data)
    normalized = surface.lower()
    if normalized == "app":
        title = "[Codex App] 계정 전환 완료"
        account_line = f"현재 App 계정은 {email} 입니다."
    elif normalized == "cli":
        title = "[Codex CLI] 계정 활성화"
        account_line = f"현재 CLI 계정은 {email} 입니다."
    else:
        title = "[Codex] 계정 상태 변경"
        account_line = f"현재 계정은 {email} 입니다."

    lines = [
        title,
        account_line,
        f"시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}",
        f"호스트: {socket.gethostname()}",
    ]
    if pid is not None:
        lines.append(f"PID: {pid}")
    return "\n".join(lines)


def send_codex_telegram(text: str, timeout: int = 15) -> tuple[bool, str]:
    """Send a Telegram message using Codex's dedicated Telegram config."""
    if os.environ.get("CODEX_MULTI_NOTIFY", "1") == "0":
        return True, "disabled"
    if os.environ.get("CODEX_MULTI_NOTIFY_DRY_RUN") == "1":
        return True, "dry-run"
    try:
        return send_configured_message(text, timeout=timeout)
    except Exception as exc:
        return False, exc.__class__.__name__


def notify_account_change(
    surface: str,
    account: str,
    auth_data: dict | None = None,
    pid: int | None = None,
) -> bool:
    text = build_account_message(surface, account, auth_data, pid)
    ok, reason = send_codex_telegram(text)
    if not ok:
        print(f"  [notify] Telegram 알림 실패: {reason}", file=sys.stderr)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex account Telegram notifier")
    parser.add_argument("--surface", choices=("app", "cli", "codex"), default="codex")
    parser.add_argument("--account", default="test@example.com")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text = build_account_message(args.surface, args.account, pid=args.pid)
    if args.dry_run:
        print(json.dumps({"ok": True, "mode": "dry-run", "text": text}, ensure_ascii=False))
        return 0
    ok, reason = send_codex_telegram(text)
    print(json.dumps({"ok": ok, "reason": reason}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
