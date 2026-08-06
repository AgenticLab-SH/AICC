from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import codex_thread_index as index


def create_state(path: Path, ids: list[str]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("create table threads (id text primary key)")
        connection.executemany("insert into threads(id) values (?)", [(value,) for value in ids])
        connection.commit()
    finally:
        connection.close()


class ThreadIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.manager = root / "manager"
        self.home = root / "home"
        self.home.mkdir()
        sessions = self.home / "sessions" / "2026" / "07" / "27"
        sessions.mkdir(parents=True)
        (sessions / "rollout-test.jsonl").write_text("{}\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_fingerprint_tracks_thread_files_not_growing_content(self):
        first = index.source_fingerprint(self.home)
        rollout = next((self.home / "sessions").rglob("*.jsonl"))
        rollout.write_text("{}\n{}\n", encoding="utf-8")
        second = index.source_fingerprint(self.home)
        self.assertEqual(first["files"], 1)
        self.assertEqual(first["sha256"], second["sha256"])
        (rollout.parent / "rollout-new.jsonl").write_text("{}\n", encoding="utf-8")
        third = index.source_fingerprint(self.home)
        self.assertNotEqual(second["sha256"], third["sha256"])

    def test_fingerprint_tracks_archived_rollouts(self):
        first = index.source_fingerprint(self.home)
        archived = self.home / "archived_sessions"
        archived.mkdir()
        (archived / "rollout-archived.jsonl").write_text("{}\n", encoding="utf-8")

        second = index.source_fingerprint(self.home)

        self.assertEqual(second["files"], first["files"] + 1)
        self.assertNotEqual(second["sha256"], first["sha256"])

    def test_fingerprint_ignores_empty_rollout_remnants(self):
        first = index.source_fingerprint(self.home)
        (self.home / "sessions" / "rollout-empty.jsonl").touch()

        second = index.source_fingerprint(self.home)

        self.assertEqual(second["files"], first["files"])
        self.assertEqual(second["sha256"], first["sha256"])

    def test_backfill_requests_active_and_archived_lists(self):
        requests = [
            message for message in index._backfill_messages()
            if message.get("method") == "thread/list"
        ]
        self.assertEqual([request["params"]["archived"] for request in requests], [False, True])
        self.assertEqual({request["id"] for request in requests}, {2, 3})

    def test_reset_backfill_state_changes_only_the_supplied_copy(self):
        source = self.home / "state_5.sqlite"
        create_state(source, ["old"])
        connection = sqlite3.connect(source)
        try:
            connection.execute(
                "create table backfill_state (id integer primary key, status text not null)"
            )
            connection.execute("insert into backfill_state values (1, 'complete')")
            connection.commit()
        finally:
            connection.close()
        copied = self.home / "copied.sqlite"
        index._sqlite_backup(source, copied)

        self.assertTrue(index._reset_backfill_state(copied))

        source_connection = sqlite3.connect(source)
        copied_connection = sqlite3.connect(copied)
        try:
            self.assertEqual(source_connection.execute("select count(*) from backfill_state").fetchone()[0], 1)
            self.assertEqual(copied_connection.execute("select count(*) from backfill_state").fetchone()[0], 0)
        finally:
            source_connection.close()
            copied_connection.close()

    def test_scan_home_exposes_rollouts_without_auth_and_retargets_paths(self):
        archived = self.home / "archived_sessions"
        archived.mkdir()
        scan_home = Path(self.temp.name) / "scan-home"
        index._prepare_scan_home(self.home, scan_home)

        self.assertTrue((scan_home / "sessions").is_symlink())
        self.assertTrue((scan_home / "archived_sessions").is_symlink())
        self.assertFalse((scan_home / "auth.json").exists())

        database = self.home / "paths.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute("create table threads (id text primary key, rollout_path text not null)")
            connection.execute(
                "insert into threads values (?, ?)",
                ("one", str(scan_home / "archived_sessions" / "rollout-one.jsonl")),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(index._retarget_rollout_paths(database, scan_home, self.home), 1)
        connection = sqlite3.connect(database)
        try:
            rollout_path = connection.execute("select rollout_path from threads").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(rollout_path, str(self.home / "archived_sessions" / "rollout-one.jsonl"))

    def test_retarget_repairs_paths_from_previous_scan_homes(self):
        scan_home = Path(self.temp.name) / "cm-thread-index-current" / "scan-home"
        database = self.home / "historical-paths.sqlite"
        historical = (
            Path("/private/var/folders/example/T/cm-thread-index-old/scan-home")
            / "sessions" / "2026" / "08" / "02" / "rollout-old.jsonl"
        )
        connection = sqlite3.connect(database)
        try:
            connection.execute("create table threads (id text primary key, rollout_path text not null)")
            connection.executemany(
                "insert into threads values (?, ?)",
                [
                    ("old", str(historical)),
                    ("current", str(scan_home / "archived_sessions" / "rollout-current.jsonl")),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(index._retarget_rollout_paths(database, scan_home, self.home), 2)
        connection = sqlite3.connect(database)
        try:
            paths = dict(connection.execute("select id, rollout_path from threads"))
        finally:
            connection.close()
        self.assertEqual(
            paths["old"],
            str(self.home / "sessions" / "2026" / "08" / "02" / "rollout-old.jsonl"),
        )
        self.assertEqual(
            paths["current"],
            str(self.home / "archived_sessions" / "rollout-current.jsonl"),
        )
        self.assertEqual(index._verify_database(database), 2)

    def test_verify_rejects_leaked_scan_home_paths(self):
        database = self.home / "leaked-path.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute("create table threads (id text primary key, rollout_path text not null)")
            connection.execute(
                "insert into threads values (?, ?)",
                (
                    "leaked",
                    "/tmp/cm-thread-index-abandoned/scan-home/sessions/rollout.jsonl",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "temporary rollout paths"):
            index._verify_database(database)

    def test_active_home_is_never_modified(self):
        state = self.home / "state_5.sqlite"
        create_state(state, ["old"])
        before = state.read_bytes()
        result = index.synchronize(
            self.manager,
            account_key="account",
            account_name="account@example.invalid",
            home=self.home,
            codex_exe=Path(sys.executable),
            active=True,
        )
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "home_active")
        self.assertEqual(state.read_bytes(), before)

    def test_status_detects_leaked_scan_home_paths(self):
        database = self.home / "state_5.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute("create table threads (id text primary key, rollout_path text not null)")
            connection.execute(
                "insert into threads values (?, ?)",
                (
                    "leaked",
                    "/tmp/cm-thread-index-abandoned/scan-home/sessions/rollout.jsonl",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        fingerprint = index.source_fingerprint(self.home)
        index._write_json(index._state_path(self.manager), {
            "accounts": {"account": {"source_sha256": fingerprint["sha256"]}}
        })

        result = index.status(self.manager, account_key="account", home=self.home)

        self.assertEqual(result["temporary_paths"], 1)
        self.assertFalse(result["up_to_date"])

    def test_sync_uses_copy_preserves_existing_rows_and_creates_backup(self):
        state = self.home / "state_5.sqlite"
        create_state(state, ["old"])

        def fake_backfill(home, sqlite_home, codex_exe):
            connection = sqlite3.connect(sqlite_home / "state_5.sqlite")
            try:
                connection.execute("insert into threads(id) values ('new')")
                connection.commit()
            finally:
                connection.close()
            return {"thread_list_ok": True}

        with mock.patch("codex_thread_index._run_backfill", side_effect=fake_backfill):
            result = index.synchronize(
                self.manager,
                account_key="account",
                account_name="account@example.invalid",
                home=self.home,
                codex_exe=Path(sys.executable),
            )

        connection = sqlite3.connect(state)
        try:
            ids = {row[0] for row in connection.execute("select id from threads")}
        finally:
            connection.close()
        self.assertEqual(ids, {"old", "new"})
        self.assertEqual(result["before"], 1)
        self.assertEqual(result["after"], 2)
        self.assertEqual(result["token_calls"], 0)
        self.assertTrue((Path(result["backup"]) / "state_5.sqlite").is_file())
        self.assertTrue(index.status(self.manager, account_key="account", home=self.home)["up_to_date"])

    def test_backup_retention_is_bounded(self):
        root = self.manager / "backups"
        for name in ("20260727_000001", "20260727_000002", "20260727_000003"):
            (root / name).mkdir(parents=True)
        removed = index._prune_backups(root, keep=2)
        self.assertEqual(removed, 1)
        self.assertFalse((root / "20260727_000001").exists())
        self.assertTrue((root / "20260727_000003").exists())


if __name__ == "__main__":
    unittest.main()
