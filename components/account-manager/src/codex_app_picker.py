"""Quick account picker for launching Codex Desktop App with an isolated account.

The desktop bootstrap reads CODEX_ELECTRON_USER_DATA_PATH before acquiring the
single-instance lock, so a per-account userData directory plus per-account
CODEX_HOME allows separate App windows without changing ~/.codex/auth.json.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from codex_multi import (  # noqa: E402
    C,
    colored,
    ensure_dirs,
    get_active_account,
    launch_app_account,
    list_accounts,
    read_auth,
    resolve_account_selector,
    show_table,
)


def main() -> int:
    ensure_dirs()
    accounts = list_accounts()
    if not accounts:
        print(f"  {colored('등록된 계정 없음. cm add로 추가하세요.', C.RED)}")
        return 1

    raw_args = [arg for arg in sys.argv[1:] if arg != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[1:]
    target = None
    app_args = raw_args

    if raw_args:
        resolved = resolve_account_selector(raw_args[0], accounts, quiet=True)
        if resolved:
            target = resolved
            app_args = raw_args[1:]

    if target is None:
        print()
        show_table(accounts)
        print()
        print(colored("  App으로 열 계정을 선택하세요 (번호/이메일/일부 입력, Enter=현재 활성 계정):", C.WHITE, C.BOLD))
        print()

        try:
            choice = input("  > ").strip()
        except EOFError:
            choice = ""

        if not choice:
            target = get_active_account()
            if not target or not read_auth(target):
                print(f"  {colored('현재 활성 계정을 확인할 수 없습니다.', C.RED)}")
                return 1
        else:
            target = resolve_account_selector(choice, accounts)
            if target is None:
                return 1

    launch_app_account(target, app_args, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
