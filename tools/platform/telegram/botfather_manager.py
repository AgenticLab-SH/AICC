"""Guarded BotFather inventory, creation, and deletion through Whale CDP.

Secrets are written directly to a credential file and are never returned in
stdout. The caller must validate the CDP endpoint before invoking this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Locator, Page, sync_playwright

from botfather_menu_audit import BOT_USERNAME_PATTERN, open_verified_botfather


OWNED_PAGE_MARKER = "aicc-telegram-bot-manager"
TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{25,}\b")


def send(page: Page, text: str) -> None:
    composer = page.locator(".Composer [contenteditable=true]:visible").last
    composer.fill(text)
    composer.press("Enter")


def button_labels(message: Locator) -> list[str]:
    labels: list[str] = []
    buttons = message.locator("button")
    for index in range(buttons.count()):
        label = (buttons.nth(index).inner_text() or "").strip()
        if label:
            labels.append(label)
    return labels


def wait_for_message(
    page: Page,
    baseline: int,
    predicate: Callable[[str, list[str]], bool],
    timeout_ms: int,
) -> tuple[Locator, str, list[str]]:
    deadline = time.monotonic() + timeout_ms / 1000
    messages = page.locator(".Message")
    while time.monotonic() < deadline:
        count = messages.count()
        for index in range(count - 1, baseline - 1, -1):
            message = messages.nth(index)
            try:
                text = (message.inner_text() or "").strip()
                labels = button_labels(message)
            except Exception:
                continue
            if predicate(text, labels):
                return message, text, labels
        page.wait_for_timeout(250)
    raise RuntimeError("botfather_response_timeout")


def exact_button(message: Locator, label: str) -> Locator:
    pattern = re.compile(rf"^{re.escape(label)}$")
    button = message.locator("button").filter(has_text=pattern)
    if button.count() == 0:
        raise RuntimeError(f"button_missing:{label}")
    return button.last


def wait_for_latest_button(page: Page, label: str, timeout_ms: int) -> Locator:
    deadline = time.monotonic() + timeout_ms / 1000
    messages = page.locator(".Message")
    while time.monotonic() < deadline:
        candidate = messages.last
        try:
            if label in button_labels(candidate):
                return candidate
        except Exception:
            pass
        page.wait_for_timeout(250)
    raise RuntimeError(f"button_response_timeout:{label}")


def open_owned_page(endpoint: str, timeout_ms: int):
    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
    if not browser.contexts:
        playwright.stop()
        raise RuntimeError("cdp_context_missing")
    context = browser.contexts[0]
    for existing in list(context.pages):
        try:
            if existing.evaluate("window.name") == OWNED_PAGE_MARKER:
                existing.close()
        except Exception:
            continue
    page = context.new_page()
    page.evaluate(f"window.name={json.dumps(OWNED_PAGE_MARKER)}")
    page.set_viewport_size({"width": 1400, "height": 900})
    open_verified_botfather(page, timeout_ms)
    return playwright, page


def latest_bot_list(page: Page, timeout_ms: int) -> tuple[Locator, list[str]]:
    messages = page.locator(".Message")
    baseline = messages.count()
    send(page, "/mybots")
    message, _, labels = wait_for_message(
        page,
        baseline,
        lambda _text, values: any(BOT_USERNAME_PATTERN.fullmatch(value) for value in values),
        timeout_ms,
    )
    bots = sorted({value for value in labels if BOT_USERNAME_PATTERN.fullmatch(value)}, key=str.casefold)
    return message, bots


def next_bot_page(page: Page, message: Locator, timeout_ms: int) -> tuple[Locator, list[str]] | None:
    labels = button_labels(message)
    if "»" not in labels:
        return None
    previous_bots = {value for value in labels if BOT_USERNAME_PATTERN.fullmatch(value)}
    exact_button(message, "»").click()
    deadline = time.monotonic() + timeout_ms / 1000
    messages = page.locator(".Message")
    while time.monotonic() < deadline:
        candidate = messages.last
        try:
            next_labels = button_labels(candidate)
        except Exception:
            page.wait_for_timeout(250)
            continue
        next_bots = {value for value in next_labels if BOT_USERNAME_PATTERN.fullmatch(value)}
        if next_bots and next_bots != previous_bots:
            return candidate, sorted(next_bots, key=str.casefold)
        page.wait_for_timeout(250)
    raise RuntimeError("botfather_pagination_timeout")


def all_bot_pages(page: Page, timeout_ms: int) -> tuple[list[str], int]:
    message, bots = latest_bot_list(page, timeout_ms)
    all_bots = set(bots)
    page_count = 1
    for _ in range(20):
        following = next_bot_page(page, message, timeout_ms)
        if following is None:
            break
        message, bots = following
        before = len(all_bots)
        all_bots.update(bots)
        page_count += 1
        if len(all_bots) == before and "»" in button_labels(message):
            raise RuntimeError("botfather_pagination_loop")
    return sorted(all_bots, key=str.casefold), page_count


def find_bot_page(page: Page, bot_username: str, timeout_ms: int) -> tuple[Locator, list[str]]:
    message, bots = latest_bot_list(page, timeout_ms)
    for _ in range(20):
        if bot_username in bots:
            return message, bots
        following = next_bot_page(page, message, timeout_ms)
        if following is None:
            break
        message, bots = following
    raise RuntimeError("bot_not_owned_or_missing")


def list_bots(page: Page, timeout_ms: int) -> dict[str, object]:
    bots, page_count = all_bot_pages(page, timeout_ms)
    return {
        "ok": True,
        "verified_botfather": True,
        "bots": bots,
        "bot_count": len(bots),
        "page_count": page_count,
    }


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_credentials(path: Path, token: str, preserve_from: Path | None) -> None:
    preserved = parse_env(preserve_from) if preserve_from else {}
    kept = {
        key: value
        for key, value in preserved.items()
        if "TOKEN" not in key.upper()
    }
    ordered: list[tuple[str, str]] = [
        ("AI_CONTROL_TELEGRAM_BOT_TOKEN", token),
        ("TELEGRAM_BOT_TOKEN", token),
        ("CODEX_TELEGRAM_BOT_TOKEN", token),
    ]
    ordered.extend(sorted(kept.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text("".join(f"{key}={value}\n" for key, value in ordered), encoding="utf-8")
    os.replace(temporary, path)


def create_bot(
    page: Page,
    display_name: str,
    candidates: list[str],
    credential_file: Path,
    preserve_from: Path | None,
    timeout_ms: int,
) -> dict[str, object]:
    if credential_file.exists():
        raise RuntimeError("credential_file_already_exists")
    messages = page.locator(".Message")
    baseline = messages.count()
    send(page, "/newbot")
    wait_for_message(page, baseline, lambda text, _labels: "new bot" in text.casefold(), timeout_ms)

    baseline = messages.count()
    send(page, display_name)
    wait_for_message(page, baseline, lambda text, _labels: "username" in text.casefold(), timeout_ms)

    chosen = ""
    token = ""
    attempted: list[str] = []
    for candidate in candidates:
        if not BOT_USERNAME_PATTERN.fullmatch("@" + candidate) or not candidate.casefold().endswith("bot"):
            raise RuntimeError(f"invalid_username_candidate:{candidate}")
        attempted.append(candidate)
        baseline = messages.count()
        send(page, candidate)
        _, reply, _ = wait_for_message(
            page,
            baseline,
            lambda text, _labels: bool(TOKEN_PATTERN.search(text))
            or "sorry" in text.casefold()
            or "invalid" in text.casefold(),
            timeout_ms,
        )
        match = TOKEN_PATTERN.search(reply)
        if match:
            chosen = candidate
            token = match.group(0)
            break
    if not token:
        raise RuntimeError("no_available_username_candidate")

    write_credentials(credential_file, token, preserve_from)
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    token = ""
    return {
        "ok": True,
        "verified_botfather": True,
        "username": chosen,
        "display_name": display_name,
        "attempted_usernames": attempted,
        "credential_file": str(credential_file),
        "token_fingerprint": fingerprint,
        "token_exposed": False,
    }


def delete_bot(page: Page, bot_username: str, timeout_ms: int) -> dict[str, object]:
    list_message, bots = find_bot_page(page, bot_username, timeout_ms)
    exact_button(list_message, bot_username).click()
    menu = wait_for_latest_button(page, "Delete Bot", timeout_ms)
    exact_button(menu, "Delete Bot").click()

    confirm_message = wait_for_latest_button(page, "Yes, delete the bot", timeout_ms)
    exact_button(confirm_message, "Yes, delete the bot").click()

    final_message = wait_for_latest_button(page, "Yes, I'm 100% sure!", timeout_ms)
    messages = page.locator(".Message")
    exact_button(final_message, "Yes, I'm 100% sure!").click()
    deadline = time.monotonic() + timeout_ms / 1000
    deleted_reply_seen = False
    while time.monotonic() < deadline:
        try:
            text = (messages.last.inner_text() or "").casefold()
        except Exception:
            page.wait_for_timeout(250)
            continue
        if "done" in text or "deleted" in text:
            deleted_reply_seen = True
            break
        page.wait_for_timeout(250)
    if not deleted_reply_seen:
        raise RuntimeError("delete_result_timeout")
    remaining, _ = all_bot_pages(page, timeout_ms)
    if bot_username in remaining:
        raise RuntimeError("delete_verification_failed")
    return {
        "ok": True,
        "verified_botfather": True,
        "deleted_bot": bot_username,
        "post_delete_verified": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Telegram bots through verified BotFather on Whale CDP.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--timeout-sec", type=int, default=60)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    create = sub.add_parser("create")
    create.add_argument("--display-name", required=True)
    create.add_argument("--username", action="append", required=True)
    create.add_argument("--credential-file", type=Path, required=True)
    create.add_argument("--preserve-from", type=Path)
    delete = sub.add_parser("delete")
    delete.add_argument("--bot-username", action="append", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timeout_ms = max(10, args.timeout_sec) * 1_000
    playwright = None
    page = None
    try:
        playwright, page = open_owned_page(args.endpoint, timeout_ms)
        if args.action == "list":
            result = list_bots(page, timeout_ms)
        elif args.action == "create":
            result = create_bot(
                page,
                args.display_name,
                args.username,
                args.credential_file,
                args.preserve_from,
                timeout_ms,
            )
        else:
            deleted: list[str] = []
            for bot_username in args.bot_username:
                if not BOT_USERNAME_PATTERN.fullmatch(bot_username):
                    raise RuntimeError("invalid_bot_username")
                delete_bot(page, bot_username, timeout_ms)
                deleted.append(bot_username)
            result = {
                "ok": True,
                "verified_botfather": True,
                "deleted_bots": deleted,
                "deleted_count": len(deleted),
                "post_delete_verified": True,
            }
        result["owned_tab_closed"] = True
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "token_exposed": False}, ensure_ascii=False))
        return 2
    finally:
        if page is not None and not page.is_closed():
            page.close()
        if playwright is not None:
            playwright.stop()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
