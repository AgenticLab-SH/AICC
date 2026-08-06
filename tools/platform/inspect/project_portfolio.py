#!/usr/bin/env python3
"""Read-only audit of registered local projects and canonical GitHub remotes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


def run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return result.returncode, result.stdout.strip()


def git(path: Path, *args: str) -> tuple[int, str]:
    return run(["git", "-C", str(path), *args])


def github_slug(url: str) -> str | None:
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def sanitize_remote(url: str) -> str:
    return re.sub(r"^(https?://)[^/@]+@", r"\1<credentials>@", url)


def read_remotes(path: Path) -> dict[str, str]:
    code, output = git(path, "remote", "-v")
    if code:
        return {}
    remotes: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] not in remotes:
            remotes[fields[0]] = sanitize_remote(fields[1])
    return remotes


def github_visibility(repo: str) -> dict[str, Any]:
    code, output = run(
        ["gh", "api", f"repos/{repo}", "--jq", "{private:.private,archived:.archived,visibility:.visibility}"]
    )
    if code:
        return {"available": False}
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return {"available": False}
    return {"available": True, **data}


def inspect_project(
    project: dict[str, Any], *, check_github: bool = False, enforce_local_name: bool = False
) -> dict[str, Any]:
    path = Path(str(project["path"])).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    result: dict[str, Any] = {
        "id": project["id"],
        "path": str(path),
        "role": project.get("role", "source"),
        "lifecycle": project.get("lifecycle", "active"),
        "canonical_repo": project.get("canonical_repo"),
        "canonical_state": project.get("canonical_state", "ready"),
        "canonical_blocker": project.get("canonical_blocker"),
    }
    if not path.is_dir():
        errors.append("path missing")
        result.update(errors=errors, warnings=warnings, ok=False)
        return result

    code, root = git(path, "rev-parse", "--show-toplevel")
    if code:
        errors.append("not a Git repository")
        result.update(errors=errors, warnings=warnings, ok=False)
        return result
    result["git_root"] = root

    local_name = Path(root).name
    expected_repo = str(project.get("canonical_repo", ""))
    canonical_name = expected_repo.split("/", 1)[1] if "/" in expected_repo else expected_repo
    expected_name = str(project.get("github_name_override") or local_name)
    result["local_git_root_name"] = local_name
    result["expected_github_name"] = expected_name
    if enforce_local_name and canonical_name != expected_name:
        errors.append(
            f"GitHub name mismatch: local policy expects {expected_name}, found {canonical_name or '(missing)'}"
        )

    _, branch = git(path, "branch", "--show-current")
    _, status = git(path, "status", "--porcelain=v1")
    result["branch"] = branch or "(detached)"
    result["dirty_files"] = len(status.splitlines()) if status else 0
    result["has_readme"] = any((path / name).is_file() for name in ("README.md", "README", "README.rst"))
    result["has_agents"] = (path / "AGENTS.md").is_file()
    result["has_gitignore"] = (path / ".gitignore").is_file()
    if result["dirty_files"]:
        warnings.append(f"{result['dirty_files']} dirty files require scoped review")
    if not result["has_gitignore"]:
        warnings.append(".gitignore missing; verify runtime and secret exclusions")

    remotes = read_remotes(path)
    result["remotes"] = remotes
    canonical_remote = str(project.get("canonical_remote", ""))
    actual_url = remotes.get(canonical_remote)
    actual_repo = github_slug(actual_url) if actual_url else None
    result["canonical_remote"] = canonical_remote
    result["canonical_remote_repo"] = actual_repo
    if project.get("canonical_state") == "pending":
        blocker = str(project.get("canonical_blocker", "")).strip()
        warnings.append(f"canonical remote pending: {blocker}" if blocker else "canonical remote pending")
    elif not actual_url:
        errors.append(f"canonical remote missing: {canonical_remote}")
    elif expected_repo and actual_repo != expected_repo:
        errors.append(f"canonical remote mismatch: expected {expected_repo}, found {actual_repo or 'non-GitHub'}")

    if check_github and expected_repo:
        visibility = github_visibility(expected_repo)
        result["github"] = visibility
        expected_visibility = str(project.get("canonical_visibility", "private")).lower()
        result["canonical_visibility"] = expected_visibility
        if project.get("canonical_state") == "ready":
            if not visibility.get("available"):
                errors.append("canonical GitHub repository unavailable")
            elif str(visibility.get("visibility", "")).lower() != expected_visibility:
                errors.append(
                    f"canonical GitHub repository visibility mismatch: expected {expected_visibility}, "
                    f"found {visibility.get('visibility', 'unknown')}"
                )
            elif visibility.get("archived"):
                warnings.append("canonical GitHub repository is archived")

    result["errors"] = errors
    result["warnings"] = warnings
    result["ok"] = not errors
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data.get("projects"), list):
        raise ValueError("manifest must contain [[projects]] entries")
    return data


def default_manifest_path(
    *, env: dict[str, str] | None = None, home: Path | None = None
) -> Path:
    supplied_env = os.environ if env is None else env
    state_root = Path(
        supplied_env.get("AICC_STATE_ROOT", (home or Path.home()) / ".ai-control-center")
    ).expanduser()
    return state_root / "cross-device" / "project-portfolio.toml"


def audit(manifest: Path, *, check_github: bool = False) -> dict[str, Any]:
    data = load_manifest(manifest)
    enforce_local_name = data.get("policy", {}).get("github_name_source") == "local-git-root-basename"
    projects = [
        inspect_project(item, check_github=check_github, enforce_local_name=enforce_local_name)
        for item in data["projects"]
    ]
    return {
        "ok": all(item["ok"] for item in projects),
        "manifest": str(manifest),
        "project_count": len(projects),
        "error_count": sum(len(item["errors"]) for item in projects),
        "warning_count": sum(len(item["warnings"]) for item in projects),
        "pending_count": sum(item["canonical_state"] == "pending" for item in projects),
        "dirty_count": sum(bool(item.get("dirty_files")) for item in projects),
        "projects": projects,
    }


def print_table(report: dict[str, Any]) -> None:
    print(f"projects={report['project_count']} errors={report['error_count']} warnings={report['warning_count']} pending={report['pending_count']} dirty={report['dirty_count']}")
    print(f"{'PROJECT':28} {'STATE':8} {'DIRTY':>5} {'BRANCH':30} NOTES")
    for item in report["projects"]:
        state = "ok" if item["ok"] else "error"
        notes = item["errors"] + item["warnings"]
        print(f"{item['id'][:28]:28} {state:8} {item.get('dirty_files', 0):5} {item.get('branch', '-')[:30]:30} {'; '.join(notes)}")


def main(argv: list[str] | None = None) -> int:
    default_manifest = default_manifest_path()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--github", action="store_true", help="verify canonical repository state through gh")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true", help="exit nonzero when a registered project has an error")
    args = parser.parse_args(argv)
    try:
        report = audit(args.manifest.resolve(), check_github=args.github)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_table(report)
    return 1 if args.strict and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
