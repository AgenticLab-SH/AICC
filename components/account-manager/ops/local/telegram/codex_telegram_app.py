"""Telegram-facing non-interactive Codex App account commands.

The Windows-native Codex Telegram bot calls this module. It reuses the cm
account store/order and performs App account switches without opening the TUI.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LOCAL_ROOT = Path(__file__).resolve().parent.parent
if str(LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCAL_ROOT))

from codex_multi import (
    CODEX_HOME,
    fetch_quota,
    format_quota,
    get_active_account,
    get_auth_path,
    get_cli_accounts,
    get_expiry,
    list_accounts,
    read_auth,
)
from codex_notify import account_email, notify_account_change

HERE = Path(__file__).resolve().parent
WRAPPER = HERE / "codex_telegram_app.cmd"
MAX_ACCOUNT_COMMANDS = 12
ACCOUNT_WIDTH = 16


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _strip_gmail(label: str) -> str:
    return label[:-10] if label.lower().endswith("@gmail.com") else label


def _fit(text: str, width: int) -> str:
    value = _strip_gmail(str(text or "?"))
    if len(value) > width:
        value = value[: max(1, width - 1)] + "~"
    return value.ljust(width)


def _pct(value) -> str:
    if value is None or value == "?":
        return " ? "
    try:
        return f"{int(value):>2}%"
    except (TypeError, ValueError):
        return " ? "


def _reset(value) -> str:
    text = str(value or "?")
    if "d" in text:
        match = re.match(r"(\d+d)(\d+)h", text)
        if match:
            text = f"{match.group(1)}{match.group(2)}h"
    else:
        text = text.rstrip("m")
    if len(text) > 6:
        text = text[:6]
    return text.rjust(6)


def _expiry_status(name: str) -> str:
    expiry = get_expiry(name)
    if not expiry:
        return "-"
    return expiry[5:] if len(expiry) == 10 else expiry[:8]


def _plain_account_label(name: str) -> str:
    auth = read_auth(name)
    return account_email(name, auth)


def _live_app_auth() -> dict | None:
    path = CODEX_HOME / "auth.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _current_app_label() -> str:
    active = get_active_account()
    if active:
        return _plain_account_label(active)
    return account_email("unknown", _live_app_auth())


def _quota_rows(accounts: list[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}

    def load_one(account_name: str) -> tuple[str, dict]:
        auth = read_auth(account_name)
        if not auth:
            return account_name, format_quota({"ok": False, "error": "no_auth"})
        return account_name, format_quota(fetch_quota(auth))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(load_one, name): name for name in accounts}
        for future in as_completed(futures):
            name = futures[future]
            try:
                rows[name] = future.result()[1]
            except Exception as exc:
                rows[name] = format_quota({"ok": False, "error": type(exc).__name__})
    return rows


def _row_status(q: dict) -> str:
    if q.get("expired"):
        return "만료"
    if q.get("error"):
        return "ERR"
    return "OK"


def _kill_codex_app() -> bool:
    killed = False
    probe = (
        "Get-Process -Name 'Codex' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -match 'WindowsApps' } | Measure-Object | "
        "Select-Object -ExpandProperty Count"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", probe],
            capture_output=True,
            text=True,
            timeout=5,
        )
        killed = int((result.stdout or "0").strip() or "0") > 0
    except Exception:
        killed = False

    commands = [
        "Get-Process -Name 'Codex' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -match 'WindowsApps' } | Stop-Process -Force",
        "Get-Process -Name 'codex' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -match 'OpenAI' } | Stop-Process -Force",
    ]
    for command in commands:
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    return killed


def _wait_codex_app_exit(timeout: int = 10) -> None:
    probe = (
        "Get-Process -Name 'Codex' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -match 'WindowsApps' } | Measure-Object | "
        "Select-Object -ExpandProperty Count"
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", probe],
                capture_output=True,
                text=True,
                timeout=5,
            )
            count = (result.stdout or "").strip()
            if count in {"", "0"}:
                return
        except Exception:
            return
        time.sleep(0.25)


def _start_codex_app() -> None:
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Start-Process 'shell:AppsFolder\\OpenAI.Codex_2p2nqsd0c76g0!App'",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def list_for_telegram() -> str:
    accounts = list_accounts()
    if not accounts:
        return "등록된 Codex 계정이 없습니다. PC에서 cm add를 먼저 실행하세요."

    shown_accounts = accounts[:MAX_ACCOUNT_COMMANDS]
    active = get_active_account()
    cli_active = get_cli_accounts()
    quotas = _quota_rows(shown_accounts)
    current = _strip_gmail(_current_app_label())
    lines = [
        "[Codex App] 계정/사용량",
        f"현재 App: {current}",
        "표시: A=App 활성, C=CLI 실행",
        "",
        "```",
        "No AC 계정             플랜  5h  5h리셋 주간 주리셋  만료   상태",
        "-- -- ---------------- ---- --- ------ --- ------ ------ ----",
    ]
    for idx, name in enumerate(shown_accounts, 1):
        label = _fit(_plain_account_label(name), ACCOUNT_WIDTH)
        app_mark = "A" if name == active else "-"
        cli_mark = "C" if name in cli_active else "-"
        q = quotas.get(name, format_quota({"ok": False, "error": "missing"}))
        plan = str(q.get("plan") or "?")[:4].ljust(4)
        if q.get("expired"):
            r5 = "만료"
            w5 = "  -  "
            rw = "만료"
            ww = "  -  "
        else:
            r5 = _pct(q.get("5h_remain"))
            w5 = _reset(q.get("5h_reset"))
            rw = _pct(q.get("wk_remain"))
            ww = _reset(q.get("wk_reset"))
        exp = _expiry_status(name).ljust(6)
        status = _row_status(q).ljust(4)
        lines.append(
            f"{idx:>2} {app_mark}{cli_mark} {label} {plan} "
            f"{r5} {w5} {rw} {ww} {exp} {status}"
        )
    lines.extend([
        "```",
        "",
        "전환: /ca <번호>  예: /ca 2",
        "상태: /codexapp status",
        "도움말: /codexapp help",
    ])
    if len(accounts) > MAX_ACCOUNT_COMMANDS:
        lines.append(f"... {len(accounts) - MAX_ACCOUNT_COMMANDS}개는 생략됨")
    return "\n".join(lines)


def status_for_telegram() -> str:
    active = get_active_account()
    current = _strip_gmail(_current_app_label())
    lines = [
        "[Codex App] 현재 상태",
        f"App 계정: {current}",
    ]
    if active:
        q = _quota_rows([active]).get(active, {})
        lines.extend(
            [
                f"플랜: {q.get('plan') or '?'}",
                f"5h 잔여: {_pct(q.get('5h_remain')).strip()} / 리셋: {q.get('5h_reset') or '?'}",
                f"주간 잔여: {_pct(q.get('wk_remain')).strip()} / 리셋: {q.get('wk_reset') or '?'}",
                f"만료일: {get_expiry(active) or '-'}",
                f"상태: {_row_status(q)}",
            ]
        )
    cli_accounts = sorted(_strip_gmail(_plain_account_label(name)) for name in get_cli_accounts())
    lines.append(f"CLI 실행 계정: {', '.join(cli_accounts) if cli_accounts else '-'}")
    lines.append("목록: /codexapp")
    return "\n".join(lines)


def help_for_telegram() -> str:
    return "\n".join(
        [
            "[Codex App] 명령어",
            "/codexapp - 계정/사용량 표",
            "/codexapp status - 현재 App 계정 상세",
            "/codexapp usage - 사용량 표 새로고침",
            "/codexapp help - 도움말",
            "/ca <번호> - 표 번호로 App 전환",
            "예: /ca 2",
            "",
            "텍스트 별칭도 동작합니다: codex app, codex app 2, ca 2",
        ]
    )


def switch_index(index_text: str) -> str:
    accounts = list_accounts()
    try:
        index = int(index_text)
    except ValueError:
        return "사용법: /ca <번호>\n예: /ca 2\n목록: /codexapp"
    if index < 1 or index > len(accounts):
        return "계정 번호가 범위를 벗어났습니다. /codexapp 으로 목록을 확인하세요."
    return switch_account(accounts[index - 1])


def switch_account(target: str) -> str:
    auth_path = get_auth_path(target)
    if not auth_path.exists():
        return f"계정 파일을 찾을 수 없습니다: {target}"

    before = _current_app_label()
    target_auth = read_auth(target)
    target_email = _strip_gmail(account_email(target, target_auth))

    _kill_codex_app()
    _wait_codex_app_exit()
    shutil.copy2(auth_path, CODEX_HOME / "auth.json")
    _start_codex_app()
    time.sleep(1.5)

    notify_account_change("app", target, target_auth)
    return (
        "[Codex App] 계정 전환 완료\n"
        f"이전: {_strip_gmail(before)}\n"
        f"현재 App 계정은 {target_email} 입니다."
    )


def main(argv: list[str]) -> int:
    cmd = argv[1].lower() if len(argv) > 1 else "list"
    try:
        if cmd in {"list", "usage", "table"}:
            print(list_for_telegram())
        elif cmd in {"help", "-h", "--help"}:
            print(help_for_telegram())
        elif cmd in {"status", "current"}:
            print(status_for_telegram())
        elif cmd == "switch-index":
            print(switch_index(argv[2] if len(argv) > 2 else ""))
        elif cmd == "switch":
            print(switch_account(argv[2] if len(argv) > 2 else ""))
        else:
            print("사용법: list | status | switch-index <번호>")
            return 2
        return 0
    except Exception as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
