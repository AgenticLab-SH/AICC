#!/usr/bin/env python3
"""Plan direct Web GPT attachments or build a deterministic context ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile


DIRECT_LIMIT = 10
DEFAULT_MAX_TOTAL_MIB = 50
SENSITIVE_NAME = re.compile(
    r"(?i)(^|[._-])(auth|cookie|credential|secret|session|token|wallet|history)([._-]|$)"
)
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".sqlite", ".sqlite3"}
EXACT_SENSITIVE_NAMES = {".env", "auth.json", "cookies.json", "local state", "login data"}
HIGH_CONFIDENCE_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(rb"(?i)\b(?:mcp|connector|runtime)[-_]?token=[^\s&]{8,}"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contains_high_confidence_secret(path: Path) -> bool:
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if any(pattern.search(chunk) for pattern in HIGH_CONFIDENCE_SECRET_PATTERNS):
                return True
    return False


def validate_file(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"file path must be absolute: {raw}")
    if path.is_symlink():
        raise ValueError(f"symbolic links are not allowed: {path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"regular file not found: {path}")
    lowered = path.name.lower()
    if (
        lowered in EXACT_SENSITIVE_NAMES
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or SENSITIVE_NAME.search(lowered)
    ):
        raise ValueError(f"sensitive-looking file is not allowed: {path}")
    if contains_high_confidence_secret(path):
        raise ValueError(f"high-confidence secret pattern found: {path}")
    return path.resolve(strict=True)


def parse_purposes(items: list[str]) -> dict[str, str]:
    purposes: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"purpose must be ABSOLUTE_PATH=TEXT: {item}")
        raw_path, text = item.split("=", 1)
        path = str(Path(raw_path).expanduser().resolve(strict=False))
        if not text.strip():
            raise ValueError(f"purpose text is empty: {item}")
        purposes[path] = text.strip()
    return purposes


def build_plan(files: list[str], output_dir: str | None, max_total_mib: int,
               purposes_raw: list[str]) -> dict[str, object]:
    if not files:
        raise ValueError("at least one explicit file path is required")
    paths = [validate_file(raw) for raw in files]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate files are not allowed")

    purposes = parse_purposes(purposes_raw)
    records: list[dict[str, object]] = []
    total = 0
    for index, path in enumerate(paths, start=1):
        size = path.stat().st_size
        total += size
        records.append(
            {
                "display_name": path.name,
                "size_bytes": size,
                "sha256": sha256_file(path),
                "purpose": purposes.get(str(path)),
                "archive_name": f"files/{index:03d}_{path.name}",
            }
        )

    maximum = max_total_mib * 1024 * 1024
    if total > maximum:
        raise ValueError(f"total size {total} exceeds limit {maximum} bytes")

    if len(paths) <= DIRECT_LIMIT:
        return {
            "mode": "direct",
            "file_count": len(paths),
            "total_bytes": total,
            "attachments": [str(path) for path in paths],
            "files": records,
        }

    destination = (
        Path(output_dir).expanduser().resolve(strict=False)
        if output_dir
        else Path(tempfile.mkdtemp(prefix="web-gpt-context-"))
    )
    destination.mkdir(parents=True, exist_ok=True)
    zip_path = destination / "web-gpt-context.zip"
    if zip_path.exists():
        raise ValueError(f"refusing to overwrite existing bundle: {zip_path}")

    manifest = {
        "schema_version": 1,
        "file_count": len(paths),
        "total_bytes": total,
        "files": records,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        for path, record in zip(paths, records, strict=True):
            archive.write(path, str(record["archive_name"]))

    with zipfile.ZipFile(zip_path, "r") as archive:
        expected = {"manifest.json", *(str(record["archive_name"]) for record in records)}
        if set(archive.namelist()) != expected or archive.testzip() is not None:
            raise RuntimeError("created ZIP failed content verification")
        archived_manifest = json.loads(archive.read("manifest.json"))
        if archived_manifest != manifest:
            raise RuntimeError("created ZIP manifest does not match the planned manifest")
        for record in records:
            archived_bytes = archive.read(str(record["archive_name"]))
            archived_hash = hashlib.sha256(archived_bytes).hexdigest()
            if archived_hash != record["sha256"]:
                raise RuntimeError(
                    f"created ZIP content hash mismatch: {record['archive_name']}"
                )

    return {
        "mode": "zip",
        "file_count": len(paths),
        "total_bytes": total,
        "attachments": [str(zip_path)],
        "zip_path": str(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "manifest": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="task-owned directory for a ZIP bundle")
    parser.add_argument("--max-total-mib", type=int, default=DEFAULT_MAX_TOTAL_MIB)
    parser.add_argument("--purpose", action="append", default=[], metavar="PATH=TEXT")
    parser.add_argument("files", nargs="*", help="explicit absolute regular-file paths")
    args = parser.parse_args()
    if args.max_total_mib <= 0:
        parser.error("--max-total-mib must be positive")
    try:
        plan = build_plan(args.files, args.output_dir, args.max_total_mib, args.purpose)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
