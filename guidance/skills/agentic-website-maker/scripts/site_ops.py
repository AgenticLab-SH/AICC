#!/usr/bin/env python3
"""Website profile, registry, and production verification helper."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def find_config_root(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("AICC_GUIDANCE_CONFIG_ROOT"):
        candidates.append(Path(os.environ["AICC_GUIDANCE_CONFIG_ROOT"]).expanduser())
    candidates.append(Path.home() / ".ai-control-center" / "guidance")
    for candidate in candidates:
        marker = candidate / "website-maker.json"
        if marker.is_file():
            return candidate.resolve()
    raise SystemExit(
        "AICC website configuration not found; run aicc setup or pass --config-root"
    )


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read JSON {path}: {exc}") from exc


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def portable_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return "~/" + resolved.relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def normalize_hostname(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if "://" in candidate:
        candidate = urllib.parse.urlparse(candidate).hostname or ""
    labels = candidate.split(".")
    if (
        not candidate
        or len(candidate) > 253
        or len(labels) < 2
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (ch.isalnum() or ch == "-") for ch in label)
            for label in labels
        )
    ):
        raise SystemExit(f"Invalid hostname: {value}")
    try:
        candidate.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SystemExit("Hostname must be lowercase ASCII or punycode") from exc
    return candidate


def load_settings(config_root: Path) -> dict[str, Any]:
    path = config_root / "website-maker.json"
    settings = read_json(path)
    if not isinstance(settings, dict):
        raise SystemExit(f"Missing or invalid settings: {path}")
    return settings


def assert_allowed(hostname: str, settings: dict[str, Any]) -> None:
    roots = settings.get("allowed_root_domains", [])
    if not any(hostname == root or hostname.endswith("." + root) for root in roots):
        raise SystemExit(f"Hostname is outside allowed root domains: {hostname}")


def csv_values(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        for item in value.split(","):
            normalized = item.strip()
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def cmd_config(args: argparse.Namespace) -> int:
    config_root = find_config_root(args.config_root)
    settings = load_settings(config_root)
    print(json.dumps({"config_root": portable_path(config_root), "settings": settings}, ensure_ascii=False, indent=2))
    return 0


def build_profile(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    hostname = normalize_hostname(args.primary_domain)
    assert_allowed(hostname, settings)
    aliases = [normalize_hostname(item) for item in csv_values(args.alias)]
    for alias in aliases:
        assert_allowed(alias, settings)
    profile = {
        "schema_version": 1,
        "title": args.title.strip(),
        "primary_domain": hostname,
        "aliases": sorted(set(aliases) - {hostname}),
        "hosting_provider": args.provider or settings.get(
            "default_hosting_provider", "cloudflare-pages"
        ),
        "provider_project": args.provider_project,
        "deployment_mode": args.deployment_mode,
        "source_repository": args.source_repository,
        "source_visibility": args.source_visibility,
        "dns_provider": args.dns_provider,
        "data_mode": args.data_mode,
        "brand_sources": csv_values(args.brand_source),
        "data_sources": csv_values(args.data_source),
        "critical_paths": csv_values(args.critical_path) or ["/"],
        "last_verified_at": args.verified_at or None,
    }
    return {key: value for key, value in profile.items() if value is not None}


def cmd_init_profile(args: argparse.Namespace) -> int:
    config_root = find_config_root(args.config_root)
    settings = load_settings(config_root)
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"Project directory not found: {project}")
    profile = build_profile(args, settings)
    profile_path = project / settings["project_profile_path"]
    if profile_path.exists() and not args.force:
        raise SystemExit(f"Profile exists; pass --force to replace: {profile_path}")
    atomic_json(profile_path, profile)
    print(json.dumps({"status": "created", "profile": portable_path(profile_path)}, ensure_ascii=False))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    config_root = find_config_root(args.config_root)
    settings = load_settings(config_root)
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"Project directory not found: {project}")
    profile = build_profile(args, settings)
    verified_at = args.verified_at or now_iso()
    profile["last_verified_at"] = verified_at
    profile["last_verification"] = {
        "status": args.status,
        "checks": csv_values(args.check),
        "production_url": f"https://{profile['primary_domain']}/",
    }

    hosting = read_json(project / ".openai" / "hosting.json", {})
    if (
        profile["hosting_provider"] == "openai-sites"
        and isinstance(hosting, dict)
        and hosting.get("project_id")
    ):
        profile["sites_project_id"] = hosting["project_id"]

    registry_path = config_root / settings["registry_path"]
    registry = read_json(
        registry_path,
        {"schema_version": 1, "updated_at": None, "projects": []},
    )
    projects = registry.setdefault("projects", [])
    if not isinstance(projects, list):
        raise SystemExit(f"Invalid projects array: {registry_path}")

    primary = profile["primary_domain"]
    occupied: dict[str, str] = {}
    for item in projects:
        if not isinstance(item, dict):
            continue
        key = item.get("project_key", "")
        for host in [item.get("primary_domain"), *(item.get("aliases") or [])]:
            if host:
                occupied[str(host)] = str(key)
    project_key = args.project_key or project.name
    for host in [primary, *profile["aliases"]]:
        owner = occupied.get(host)
        if owner and owner != project_key:
            raise SystemExit(f"Domain already belongs to {owner}: {host}")

    entry = {
        "project_key": project_key,
        "title": profile["title"],
        "project_root": portable_path(project),
        "primary_domain": primary,
        "aliases": profile["aliases"],
        "hosting_provider": profile["hosting_provider"],
        "provider_project": profile.get("provider_project"),
        "deployment_mode": profile.get("deployment_mode"),
        "source_repository": profile.get("source_repository"),
        "source_visibility": profile.get("source_visibility"),
        "dns_provider": profile.get("dns_provider"),
        "data_mode": profile["data_mode"],
        "brand_sources": profile["brand_sources"],
        "data_sources": profile["data_sources"],
        "critical_paths": profile["critical_paths"],
        "status": args.status,
        "last_verified_at": verified_at,
        "checks": csv_values(args.check),
    }
    if profile.get("sites_project_id"):
        entry["sites_project_id"] = profile["sites_project_id"]
    entry = {key: value for key, value in entry.items() if value is not None}
    projects[:] = [
        item
        for item in projects
        if not isinstance(item, dict) or item.get("project_key") != project_key
    ]
    projects.append(entry)
    projects.sort(key=lambda item: str(item.get("project_key", "")))
    registry["updated_at"] = now_iso()

    atomic_json(project / settings["project_profile_path"], profile)
    atomic_json(registry_path, registry)
    print(
        json.dumps(
            {
                "status": "recorded",
                "project_key": project_key,
                "primary_url": f"https://{primary}/",
                "profile": portable_path(project / settings["project_profile_path"]),
                "registry": portable_path(registry_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AgenticWebsiteMakerVerifier/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_000).decode("utf-8", errors="replace")
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        return int(exc.code), body


def cmd_verify(args: argparse.Namespace) -> int:
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SystemExit("--url must be an https URL")
    hostname = normalize_hostname(parsed.hostname)
    timeout = float(args.timeout)
    checks: list[dict[str, Any]] = []
    ok = True

    try:
        addresses = sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(
                    hostname, 443, type=socket.SOCK_STREAM
                )
            }
        )
        checks.append({"name": "dns", "ok": bool(addresses), "addresses": addresses})
    except socket.gaierror as exc:
        checks.append({"name": "dns", "ok": False, "error": str(exc)})
        addresses = []
        ok = False

    if addresses:
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=timeout) as raw:
                with context.wrap_socket(raw, server_hostname=hostname) as secure:
                    certificate = secure.getpeercert()
            checks.append(
                {
                    "name": "tls",
                    "ok": True,
                    "subject_alt_names": [
                        value
                        for kind, value in certificate.get("subjectAltName", [])
                        if kind == "DNS"
                    ],
                }
            )
        except (OSError, ssl.SSLError) as exc:
            checks.append({"name": "tls", "ok": False, "error": str(exc)})
            ok = False

    paths = csv_values(args.endpoint) or [parsed.path or "/"]
    expected = csv_values(args.expect)
    rejected = csv_values(args.reject)
    origin = f"https://{hostname}"
    for path in paths:
        target = urllib.parse.urljoin(origin + "/", path.lstrip("/"))
        try:
            status, body = fetch(target, timeout)
            path_ok = 200 <= status < 300
            missing = [text for text in expected if text not in body] if path == paths[0] else []
            present_rejected = [text for text in rejected if text in body]
            path_ok = path_ok and not missing and not present_rejected
            checks.append(
                {
                    "name": "http",
                    "url": target,
                    "ok": path_ok,
                    "status": status,
                    "missing_expected": missing,
                    "present_rejected": present_rejected,
                }
            )
            ok = ok and path_ok
        except (OSError, urllib.error.URLError) as exc:
            checks.append({"name": "http", "url": target, "ok": False, "error": str(exc)})
            ok = False

    report = {
        "status": "passed" if ok else "failed",
        "url": f"https://{hostname}/",
        "verified_at": now_iso(),
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_list(args: argparse.Namespace) -> int:
    config_root = find_config_root(args.config_root)
    settings = load_settings(config_root)
    registry = read_json(config_root / settings["registry_path"], {"projects": []})
    print(json.dumps(registry, ensure_ascii=False, indent=2))
    return 0


def add_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-key")
    parser.add_argument("--title", required=True)
    parser.add_argument("--primary-domain", required=True)
    parser.add_argument("--alias", action="append")
    parser.add_argument("--provider")
    parser.add_argument("--provider-project")
    parser.add_argument(
        "--deployment-mode",
        choices=("direct-upload", "git-integration", "worker-deploy", "firebase-cli", "saved-version"),
    )
    parser.add_argument("--source-repository")
    parser.add_argument(
        "--source-visibility",
        choices=("private", "public"),
        default="private",
    )
    parser.add_argument("--dns-provider", default="cloudflare")
    parser.add_argument(
        "--data-mode",
        choices=("live", "user-owned", "static", "fixture-only"),
        default="static",
    )
    parser.add_argument("--brand-source", action="append")
    parser.add_argument("--data-source", action="append")
    parser.add_argument("--critical-path", action="append")
    parser.add_argument("--verified-at")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-root", "--hub", dest="config_root",
        help="AICC personal guidance configuration root",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="show resolved maker configuration")
    config.set_defaults(func=cmd_config)

    init_profile = sub.add_parser("init-profile", help="create a project profile")
    add_profile_args(init_profile)
    init_profile.add_argument("--force", action="store_true")
    init_profile.set_defaults(func=cmd_init_profile)

    record = sub.add_parser("record", help="record a verified production release")
    add_profile_args(record)
    record.add_argument("--status", choices=("active", "pending", "retired"), default="active")
    record.add_argument("--check", action="append")
    record.set_defaults(func=cmd_record)

    verify = sub.add_parser("verify", help="verify DNS, TLS, and HTTPS paths")
    verify.add_argument("--url", required=True)
    verify.add_argument("--endpoint", action="append")
    verify.add_argument("--expect", action="append")
    verify.add_argument("--reject", action="append")
    verify.add_argument("--timeout", type=float, default=15.0)
    verify.set_defaults(func=cmd_verify)

    listing = sub.add_parser("list", help="print the central website registry")
    listing.set_defaults(func=cmd_list)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
