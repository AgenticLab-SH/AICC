"""Token-free, account-local Codex thread-index reconciliation.

Conversation rollouts may be shared across managed CODEX_HOME directories,
while each home keeps its own SQLite state.  This module updates one inactive
home by asking the installed Codex app-server to backfill a consistent copy of
that home's database.  It never calls a model and never shares a live SQLite
database between app-server processes.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path


STATE_FILE = "thread-index-sync.json"
BACKUP_DIR = "thread-index-backups"
BACKUPS_PER_ACCOUNT = 2
ROLLOUT_PATTERNS = ("rollout-*.jsonl", "rollout-*.jsonl.zst")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _state_path(manager_dir: Path) -> Path:
    return Path(manager_dir) / STATE_FILE


def _rollout_files(home: Path) -> list[Path]:
    files: dict[str, Path] = {}
    for root_name in ("sessions", "archived_sessions"):
        root = Path(home) / root_name
        if not root.exists():
            continue
        for pattern in ROLLOUT_PATTERNS:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                try:
                    if path.stat().st_size == 0:
                        continue
                except OSError:
                    continue
                try:
                    key = str(path.resolve())
                except OSError:
                    key = str(path.absolute())
                files[key] = path
    return [files[key] for key in sorted(files)]


def source_fingerprint(home: Path) -> dict:
    digest = hashlib.sha256()
    total_bytes = 0
    newest_ns = 0
    files = _rollout_files(home)
    for path in files:
        stat = path.stat()
        total_bytes += stat.st_size
        newest_ns = max(newest_ns, stat.st_mtime_ns)
        digest.update(str(path.resolve()).encode("utf-8", errors="surrogateescape"))
        digest.update(b"\n")
    return {
        "sha256": digest.hexdigest(),
        "files": len(files),
        "bytes": total_bytes,
        "newest_mtime_ns": newest_ns,
    }


def _configured_sqlite_home(home: Path) -> Path:
    config_path = Path(home) / "config.toml"
    try:
        with config_path.open("rb") as handle:
            configured = tomllib.load(handle).get("sqlite_home")
    except (OSError, tomllib.TOMLDecodeError):
        configured = None
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path(home).resolve()


def database_path(home: Path) -> Path:
    return _configured_sqlite_home(home) / "state_5.sqlite"


def _thread_count(path: Path) -> int:
    if not path.is_file():
        return 0
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        return int(connection.execute("select count(*) from threads").fetchone()[0])
    except sqlite3.DatabaseError:
        return -1
    finally:
        connection.close()


def _temporary_rollout_path_count(path: Path) -> int:
    """Count leaked cm scan-home paths without modifying the live database."""
    if not path.is_file():
        return 0
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(threads)")}
        if "rollout_path" not in columns:
            return 0
        return sum(
            _temporary_scan_rollout_suffix(row[0]) is not None
            for row in connection.execute("select rollout_path from threads")
        )
    except sqlite3.DatabaseError:
        return -1
    finally:
        connection.close()


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    destination_connection = sqlite3.connect(str(destination), timeout=30)
    try:
        source_connection.backup(destination_connection)
        destination_connection.execute("pragma wal_checkpoint(truncate)")
    finally:
        destination_connection.close()
        source_connection.close()


def _reset_backfill_state(path: Path) -> bool:
    """Make an inactive database copy rescan all rollout roots.

    Codex records a completed filesystem scan in ``backfill_state``. A home that
    previously exposed only ``sessions`` will otherwise ignore a newly shared
    ``archived_sessions`` root. This helper is called only for the temporary
    SQLite copy used during reconciliation; the live account database is never
    edited in place.
    """
    if not path.is_file():
        return False
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        exists = connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'backfill_state'"
        ).fetchone()
        if exists is None:
            return False
        changed = connection.execute("delete from backfill_state").rowcount > 0
        connection.commit()
        return changed
    finally:
        connection.close()


def _prepare_scan_home(source_home: Path, scan_home: Path) -> None:
    """Expose rollout roots to app-server without exposing account auth."""
    scan_home.mkdir(parents=True, exist_ok=True)
    for root_name in ("sessions", "archived_sessions"):
        source = Path(source_home) / root_name
        if source.exists():
            (scan_home / root_name).symlink_to(source, target_is_directory=True)


def _temporary_scan_rollout_suffix(rollout_path: str) -> tuple[str, tuple[str, ...]] | None:
    """Return the real rollout-root suffix stored below a cm scan home.

    A rebuilt database starts as a copy of the previous account database.  An
    interrupted or older rebuild can therefore contain paths from a *previous*
    ``cm-thread-index-*/scan-home`` directory, not only the current temporary
    directory.  Those directories are deleted at the end of synchronization,
    so retaining any such path makes the desktop hide an otherwise valid row.
    """
    if not isinstance(rollout_path, str):
        return None
    parts = tuple(part for part in rollout_path.replace("\\", "/").split("/") if part)
    for index, part in enumerate(parts[:-1]):
        if (
            part == "scan-home"
            and index > 0
            and parts[index - 1].startswith("cm-thread-index-")
            and parts[index + 1] in {"sessions", "archived_sessions"}
        ):
            return parts[index + 1], parts[index + 2:]
    return None


def _retarget_rollout_paths(database: Path, scan_home: Path, source_home: Path) -> int:
    """Replace current and historical scan-home paths with durable home paths."""
    connection = sqlite3.connect(str(database), timeout=30)
    updates: list[tuple[str, str]] = []
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(threads)")}
        if "rollout_path" not in columns:
            return 0
        for thread_id, rollout_path in connection.execute("select id, rollout_path from threads"):
            if not isinstance(rollout_path, str):
                continue
            replacement: str | None = None
            for root_name in ("sessions", "archived_sessions"):
                temporary_root = str(Path(scan_home) / root_name)
                source_root = str(Path(source_home) / root_name)
                if rollout_path == temporary_root or rollout_path.startswith(temporary_root + os.sep):
                    replacement = source_root + rollout_path[len(temporary_root):]
                    break
            if replacement is None:
                suffix = _temporary_scan_rollout_suffix(rollout_path)
                if suffix is not None:
                    root_name, relative_parts = suffix
                    replacement = str(Path(source_home) / root_name / Path(*relative_parts))
            if replacement is not None and replacement != rollout_path:
                updates.append((replacement, thread_id))
        if updates:
            connection.executemany("update threads set rollout_path = ? where id = ?", updates)
            connection.commit()
        return len(updates)
    finally:
        connection.close()


def _backfill_messages() -> tuple[dict, ...]:
    return (
        {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "cm_thread_index_sync",
                    "title": "cm thread index sync",
                    "version": "1",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"method": "thread/list", "id": 2, "params": {"limit": 1, "archived": False}},
        {"method": "thread/list", "id": 3, "params": {"limit": 1, "archived": True}},
    )


def _run_backfill(home: Path, sqlite_home: Path, codex_exe: Path) -> dict:
    payload = "\n".join(
        json.dumps(message, separators=(",", ":"))
        for message in _backfill_messages()
    ) + "\n"
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(Path(home).resolve())
    environment["CODEX_SQLITE_HOME"] = str(Path(sqlite_home).resolve())
    environment.pop("OPENAI_API_KEY", None)
    process = subprocess.Popen(
        [
            str(Path(codex_exe).resolve()),
            "app-server",
            "--stdio",
            "-c",
            "features.plugins=false",
            "-c",
            "features.remote_plugin=false",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    output_queue: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        try:
            for line in process.stdout:
                output_queue.put(line)
        finally:
            output_queue.put(None)

    def read_stderr() -> None:
        for line in process.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 40:
                del stderr_lines[:20]

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    process.stdin.write(payload)
    process.stdin.flush()

    responses: dict[int, dict] = {}
    pending_ids = {2, 3}
    deadline = time.monotonic() + 45
    while pending_ids and time.monotonic() < deadline:
        try:
            line = output_queue.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response_id = message.get("id")
        if response_id in pending_ids:
            responses[response_id] = message
            pending_ids.remove(response_id)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    process.stdin.close()
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    process.stdout.close()
    process.stderr.close()
    failed = next((response for response in responses.values() if response.get("error")), None)
    if pending_ids or failed is not None:
        detail = failed.get("error") if failed is not None else "".join(stderr_lines)[-500:]
        if pending_ids and not detail:
            detail = f"missing thread/list responses: {sorted(pending_ids)}"
        raise RuntimeError(f"Codex local thread backfill failed: {detail}")
    return {"returncode": process.returncode, "thread_list_ok": True, "thread_lists": 2}


def _verify_database(path: Path) -> int:
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        connection.execute("pragma wal_checkpoint(truncate)")
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"rebuilt thread index failed integrity_check: {integrity}")
        columns = {row[1] for row in connection.execute("pragma table_info(threads)")}
        if "rollout_path" in columns:
            leaked = sum(
                _temporary_scan_rollout_suffix(row[0]) is not None
                for row in connection.execute("select rollout_path from threads")
            )
            if leaked:
                raise RuntimeError(
                    f"rebuilt thread index retained {leaked} temporary rollout paths"
                )
        return int(connection.execute("select count(*) from threads").fetchone()[0])
    finally:
        connection.close()


def _prune_backups(account_root: Path, keep: int = BACKUPS_PER_ACCOUNT) -> int:
    directories = sorted(
        (path for path in account_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ) if account_root.is_dir() else []
    removed = 0
    for old in directories[max(1, keep):]:
        shutil.rmtree(old)
        removed += 1
    return removed


def status(manager_dir: Path, *, account_key: str, home: Path) -> dict:
    fingerprint = source_fingerprint(home)
    records = _read_json(_state_path(manager_dir)).get("accounts", {})
    record = records.get(account_key, {}) if isinstance(records, dict) else {}
    db = database_path(home)
    temporary_paths = _temporary_rollout_path_count(db)
    return {
        "account_key": account_key,
        "home": str(Path(home).resolve()),
        "database": str(db),
        "thread_count": _thread_count(db),
        "temporary_paths": temporary_paths,
        "source": fingerprint,
        "last_sync": record,
        "up_to_date": bool(
            record.get("source_sha256") == fingerprint["sha256"]
            and db.is_file()
            and temporary_paths == 0
        ),
    }


def synchronize(
    manager_dir: Path,
    *,
    account_key: str,
    account_name: str,
    home: Path,
    codex_exe: Path,
    active: bool = False,
    force: bool = False,
) -> dict:
    home = Path(home).resolve()
    sqlite_home = _configured_sqlite_home(home)
    if sqlite_home != home:
        raise RuntimeError(
            f"thread sync requires account-local SQLite; configured sqlite_home is {sqlite_home}"
        )
    if active:
        return {
            "ok": False,
            "skipped": True,
            "reason": "home_active",
            "account": account_name,
            "home": str(home),
        }

    current = status(manager_dir, account_key=account_key, home=home)
    if current["up_to_date"] and not force:
        return {"ok": True, "skipped": True, "reason": "up_to_date", **current}

    db = database_path(home)
    before = _thread_count(db)
    with tempfile.TemporaryDirectory(prefix="cm-thread-index-") as temporary_name:
        temporary = Path(temporary_name)
        temporary_db = temporary / "state_5.sqlite"
        if db.is_file():
            _sqlite_backup(db, temporary_db)
            _reset_backfill_state(temporary_db)
        scan_home = temporary / "scan-home"
        _prepare_scan_home(home, scan_home)
        _run_backfill(scan_home, temporary, codex_exe)
        _retarget_rollout_paths(temporary_db, scan_home, home)
        after = _verify_database(temporary_db)
        if before >= 0 and after < before:
            raise RuntimeError(f"thread sync refused a shrinking index: before={before}, after={after}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = Path(manager_dir) / BACKUP_DIR / account_key / stamp
        backup.mkdir(parents=True, exist_ok=False)
        if db.is_file():
            _sqlite_backup(db, backup / "state_5.sqlite")
        for suffix in ("-wal", "-shm"):
            companion = Path(str(db) + suffix)
            if companion.exists():
                shutil.move(str(companion), str(backup / companion.name))

        replacement = db.with_name(f".{db.name}.sync-{os.getpid()}-{time.time_ns()}")
        shutil.copy2(temporary_db, replacement)
        os.replace(replacement, db)

    final_source = source_fingerprint(home)
    state_path = _state_path(manager_dir)
    state = _read_json(state_path)
    accounts = state.setdefault("accounts", {})
    synced_at = datetime.now().astimezone().isoformat()
    accounts[account_key] = {
        "account": account_name,
        "home": str(home),
        "source_sha256": final_source["sha256"],
        "source_files": final_source["files"],
        "source_bytes": final_source["bytes"],
        "thread_count": after,
        "synced_at": synced_at,
        "backup": str(backup),
    }
    state["schema_version"] = 1
    _write_json(state_path, state)
    pruned_backups = _prune_backups(backup.parent)
    return {
        "ok": True,
        "skipped": False,
        "account": account_name,
        "home": str(home),
        "before": before,
        "after": after,
        "added": max(0, after - max(before, 0)),
        "backup": str(backup),
        "synced_at": synced_at,
        "token_calls": 0,
        "pruned_backups": pruned_backups,
    }
