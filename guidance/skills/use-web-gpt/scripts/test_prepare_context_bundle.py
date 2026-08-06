#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).with_name("prepare_context_bundle.py")
SPEC = importlib.util.spec_from_file_location("prepare_context_bundle", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ContextBundleTests(unittest.TestCase):
    def test_direct_mode_for_ten_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = []
            for index in range(10):
                path = root / f"doc-{index}.md"
                path.write_text(f"document {index}\n", encoding="utf-8")
                paths.append(str(path))
            plan = MODULE.build_plan(paths, None, 1, [])
            self.assertEqual("direct", plan["mode"])
            self.assertEqual(10, len(plan["attachments"]))

    def test_zip_mode_for_eleven_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "out"
            paths = []
            for index in range(11):
                path = root / f"source-{index}.txt"
                path.write_text(f"source {index}\n", encoding="utf-8")
                paths.append(str(path))
            plan = MODULE.build_plan(paths, str(output), 1, [])
            self.assertEqual("zip", plan["mode"])
            self.assertEqual(1, len(plan["attachments"]))
            with zipfile.ZipFile(plan["zip_path"], "r") as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(11, manifest["file_count"])
                self.assertEqual(12, len(archive.namelist()))
                self.assertNotIn("original_path", manifest["files"][0])
                self.assertEqual("source-0.txt", manifest["files"][0]["display_name"])
                self.assertNotIn(str(root), archive.read("manifest.json").decode("utf-8"))

    def test_sensitive_and_symlink_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            secret = root / "auth.json"
            secret.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sensitive-looking"):
                MODULE.build_plan([str(secret)], None, 1, [])

            target = root / "safe.txt"
            target.write_text("safe", encoding="utf-8")
            link = root / "linked.txt"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                MODULE.build_plan([str(link)], None, 1, [])

    def test_high_confidence_secret_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "notes.txt"
            path.write_text("token=ghp_abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "high-confidence secret pattern"):
                MODULE.build_plan([str(path)], None, 1, [])


if __name__ == "__main__":
    unittest.main()
