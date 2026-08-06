"""Quick account picker for `codex cm`.
Shows accounts table, user picks a number, codex launches with that account.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from codex_multi import (
    list_accounts, show_table, setup_isolated_home, record_cli_session,
    remove_cli_session, colored, C, ensure_dirs, CODEX_HOME, get_active_account,
    read_auth, resolve_account_selector
)
import cm_integrations
import subprocess

# Real codex binary (not this wrapper). Resolved from user config or PATH, and
# never a path baked in at build time.
REAL_CODEX = cm_integrations.real_codex_command() or "codex"


def read_live_app_auth() -> dict | None:
    auth_file = CODEX_HOME / "auth.json"
    if not auth_file.exists():
        return None
    try:
        return json.loads(auth_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def launch_account(target: str, remaining: list[str]) -> int:
    home = setup_isolated_home(target)

    print(f"\n  {colored('→', C.GREEN)} {target}\n", flush=True)

    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    env.pop("OPENAI_API_KEY", None)

    # Launch codex directly via .cmd (bypasses our wrapper)
    proc = subprocess.Popen([REAL_CODEX] + remaining, env=env)
    record_cli_session(target, proc.pid)
    proc.wait()
    remove_cli_session(proc.pid)
    return proc.returncode


def main():
    ensure_dirs()
    accounts = list_accounts()

    if not accounts:
        print(f"  {colored('등록된 계정 없음. cm add로 추가하세요.', C.RED)}")
        sys.exit(1)

    print()
    # Remaining args (anything after cm flag)
    remaining = sys.argv[1:]
    target = None
    if remaining:
        resolved = resolve_account_selector(remaining[0], accounts, quiet=True)
        if resolved:
            target = resolved
            remaining = remaining[1:]

    if target:
        sys.exit(launch_account(target, remaining))

    show_table(accounts)
    print()
    print(colored("  계정을 선택하세요 (번호/이메일/일부 입력, Enter=현재 활성 계정으로 실행):", C.WHITE, C.BOLD))
    print()

    try:
        choice = input("  > ").strip()
    except EOFError:
        choice = ""

    if not choice:
        # Enter = run with current active account in its isolated CLI home.
        active = get_active_account()
        if active and read_auth(active):
            sys.exit(launch_account(active, remaining))
        os.execv(REAL_CODEX, [REAL_CODEX] + remaining)
        return

    target = resolve_account_selector(choice, accounts)
    if target is None:
        sys.exit(1)
    sys.exit(launch_account(target, remaining))


if __name__ == "__main__":
    main()
