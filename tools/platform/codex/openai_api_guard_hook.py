#!/usr/bin/env python3
"""Block Codex shell calls that bypass the AICC OpenAI API guard."""

from __future__ import annotations

import json
import re
import sys


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=True,
        )
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    normalized = re.sub(r"\s+", " ", command).strip()

    if re.search(r"https?://api\.openai\.com(?:/|\b)", normalized, re.IGNORECASE):
        deny("OpenAI API 직접 호출은 차단됩니다. AICC의 `aicc openai estimate/ask` 경로를 사용하세요.")
        return 0
    if re.search(r"\bsecurity\b.*\bfind-generic-password\b", normalized, re.IGNORECASE) and re.search(
        r"OpenAI(?: Admin)? API", normalized, re.IGNORECASE
    ):
        deny("Codex가 OpenAI Keychain 항목을 직접 읽을 수 없습니다. 키는 AICC gateway만 사용합니다.")
        return 0
    if re.search(r"\$(?:\{)?OPENAI_(?:API|ADMIN)_KEY\b", normalized, re.IGNORECASE) or re.search(
        r"\b(?:printenv|env)\b[^\n]*(?:OPENAI_API_KEY|OPENAI_ADMIN_KEY)", normalized, re.IGNORECASE
    ):
        deny("Codex 하위 명령에서 OpenAI key 환경변수를 읽는 동작은 차단됩니다.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
