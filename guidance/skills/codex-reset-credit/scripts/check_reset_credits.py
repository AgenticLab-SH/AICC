#!/usr/bin/env python3
"""Read Codex rate limits, reset credits, and token usage through app-server."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

READ_METHODS = {
    2: "account/rateLimits/read",
    3: "account/usage/read",
}
BLOCKED_METHODS = frozenset({"account/rateLimitResetCredit/consume"})
DEFAULT_TIMEZONE = "Asia/Seoul"


class AppServerError(RuntimeError):
    """A safe-to-display app-server query error."""


def validate_read_method(method: str) -> None:
    """Reject every method except the two reviewed read-only methods."""
    if method in BLOCKED_METHODS:
        raise AppServerError("Reset-credit consumption is blocked by this read-only tool.")
    if method not in READ_METHODS.values():
        raise AppServerError(f"Unsupported app-server method: {method}")


def _find_npm_native_codex(wrapper: Path) -> Path | None:
    package_root = wrapper.parent / "node_modules" / "@openai" / "codex" / "node_modules"
    if not package_root.is_dir():
        return None
    matches = sorted(package_root.glob("@openai/codex-*/vendor/*/bin/codex.exe"))
    return matches[-1] if matches else None


def resolve_codex_command(explicit: str | None = None) -> list[str]:
    """Resolve an executable app-server command without PowerShell functions."""
    candidate = explicit or os.environ.get("CODEX_BIN")
    if candidate:
        path = Path(candidate).expanduser()
        if not path.exists():
            located = shutil.which(candidate)
            if not located:
                raise AppServerError(f"Codex executable was not found: {candidate}")
            path = Path(located)
        return _command_for_path(path.resolve())

    if os.name == "nt":
        wrapper = shutil.which("codex.cmd")
        if wrapper:
            native = _find_npm_native_codex(Path(wrapper))
            if native:
                return [str(native), "app-server", "--stdio"]
            return _command_for_path(Path(wrapper))

    located = shutil.which("codex") or shutil.which("codex.exe")
    if not located:
        raise AppServerError("Codex CLI with app-server support was not found on PATH.")
    return _command_for_path(Path(located))


def _command_for_path(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        command_line = subprocess.list2cmdline([str(path), "app-server", "--stdio"])
        return [comspec, "/d", "/s", "/c", command_line]
    if os.name == "nt" and suffix == ".ps1":
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            raise AppServerError("PowerShell is required to launch the Codex wrapper.")
        return [pwsh, "-NoProfile", "-File", str(path), "app-server", "--stdio"]
    return [str(path), "app-server", "--stdio"]


class AppServerClient:
    def __init__(self, command: list[str], timeout: float = 15.0):
        self.command = command
        self.timeout = timeout

    def read(self) -> dict[str, dict[str, Any]]:
        for method in READ_METHODS.values():
            validate_read_method(method)

        process = self._start_process()
        stdout_lines: queue.Queue[str] = queue.Queue()
        threading.Thread(
            target=_read_stdout,
            args=(process, stdout_lines),
            daemon=True,
        ).start()
        threading.Thread(
            target=_drain_stderr,
            args=(process,),
            daemon=True,
        ).start()
        try:
            self._send(
                process,
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "codex-reset-credit",
                            "version": "1.0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                },
            )
            initialized = self._wait_for_ids(process, stdout_lines, {1})
            _raise_rpc_error(initialized[1], "initialize")

            self._send(process, {"method": "initialized"})
            for request_id, method in READ_METHODS.items():
                self._send(
                    process,
                    {"id": request_id, "method": method, "params": None},
                )
            responses = self._wait_for_ids(
                process,
                stdout_lines,
                set(READ_METHODS),
            )
            results: dict[str, dict[str, Any]] = {}
            for request_id, method in READ_METHODS.items():
                response = responses[request_id]
                _raise_rpc_error(response, method)
                result = response.get("result")
                if not isinstance(result, dict):
                    raise AppServerError(f"Invalid result shape for {method}.")
                results[method] = result
            return results
        finally:
            _stop_process(process)

    def _start_process(self) -> subprocess.Popen[str]:
        try:
            return subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise AppServerError("Codex app-server could not be started.") from exc

    @staticmethod
    def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise AppServerError("Codex app-server stdin is unavailable.")
        try:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AppServerError("Codex app-server closed its input unexpectedly.") from exc

    def _wait_for_ids(
        self,
        process: subprocess.Popen[str],
        stdout_lines: queue.Queue[str],
        expected_ids: set[int],
    ) -> dict[int, dict[str, Any]]:
        deadline = time.monotonic() + self.timeout
        responses: dict[int, dict[str, Any]] = {}
        while expected_ids - responses.keys():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                missing = sorted(expected_ids - responses.keys())
                raise AppServerError(f"Timed out waiting for app-server response IDs: {missing}")
            try:
                line = stdout_lines.get(timeout=min(0.2, remaining))
            except queue.Empty:
                if process.poll() is not None:
                    raise AppServerError(
                        f"Codex app-server exited before replying (code {process.returncode})."
                    ) from None
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if isinstance(request_id, int) and request_id in expected_ids:
                responses[request_id] = message
        return responses


def _read_stdout(process: subprocess.Popen[str], target: queue.Queue[str]) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        if line.strip():
            target.put(line)


def _drain_stderr(process: subprocess.Popen[str]) -> None:
    if process.stderr is None:
        return
    for _line in process.stderr:
        pass


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _raise_rpc_error(response: Mapping[str, Any], method: str) -> None:
    error = response.get("error")
    if error is None:
        return
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, int | str):
            raise AppServerError(f"{method} failed (code {code}).")
    raise AppServerError(f"{method} failed.")


def _timezone(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == DEFAULT_TIMEZONE:
            return dt.timezone(dt.timedelta(hours=9), name="KST")
        raise AppServerError(f"Unknown timezone: {name}") from None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value / 1000 if value > 10_000_000_000 else value)


def _time_fields(value: Any, timezone: dt.tzinfo, now: float) -> dict[str, Any]:
    timestamp = _timestamp(value)
    if timestamp is None:
        return {"unix": None, "local": None, "remaining": None}
    local = dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).astimezone(timezone)
    return {
        "unix": int(timestamp),
        "local": local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "remaining": _format_duration(timestamp - now),
    }


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "expired"
    total_minutes = int(seconds // 60)
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _window(
    name: str,
    value: Any,
    timezone: dt.tzinfo,
    now: float,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    used = value.get("usedPercent")
    used_percent = used if isinstance(used, int | float) and not isinstance(used, bool) else None
    return {
        "name": name,
        "used_percent": used_percent,
        "remaining_percent": max(0, 100 - used_percent) if used_percent is not None else None,
        "window_duration_mins": value.get("windowDurationMins"),
        "resets": _time_fields(value.get("resetsAt"), timezone, now),
    }


def build_report(
    results: Mapping[str, dict[str, Any]],
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    now: float | None = None,
) -> dict[str, Any]:
    timezone = _timezone(timezone_name)
    now_value = time.time() if now is None else now
    rate_result = results.get("account/rateLimits/read")
    usage_result = results.get("account/usage/read")
    if not isinstance(rate_result, dict) or not isinstance(usage_result, dict):
        raise AppServerError("Both read-only app-server results are required.")

    rate_limits = rate_result.get("rateLimits")
    if not isinstance(rate_limits, dict):
        rate_limits = {}
    windows = [
        window
        for name in ("primary", "secondary")
        if (window := _window(name, rate_limits.get(name), timezone, now_value)) is not None
    ]

    reset_data = rate_result.get("rateLimitResetCredits")
    if not isinstance(reset_data, dict):
        reset_data = {}
    credits: list[dict[str, Any]] = []
    raw_credits = reset_data.get("credits")
    if isinstance(raw_credits, list):
        for item in raw_credits:
            if not isinstance(item, dict):
                continue
            credits.append(
                {
                    "title": item.get("title") if isinstance(item.get("title"), str) else None,
                    "status": item.get("status") if isinstance(item.get("status"), str) else None,
                    "expires": _time_fields(item.get("expiresAt"), timezone, now_value),
                }
            )

    raw_summary = usage_result.get("summary")
    summary: dict[str, int | float] = {}
    if isinstance(raw_summary, dict):
        for key in (
            "lifetimeTokens",
            "peakDailyTokens",
            "longestRunningTurnSec",
            "currentStreakDays",
            "longestStreakDays",
        ):
            value = raw_summary.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                summary[key] = value

    daily: list[dict[str, Any]] = []
    raw_daily = usage_result.get("dailyUsageBuckets")
    if isinstance(raw_daily, list):
        for item in raw_daily:
            if not isinstance(item, dict):
                continue
            start_date = item.get("startDate")
            tokens = item.get("tokens")
            if isinstance(start_date, str) and isinstance(tokens, int | float):
                daily.append({"start_date": start_date, "tokens": tokens})

    queried = dt.datetime.fromtimestamp(now_value, tz=dt.UTC).astimezone(timezone)
    available_count = reset_data.get("availableCount")
    if isinstance(available_count, bool) or not isinstance(available_count, int | float):
        available_count = None
    return {
        "queried_at": queried.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "timezone": timezone_name,
        "plan_type": rate_limits.get("planType"),
        "rate_limits": windows,
        "reset_credits": {
            "available_count": available_count,
            "credits": credits,
        },
        "usage": {
            "summary": summary,
            "daily": daily,
        },
    }


def format_report(report: Mapping[str, Any], daily_limit: int = 14) -> str:
    lines = [
        "Codex usage and Full reset credits (read-only)",
        f"Queried: {report.get('queried_at')}",
        f"Plan: {report.get('plan_type') or 'unknown'}",
    ]
    windows = report.get("rate_limits")
    if isinstance(windows, list):
        for window in windows:
            if not isinstance(window, dict):
                continue
            raw_resets = window.get("resets")
            resets: dict[str, Any] = raw_resets if isinstance(raw_resets, dict) else {}
            lines.append(
                f"{str(window.get('name', 'rate')).title()} rate limit: "
                f"{_number(window.get('used_percent'))}% used, "
                f"{_number(window.get('remaining_percent'))}% remaining"
            )
            lines.append(
                f"  Auto reset: {resets.get('local') or 'unknown'} "
                f"({resets.get('remaining') or 'unknown'})"
            )

    reset_credits = report.get("reset_credits")
    if isinstance(reset_credits, dict):
        available = _number(reset_credits.get("available_count"))
        lines.append(f"Available Full reset credits: {available}")
        credits = reset_credits.get("credits")
        if isinstance(credits, list):
            for index, credit in enumerate(credits, start=1):
                if not isinstance(credit, dict):
                    continue
                raw_expires = credit.get("expires")
                expires: dict[str, Any] = (
                    raw_expires if isinstance(raw_expires, dict) else {}
                )
                lines.append(
                    f"  {index}. {credit.get('title') or 'Full reset'} "
                    f"[{credit.get('status') or 'unknown'}] - "
                    f"{expires.get('local') or 'unknown'} "
                    f"({expires.get('remaining') or 'unknown'})"
                )

    usage = report.get("usage")
    if isinstance(usage, dict):
        summary = usage.get("summary")
        if isinstance(summary, dict):
            lines.extend(
                [
                    "Usage summary:",
                    f"  Lifetime tokens: {_number(summary.get('lifetimeTokens'), commas=True)}",
                    f"  Peak daily tokens: {_number(summary.get('peakDailyTokens'), commas=True)}",
                    "  Longest turn: "
                    f"{_number(summary.get('longestRunningTurnSec'), commas=True)} sec",
                    "  Current / longest streak: "
                    f"{_number(summary.get('currentStreakDays'))} / "
                    f"{_number(summary.get('longestStreakDays'))} days",
                ]
            )
        daily = usage.get("daily")
        if isinstance(daily, list) and daily:
            selected = daily[-daily_limit:] if daily_limit > 0 else daily
            lines.append(f"Daily token usage (latest {len(selected)} buckets):")
            for item in selected:
                if isinstance(item, dict):
                    lines.append(
                        f"  {item.get('start_date')}: "
                        f"{_number(item.get('tokens'), commas=True)}"
                    )
    return "\n".join(lines)


def _number(value: Any, *, commas: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "unknown"
    return f"{value:,.0f}" if commas else f"{value:g}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read Codex usage, rate limits, and Full reset credits through app-server."
    )
    parser.add_argument("--codex", help="Explicit Codex executable or wrapper path.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--daily-limit", type=int, default=14)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.daily_limit < 0:
        parser.error("--daily-limit must be zero or positive")
    try:
        command = resolve_codex_command(args.codex)
        results = AppServerClient(command, timeout=args.timeout).read()
        report = build_report(results, timezone_name=args.timezone)
    except AppServerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report, daily_limit=args.daily_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
