"""Inspect the verified BotFather edit menu through an existing Whale CDP session.

The script intentionally reads only button labels needed to determine which
configuration actions BotFather currently exposes. It never reads tokens,
cookies, profile databases, or arbitrary message bodies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from playwright.sync_api import Locator, Page, sync_playwright


OWNED_PAGE_MARKER = "aicc-botfather-menu-audit"
BOT_USERNAME_PATTERN = re.compile(r"^@[A-Za-z0-9_]{5,32}$")


def visible_exact(page: Page, text: str) -> list[Locator]:
    locator = page.get_by_text(text, exact=True)
    return [locator.nth(index) for index in range(locator.count()) if locator.nth(index).is_visible()]


def exact_button(page: Page, text: str) -> Locator:
    pattern = re.compile(rf"^{re.escape(text)}$")
    locator = page.locator(".Message button:visible").filter(has_text=pattern)
    if locator.count() == 0:
        raise RuntimeError(f"button_missing:{text}")
    return locator.last


def open_verified_botfather(page: Page, timeout_ms: int) -> None:
    page.goto("https://web.telegram.org/a/", wait_until="domcontentloaded", timeout=timeout_ms)
    phone_input = page.locator("input[type=tel]")
    search = page.locator("input[placeholder*='Search'], input[placeholder*='검색']").first
    if phone_input.count() > 0:
        raise RuntimeError("telegram_login_required")
    search.wait_for(state="visible", timeout=timeout_ms)
    search.fill("BotFather")
    page.wait_for_timeout(4_000)

    exact_name = page.locator("h3.fullName:visible").filter(has_text=re.compile(r"^BotFather$"))
    verified: list[Locator] = []
    for index in range(exact_name.count()):
        candidate = exact_name.nth(index)
        if candidate.is_visible() and candidate.locator("xpath=..").locator("svg.VerifiedIcon").count() > 0:
            verified.append(candidate)
    if not verified:
        raise RuntimeError("verified_botfather_missing")

    # Telegram keeps invisible and chat-list duplicates in the DOM. The last
    # visible verified exact result is the global-search result observed in /a/.
    verified[-1].click()
    page.wait_for_timeout(2_000)
    if page.locator(".Composer [contenteditable=true]:visible").count() == 0:
        raise RuntimeError("botfather_composer_missing")


def inspect_menu(endpoint: str, bot_username: str, timeout_ms: int) -> dict[str, Any]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
        if not browser.contexts:
            raise RuntimeError("cdp_context_missing")
        context = browser.contexts[0]

        # Clean only pages explicitly marked by a prior interrupted run.
        for existing in list(context.pages):
            try:
                if existing.evaluate("window.name") == OWNED_PAGE_MARKER:
                    existing.close()
            except Exception:
                continue

        page = context.new_page()
        try:
            page.evaluate(f"window.name={json.dumps(OWNED_PAGE_MARKER)}")
            page.set_viewport_size({"width": 1400, "height": 900})
            open_verified_botfather(page, timeout_ms)

            composer = page.locator(".Composer [contenteditable=true]:visible").last
            composer.fill("/mybots")
            composer.press("Enter")
            page.wait_for_timeout(2_500)

            exact_button(page, bot_username).click()
            page.wait_for_timeout(2_200)
            exact_button(page, "Edit Bot").click()
            page.wait_for_timeout(2_500)

            edit_name = page.locator(".Message button:visible").filter(has_text=re.compile(r"^Edit Name$"))
            if edit_name.count() == 0:
                raise RuntimeError("edit_bot_menu_missing")
            menu_message = edit_name.last.locator("xpath=ancestor::*[contains(@class,'Message')][1]")
            if menu_message.count() == 0:
                raise RuntimeError("edit_bot_menu_container_missing")

            labels: list[str] = []
            buttons = menu_message.locator("button")
            for index in range(buttons.count()):
                label = (buttons.nth(index).inner_text() or "").strip()
                if label:
                    labels.append(label)

            username_labels = [label for label in labels if "username" in label.casefold()]
            return {
                "ok": True,
                "bot_username": bot_username,
                "endpoint": endpoint,
                "verified_botfather": True,
                "edit_menu_buttons": labels,
                "username_edit_available": bool(username_labels),
                "username_edit_labels": username_labels,
                "owned_tab_closed": True,
            }
        finally:
            if not page.is_closed():
                page.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit BotFather edit-menu capabilities on guarded Whale CDP.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--bot-username", required=True)
    parser.add_argument("--timeout-sec", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not BOT_USERNAME_PATTERN.fullmatch(args.bot_username):
        print(json.dumps({"ok": False, "error": "invalid_bot_username"}, ensure_ascii=False))
        return 2
    try:
        result = inspect_menu(args.endpoint, args.bot_username, max(10, args.timeout_sec) * 1_000)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
