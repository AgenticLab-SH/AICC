"""Send a bounded command smoke test to one Telegram bot through Whale Web."""

from __future__ import annotations

import argparse
import json
import sys
import time

from playwright.sync_api import Locator, Page, sync_playwright


OWNED_PAGE_MARKER = "aicc-telegram-bot-smoke"


def send(page: Page, text: str) -> None:
    composer = page.locator(".Composer [contenteditable=true]:visible").last
    composer.fill(text)
    composer.press("Enter")


def is_own(message: Locator) -> bool:
    classes = message.get_attribute("class") or ""
    return "own" in classes.split()


def wait_for_reply(page: Page, baseline: int, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    messages = page.locator(".Message")
    while time.monotonic() < deadline:
        count = messages.count()
        for index in range(count - 1, baseline - 1, -1):
            message = messages.nth(index)
            try:
                if message.is_visible() and not is_own(message) and (message.inner_text() or "").strip():
                    return True
            except Exception:
                continue
        page.wait_for_timeout(250)
    return False


def smoke(endpoint: str, bot_id: int, commands: list[str], timeout_ms: int) -> dict[str, object]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
        if not browser.contexts:
            raise RuntimeError("cdp_context_missing")
        context = browser.contexts[0]
        for existing in list(context.pages):
            try:
                if existing.evaluate("window.name") == OWNED_PAGE_MARKER:
                    existing.close()
            except Exception:
                continue
        page = context.new_page()
        try:
            page.evaluate(f"window.name={json.dumps(OWNED_PAGE_MARKER)}")
            page.goto(f"https://web.telegram.org/a/#{bot_id}", wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_function(
                "expected => window.location.hash === '#' + expected",
                arg=str(bot_id),
                timeout=timeout_ms,
            )
            page.wait_for_timeout(1_000)

            start = page.get_by_role("button", name="START", exact=True)
            started = False
            if start.count() and start.last.is_visible():
                start.last.click()
                started = True
                page.wait_for_timeout(1_000)
            page.locator(".Composer [contenteditable=true]:visible").last.wait_for(
                state="visible", timeout=timeout_ms
            )

            results: list[dict[str, object]] = []
            messages = page.locator(".Message")
            for command in commands:
                baseline = messages.count()
                send(page, command)
                received = wait_for_reply(page, baseline, timeout_ms)
                results.append({"command": command, "reply_received": received})
                if not received:
                    break
            return {
                "ok": all(item["reply_received"] for item in results) and len(results) == len(commands),
                "bot_id": bot_id,
                "started": started,
                "commands": results,
                "owned_tab_closed": True,
            }
        finally:
            page.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test one Telegram bot through Whale Web.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--bot-id", type=int, required=True)
    parser.add_argument("--command", action="append", required=True)
    parser.add_argument("--timeout-sec", type=int, default=30)
    args = parser.parse_args()
    try:
        result = smoke(args.endpoint, args.bot_id, args.command, max(10, args.timeout_sec) * 1_000)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
